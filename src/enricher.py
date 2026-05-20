"""Example sentences + RU translation enricher (BL-10 / RFC-010).

Given a word object, ask an LLM for 5 fields:
``ru``, ``ex1_en``, ``ex1_ru``, ``ex2_en``, ``ex2_ru`` and merge them
into the word object.

The LLM client is injected (``Protocol`` with ``.complete``) so unit
tests stay offline.  Output is validated: all 5 fields must be
non-empty, and English example sentences must not contain any
forbidden symbol (``$ % → + / K x`` and a few currency markers).
On the first violation we retry once with an explicit complaint about
the offending symbol.  Max 2 LLM calls per word / batch.
"""

from __future__ import annotations

import json
import re
from typing import Iterable, Protocol


# Forbidden characters in English example sentences.  Per RFC-010 these
# break Reword's read-aloud (numbers + ``K`` / ``x`` abbreviations,
# currency / operator glyphs).  Detection is a literal substring check.
FORBIDDEN_SYMBOLS: tuple[str, ...] = (
    "$",
    "%",
    "→",  # →
    "+",
    "/",
    "K",
    "x",
    "€",  # €
    "£",  # £
    "¥",  # ¥
)

# Required output keys produced by the LLM per word.
REQUIRED_FIELDS: tuple[str, ...] = ("ru", "ex1_en", "ex1_ru", "ex2_en", "ex2_ru")

# How many words to send to the LLM in one batched call.
BATCH_SIZE = 20

# Hard cap on LLM calls per ``enrich`` / per batch in ``enrich_many``.
MAX_CALLS = 2


SYSTEM_PROMPT = """\
You are a bilingual translator (English <-> Russian) helping a learner
build vocabulary. Output JSON with keys: ru, ex1_en, ex1_ru, ex2_en,
ex2_ru.

Rules:
- ru: 1-3 word natural Russian translation. Not a literal calque.
- ex1_en: short (<=10 words), conversational.
- ex2_en: medium (10-18 words), shows a different usage context.
- ex*_ru: natural Russian rendering, not word-for-word.
- ABSOLUTELY NO of these symbols in any English example:
  $, %, ->, +, /, K, x, $$ (anything dollar-related), parens with
  numbers. They break Reword's read-aloud.
- Quote signals: examples are spoken aloud by TTS - anything that
  does not pronounce naturally is forbidden.
"""


class LLMClient(Protocol):
    """Minimal LLM client contract used across the project."""

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - protocol
        ...


