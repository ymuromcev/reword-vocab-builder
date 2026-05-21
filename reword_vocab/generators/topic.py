"""Topic-mode generator: prompt LLM with topic, produce word list.

Public API:

    from reword_vocab.generators.topic import generate

    words = generate("PM interview vocabulary", target_count=200)
    # [{"word": "leverage", "part_of_speech": "verb",
    #   "context_note": "common in strategy"}, ...]

The LLM backend is injected so unit tests run without network access.
``LLMClient`` is a Protocol with a single ``.complete(system, user)``
method returning a JSON string. The default factory wraps the Anthropic
SDK (``claude-sonnet-4-6``) and reads ``ANTHROPIC_API_KEY`` from env.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol


# Default Anthropic model. Pinned here so CLI / callers can override.
DEFAULT_MODEL = "claude-sonnet-4-6"

# Hard cap on retries — RFC-007 caps at 2 LLM calls total.
MAX_CALLS = 2

# Over-request factor for the first call. RFC-007: target_count + 20%.
OVERREQUEST_FACTOR = 1.2

# Characters that disqualify a word (digits / brand-y / math-y noise).
_BAD_CHAR_PATTERN = re.compile(r"[\d$%→/+]|x[Kk]")

# Allowed part-of-speech values, per RFC-007 prompt spec.
_ALLOWED_POS = frozenset(
    {"verb", "noun", "adjective", "adverb", "phrase", "idiom"}
)


SYSTEM_PROMPT_TEMPLATE = """\
You are an expert vocabulary curator for English learners preparing for
{topic} contexts. Output ONLY a JSON array of objects with fields:
word, part_of_speech (verb|noun|adjective|adverb|phrase|idiom),
context_note (short, <=8 words).

Rules:
- Base form only. Verbs without "to" prefix.
- No obvious words (project, team, work, manager, plan).
- No company names, no brand names.
- No duplicates.
- Mix: ~40% verbs/phrasal verbs, ~30% nouns, ~20% adjectives/adverbs,
  ~10% idioms.
- Cover collocations a non-native speaker would not naturally produce.
- Output JSON only. No prose, no markdown fences.
"""


class LLMClient(Protocol):
    """Minimal LLM interface used by ``generate``.

    Implementations return the raw text completion. The topic
    generator handles JSON parsing and validation itself so the
    Protocol stays narrow and easy to fake in tests.
    """

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - protocol
        ...


def generate(
    topic: str,
    target_count: int = 200,
    *,
    llm: LLMClient | None = None,
) -> list[dict]:
    """Generate a deduplicated, sanitized vocab list for ``topic``.

    Args:
        topic: Free-form domain string (e.g. "PM interview vocabulary").
        target_count: Desired list length after dedup + sanitation.
        llm: LLM client implementing the ``LLMClient`` protocol. If
            ``None``, the default Anthropic-backed client is built
            lazily — useful for the CLI but never invoked from tests.

    Returns:
        A list of ``{"word", "part_of_speech", "context_note"}`` dicts.

    Raises:
        ValueError: if ``topic`` is empty/whitespace.
    """
    if not topic or not topic.strip():
        raise ValueError("topic must be a non-empty string")

    if target_count <= 0:
        raise ValueError("target_count must be positive")

    client = llm if llm is not None else _build_default_client()
    system = SYSTEM_PROMPT_TEMPLATE.format(topic=topic.strip())

    # First call: ask for an over-sampled list, then dedup + sanitize.
    first_ask = max(int(target_count * OVERREQUEST_FACTOR), target_count)
    user_msg = (
        f"Topic: {topic.strip()}\n\n"
        f"Produce approximately {first_ask} entries as a JSON array."
    )
    raw = client.complete(system, user_msg)
    items = _parse_and_clean(raw)

    calls_used = 1
    if len(items) < target_count and calls_used < MAX_CALLS:
        seen = sorted({item["word"].lower() for item in items})
        # Compact "seen" to keep the prompt small for very long lists.
        seen_blob = ", ".join(seen)
        missing = target_count - len(items)
        extend_msg = (
            f"Topic: {topic.strip()}\n\n"
            f"Extend the list with approximately {missing + 20} more "
            f"entries. Avoid these words (already covered): {seen_blob}.\n"
            f"Return ONLY the new entries as a JSON array."
        )
        raw_more = client.complete(system, extend_msg)
        items.extend(_parse_and_clean(raw_more))
        items = _dedup(items)

    # Trim to target_count if we overshot.
    return items[:target_count]


def _parse_and_clean(raw: str) -> list[dict]:
    """Parse JSON from an LLM completion and sanitize entries."""
    parsed = _parse_json_array(raw)
    cleaned: list[dict] = []
    for entry in parsed:
        item = _sanitize_entry(entry)
        if item is not None:
            cleaned.append(item)
    return _dedup(cleaned)


def _parse_json_array(raw: str) -> list[Any]:
    """Extract a JSON array from ``raw``.

    Tolerates leading/trailing prose or markdown fences the LLM might
    add despite the instructions.
    """
    text = raw.strip()
    if not text:
        return []

    # Quick path: clean JSON.
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        pass

    # Strip markdown fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        try:
            parsed = json.loads(fence.group(1).strip())
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            pass

    # Last resort: find the first '[' and matching ']'.
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []

    return []


def _sanitize_entry(entry: Any) -> dict | None:
    """Return a normalized entry or ``None`` if it fails validation."""
    if not isinstance(entry, dict):
        return None

    word = entry.get("word")
    pos = entry.get("part_of_speech")
    note = entry.get("context_note")

    if not isinstance(word, str):
        return None
    word = word.strip()
    if not word:
        return None
    if _BAD_CHAR_PATTERN.search(word):
        return None

    if not isinstance(pos, str) or pos.strip().lower() not in _ALLOWED_POS:
        return None

    if note is None:
        note = ""
    elif not isinstance(note, str):
        return None

    return {
        "word": word,
        "part_of_speech": pos.strip().lower(),
        "context_note": note.strip(),
    }


def _dedup(items: list[dict]) -> list[dict]:
    """Deduplicate by lowercased word, keeping first occurrence."""
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        key = item["word"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _build_default_client() -> LLMClient:
    """Lazy factory for the real Anthropic-backed client.

    Imports ``anthropic`` only when actually needed so tests that inject
    a fake client run without the SDK installed.
    """
    try:
        import anthropic  # type: ignore
    except ImportError as exc:  # pragma: no cover - import-time guard
        raise RuntimeError(
            "anthropic SDK is required for the default LLM client. "
            "Install with: pip install 'anthropic>=0.40'"
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:  # pragma: no cover - env guard
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set; cannot build default LLM client."
        )

    return _AnthropicClient(anthropic.Anthropic(api_key=api_key))


class _AnthropicClient:
    """Thin adapter wrapping the Anthropic SDK to the LLMClient shape."""

    def __init__(self, client: Any, model: str = DEFAULT_MODEL) -> None:
        self._client = client
        self._model = model

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - network
        message = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # SDK returns a list of content blocks; concatenate text blocks.
        chunks: list[str] = []
        for block in getattr(message, "content", []):
            text = getattr(block, "text", None)
            if text:
                chunks.append(text)
        return "".join(chunks)
