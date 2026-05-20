"""Source-mode generator: extract vocabulary from PDF/EPUB/text/HTML.

Per RFC-008. Reads a file, chunks the text, calls an LLM per chunk
asking for JSON vocab items grounded in the chunk (each item carries
a verbatim `source_quote`), filters out items whose quote is not a
substring of the chunk (hallucination guard), and dedups across chunks.

The LLM client is injected via a Protocol so unit tests stay offline.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Protocol


# ----- Public exceptions -----------------------------------------------------


class UnsupportedSourceError(Exception):
    """Raised when the file extension isn't supported by source-mode."""


class EmptySourceError(ValueError):
    """Raised when the parsed source contains no extractable text."""


# ----- LLM client Protocol (same shape as BL-07) -----------------------------


class LLMClient(Protocol):
    """Minimal client surface required by the source generator.

    Implementations return raw text (expected to be a JSON array of
    objects with `word`, `part_of_speech`, `source_quote`). The real
    backend is wired in `cli.py`; tests inject a fake.
    """

    def complete(self, system: str, user: str) -> str:  # pragma: no cover
        ...


# ----- Constants -------------------------------------------------------------


MAX_CHUNK_TOKENS = 4000
# Heuristic from RFC: 1 token ~= 4 characters.
_CHARS_PER_TOKEN = 4
MAX_CHUNK_CHARS = MAX_CHUNK_TOKENS * _CHARS_PER_TOKEN


SYSTEM_PROMPT = """You are an expert vocabulary curator for English learners.

Given an instruction and a passage of text, return ONLY a JSON array of
objects with these fields:
  - word: the base-form English word or short phrase
  - part_of_speech: one of verb | noun | adjective | adverb | phrase | idiom
  - source_quote: the EXACT sentence from the passage containing the word,
    copied verbatim — no paraphrasing, no truncation

Rules:
- Base form only. Verbs without "to" prefix.
- No company / brand names, no proper nouns.
- No duplicates within your output.
- `source_quote` MUST appear verbatim in the passage I gave you.
- Respond with valid JSON only — no prose, no markdown fence.
"""


# ----- File parsers ----------------------------------------------------------


def _read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_html(path: Path) -> str:
    from bs4 import BeautifulSoup

    raw = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw, "html.parser")
    # Drop scripts / styles to keep noise out.
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    text = "\n".join(p for p in parts if p)
    if not text.strip():
        # Image-only PDF — OCR is out of scope per RFC.
        raise UnsupportedSourceError(
            f"{path.name}: no extractable text. Scanned PDFs need OCR "
            "(out of scope)."
        )
    return text


def _read_epub(path: Path) -> str:
    from bs4 import BeautifulSoup
    from ebooklib import ITEM_DOCUMENT, epub

    book = epub.read_epub(str(path))
    parts: list[str] = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        parts.append(soup.get_text(separator=" ", strip=True))
    return "\n".join(parts)


_PARSERS = {
    ".txt": _read_txt,
    ".md": _read_txt,
    ".html": _read_html,
    ".htm": _read_html,
    ".pdf": _read_pdf,
    ".epub": _read_epub,
}


def _normalize_whitespace(text: str) -> str:
    """Collapse runs of inline whitespace, preserve paragraph breaks.

    Real-world parsers (BeautifulSoup, pypdf) leak inline newlines from
    wrapped source lines. We collapse those so the LLM gets clean text
    and `source_quote` substring checks aren't tripped by stray `\n  `.
    """
    # First normalize Windows line endings.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Preserve blank lines as paragraph separators (mark them).
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    # Collapse intra-paragraph whitespace runs (incl. single newlines).
    parts = text.split("\n\n")
    parts = [re.sub(r"\s+", " ", p).strip() for p in parts]
    return "\n\n".join(p for p in parts if p)


def _read_source(path: Path) -> str:
    suffix = path.suffix.lower()
    parser = _PARSERS.get(suffix)
    if parser is None:
        raise UnsupportedSourceError(
            f"{path.name}: extension {suffix!r} is not supported. "
            f"Supported: {sorted(_PARSERS)}"
        )
    return _normalize_whitespace(parser(path))