class EnrichmentError(RuntimeError):
    """Raised when an LLM response cannot be turned into a valid record."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enrich(word_obj: dict, *, llm: LLMClient) -> dict:
    """Enrich a single word object with ru + two example pairs.

    Parameters
    ----------
    word_obj:
        Must contain ``word``.  Extra keys (including ``source_quote``)
        are preserved on the output.
    llm:
        Injected client implementing :class:`LLMClient`.

    Returns
    -------
    dict
        Input merged with ``ru``, ``ex1_en``, ``ex1_ru``, ``ex2_en``,
        ``ex2_ru``.

    Raises
    ------
    EnrichmentError
        If two consecutive LLM responses cannot pass validation.
    """
    word = (word_obj.get("word") or "").strip()
    if not word:
        raise EnrichmentError("word_obj.word is empty")

    source_quote = (word_obj.get("source_quote") or "").strip() or None
    user_msg = _build_single_user_message(word, source_quote)

    fields = _call_with_retry(
        llm=llm,
        user_msg_builder=lambda complaint: (
            user_msg if complaint is None else f"{user_msg}\n\n{complaint}"
        ),
        parse=lambda raw: _parse_single(raw),
    )

    out = dict(word_obj)
    out.update(fields)
    return out


def enrich_many(words: list[dict], *, llm: LLMClient) -> list[dict]:
    """Enrich a list of word objects, batching 20 per LLM call.

    Each batch is one LLM round-trip whose response is a JSON object
    keyed by the word string.  A batch may retry once if any English
    example contains a forbidden symbol; that still counts as the same
    batch (max 2 calls).
    """
    out: list[dict] = []
    for chunk_start in range(0, len(words), BATCH_SIZE):
        chunk = words[chunk_start : chunk_start + BATCH_SIZE]
        enriched_chunk = _enrich_batch(chunk, llm=llm)
        out.extend(enriched_chunk)
    return out


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _enrich_batch(chunk: list[dict], *, llm: LLMClient) -> list[dict]:
    if not chunk:
        return []

    user_msg = _build_batch_user_message(chunk)
    keys = [(item.get("word") or "").strip() for item in chunk]
    if any(not k for k in keys):
        raise EnrichmentError("batch contains a word_obj with empty word")

    fields_by_word = _call_with_retry(
        llm=llm,
        user_msg_builder=lambda complaint: (
            user_msg if complaint is None else f"{user_msg}\n\n{complaint}"
        ),
        parse=lambda raw: _parse_batch(raw, keys),
    )

    result: list[dict] = []
    for item, key in zip(chunk, keys):
        merged = dict(item)
        merged.update(fields_by_word[key])
        result.append(merged)
    return result


def _call_with_retry(*, llm, user_msg_builder, parse):
    """Run up to ``MAX_CALLS`` LLM calls with forbidden-symbol retry.

    ``user_msg_builder(complaint)`` returns the user prompt; on retry
    we pass a complaint string naming the offending symbol so the LLM
    can correct itself.  ``parse(raw)`` turns the raw text into either
    a single field dict or a {word: fields} map.
    """
    complaint: str | None = None
    last_error: Exception | None = None

    for attempt in range(MAX_CALLS):
        user_msg = user_msg_builder(complaint)
        raw = llm.complete(SYSTEM_PROMPT, user_msg)
        try:
            parsed = parse(raw)
        except EnrichmentError as exc:
            last_error = exc
            complaint = f"Previous response was invalid: {exc}. Reissue valid JSON."
            continue

        bad_symbol = _find_forbidden(parsed)
        if bad_symbol is None:
            return parsed

        last_error = EnrichmentError(f"forbidden symbol {bad_symbol!r} in example")
        complaint = (
            f"Previous response contained {bad_symbol!r} in an English "
            "example. Remove it and reissue valid JSON."
        )

    raise EnrichmentError(
        f"failed to produce clean enrichment after {MAX_CALLS} calls: {last_error}"
    )


def _find_forbidden(parsed):
    """Return the first forbidden symbol found, or ``None``.

    ``parsed`` is either a single fields dict (for ``enrich``) or a
    ``{word: fields}`` map (for ``enrich_many``).
    """
    if not isinstance(parsed, dict):
        return None

    # Detect single vs. batch shape: single shape contains REQUIRED_FIELDS
    # directly; batch shape's values do.
    if all(field in parsed for field in REQUIRED_FIELDS):
        candidates = [parsed]
    else:
        candidates = list(parsed.values())

    for fields in candidates:
        for key in ("ex1_en", "ex2_en"):
            value = fields.get(key, "")
            for sym in FORBIDDEN_SYMBOLS:
                if sym in value:
                    return sym
    return None


def _parse_single(raw: str) -> dict:
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise EnrichmentError("expected JSON object")
    fields = {k: _clean(data.get(k)) for k in REQUIRED_FIELDS}
    _require_all_fields(fields, context="word")
    return fields


def _parse_batch(raw: str, keys: Iterable[str]) -> dict:
    data = _load_json(raw)
    if not isinstance(data, dict):
        raise EnrichmentError("expected JSON object keyed by word")
    out: dict[str, dict] = {}
    for key in keys:
        sub = data.get(key)
        if not isinstance(sub, dict):
            raise EnrichmentError(f"missing entry for word {key!r}")
        fields = {f: _clean(sub.get(f)) for f in REQUIRED_FIELDS}
        _require_all_fields(fields, context=key)
        out[key] = fields
    return out


def _require_all_fields(fields: dict, *, context: str) -> None:
    for f in REQUIRED_FIELDS:
        if not fields.get(f):
            raise EnrichmentError(f"empty field {f!r} for {context}")


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _load_json(raw: str):
    """Tolerant JSON loader: tries direct parse, then largest ``{...}``."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_RE.search(raw or "")
        if not match:
            raise EnrichmentError("LLM response is not valid JSON")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise EnrichmentError(f"LLM response is not valid JSON: {exc}")


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _build_single_user_message(word: str, source_quote: str | None) -> str:
    lines = [
        f'Word: "{word}"',
        "",
        "Return a single JSON object with keys: ru, ex1_en, ex1_ru, "
        "ex2_en, ex2_ru.",
    ]
    if source_quote:
        lines.append("")
        lines.append(
            "Use this real sentence (lightly adapted if needed) as ex2_en:"
        )
        lines.append(f'"{source_quote}"')
    return "\n".join(lines)


def _build_batch_user_message(chunk: list[dict]) -> str:
    lines = [
        "Enrich each of the following words. Return a single JSON object "
        "keyed by the exact word string, where each value has keys: ru, "
        "ex1_en, ex1_ru, ex2_en, ex2_ru.",
        "",
    ]
    for item in chunk:
        word = (item.get("word") or "").strip()
        quote = (item.get("source_quote") or "").strip()
        if quote:
            lines.append(
                f'- "{word}" (use this real sentence, lightly adapted, '
                f'as ex2_en: "{quote}")'
            )
        else:
            lines.append(f'- "{word}"')
    return "\n".join(lines)