# ----- Chunking --------------------------------------------------------------


def _chunk_text(text: str, max_chars: int | None = None) -> list[str]:
    """Split text into chunks of <= max_chars on paragraph boundaries.

    Falls back to hard-cutting when a single paragraph exceeds the budget.
    Empty input returns an empty list.
    """
    # Resolve the budget at call time so tests can monkeypatch the constant.
    if max_chars is None:
        max_chars = MAX_CHUNK_CHARS
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for para in paragraphs:
        p = para.strip()
        if not p:
            continue
        # Hard-cut paragraphs that exceed the chunk budget on their own.
        if len(p) > max_chars:
            if buf:
                chunks.append("\n\n".join(buf))
                buf, size = [], 0
            for i in range(0, len(p), max_chars):
                chunks.append(p[i : i + max_chars])
            continue
        if size + len(p) + 2 > max_chars and buf:
            chunks.append("\n\n".join(buf))
            buf, size = [p], len(p)
        else:
            buf.append(p)
            size += len(p) + 2
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


# ----- LLM call + parsing ----------------------------------------------------


def _parse_json_array(raw: str) -> list[dict]:
    """Parse a JSON array, tolerating a stray markdown fence or whitespace."""
    raw = raw.strip()
    if raw.startswith("```"):
        # Strip code fences if the model misbehaves.
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Last-ditch: extract the outermost [...] block.
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _extract_from_chunk(
    chunk: str,
    instruction: str,
    llm: LLMClient,
    chunk_index: int,
) -> list[dict]:
    user_msg = f"Instruction: {instruction}\n\nText:\n{chunk}"
    raw = llm.complete(SYSTEM_PROMPT, user_msg)
    items = _parse_json_array(raw)

    cleaned: list[dict] = []
    for item in items:
        word = (item.get("word") or "").strip()
        pos = (item.get("part_of_speech") or "").strip().lower()
        quote = (item.get("source_quote") or "").strip()
        if not word or not quote:
            continue
        # Hallucination guard — drop items whose quote is not in the chunk.
        if quote not in chunk:
            continue
        cleaned.append(
            {
                "word": word,
                "part_of_speech": pos,
                "source_quote": quote,
                "context_note": f"chunk {chunk_index + 1}",
            }
        )
    return cleaned


# ----- Dedup + merge ---------------------------------------------------------


def normalize_key(word: str) -> str:
    """Normalize a word for dedup. Mirrors BL-02 helper shape."""
    key = word.strip().lower()
    if key.startswith("to "):
        key = key[3:]
    return key


def _merge_items(items: list[dict]) -> list[dict]:
    """Dedup by normalize_key(word); keep the longest source_quote per key."""
    by_key: dict[str, dict] = {}
    for item in items:
        key = normalize_key(item["word"])
        if not key:
            continue
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = item
            continue
        # Keep the entry with the longer (more informative) source quote.
        if len(item["source_quote"]) > len(existing["source_quote"]):
            by_key[key] = item
    return list(by_key.values())


# ----- Public entry point ----------------------------------------------------


def extract(
    source_path: str | Path,
    instruction: str,
    *,
    llm: LLMClient | None = None,
) -> list[dict]:
    """Extract vocabulary grounded in `source_path` per `instruction`.

    Returns a list of dicts with keys: word, part_of_speech, source_quote,
    context_note. Words are deduped across chunks by normalized key.
    """
    if not instruction or not instruction.strip():
        raise ValueError("instruction must be a non-empty string")
    if llm is None:
        raise ValueError(
            "an LLMClient must be provided (CLI wires the real client)"
        )

    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    text = _read_source(path)
    chunks = _chunk_text(text)
    if not chunks:
        raise EmptySourceError(f"{path.name}: no extractable text")

    collected: list[dict] = []
    for idx, chunk in enumerate(chunks):
        collected.extend(_extract_from_chunk(chunk, instruction, llm, idx))

    return _merge_items(collected)
