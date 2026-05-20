"""Detect verbs and prefix with 'to ' per Reword convention.

Implements RFC-004 / BL-04.

Pipeline (first hit wins):
    1. Manual override file (``config/verb_overrides.yaml``).
    2. ``to ``-prefixed input is stripped and re-evaluated (idempotency).
    3. Single-word, base-form verb per spaCy (``token.tag_ == "VB"``).
       Gerunds (``VBG``), past (``VBD``), participles (``VBN``) rejected.
    4. Phrasal verb: two tokens, head ``VB`` + particle/preposition from
       a small allow-list (``back, in, out, up, down, into, over,
       through, off, on``).
    5. Idiom (>=2 tokens): first token is ``VB``.
    6. Default: not a verb.

Setup
-----
spaCy's small English model is required for real classification::

    python -m spacy download en_core_web_sm

The model is **not** auto-downloaded on import — that would make first
runs slow and tests non-hermetic. Tests inject a fake POS tagger via
:func:`set_nlp`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PARTICLES: frozenset[str] = frozenset(
    {
        "back",
        "in",
        "out",
        "up",
        "down",
        "into",
        "over",
        "through",
        "off",
        "on",
    }
)

_DEFAULT_OVERRIDES_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "verb_overrides.yaml"
)


# ---------------------------------------------------------------------------
# spaCy lazy singleton
# ---------------------------------------------------------------------------


class _Token(Protocol):
    """Subset of the spaCy ``Token`` interface used here."""

    text: str
    tag_: str


class _Doc(Protocol):
    """Subset of the spaCy ``Doc`` interface used here."""

    def __iter__(self) -> Iterable[_Token]: ...
    def __len__(self) -> int: ...
    def __getitem__(self, index: int) -> _Token: ...


NLP = Callable[[str], _Doc]

_nlp: NLP | None = None


def set_nlp(custom: NLP | None) -> None:
    """Inject a callable ``str -> Doc`` for tests. Pass ``None`` to reset."""

    global _nlp
    _nlp = custom


def _get_nlp() -> NLP:
    """Load ``en_core_web_sm`` on first use; cache for the rest of the run."""

    global _nlp
    if _nlp is not None:
        return _nlp
    try:
        import spacy  # local import — keeps module import light
    except ImportError as exc:  # pragma: no cover - environmental
        raise RuntimeError(
            "spaCy is not installed. Add `spacy` to dependencies."
        ) from exc
    try:
        _nlp = spacy.load("en_core_web_sm")
    except OSError as exc:  # pragma: no cover - environmental
        raise RuntimeError(
            "spaCy model 'en_core_web_sm' is not installed. Run "
            "`python -m spacy download en_core_web_sm`."
        ) from exc
    return _nlp


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def _load_overrides(path: Path = _DEFAULT_OVERRIDES_PATH) -> tuple[set[str], set[str]]:
    """Return (verbs, not_verbs) sets, lower-cased and stripped.

    Missing / empty / malformed files yield two empty sets — the
    override mechanism is optional.
    """

    if not path.exists():
        return set(), set()
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return set(), set()
    if not isinstance(data, dict):
        return set(), set()
    verbs = {str(w).strip().lower() for w in (data.get("verbs") or []) if w}
    not_verbs = {str(w).strip().lower() for w in (data.get("not_verbs") or []) if w}
    return verbs, not_verbs


_OVERRIDE_VERBS, _OVERRIDE_NOT_VERBS = _load_overrides()


def reload_overrides(path: Path | None = None) -> None:
    """Re-read the override file. Useful for tests and long-running procs."""

    global _OVERRIDE_VERBS, _OVERRIDE_NOT_VERBS
    _OVERRIDE_VERBS, _OVERRIDE_NOT_VERBS = _load_overrides(
        path or _DEFAULT_OVERRIDES_PATH
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _normalize(word: str) -> str:
    return word.strip().lower()


def _strip_to(word: str) -> str:
    return word[3:] if word.startswith("to ") else word


def is_verb(word: str) -> bool:
    """True iff ``word`` should be treated as an English verb.

    See module docstring for the full pipeline.
    """

    if not word or not word.strip():
        return False

    normalized = _normalize(word)
    bare = _strip_to(normalized)

    # 1. Manual override — checked against the stripped form so that
    #    `to align` and `align` both resolve via the same key.
    if bare in _OVERRIDE_NOT_VERBS:
        return False
    if bare in _OVERRIDE_VERBS:
        return True

    # 2. `to `-prefix: treat as verb if and only if the bare form is one.
    if normalized != bare:
        return is_verb(bare)

    tokens = bare.split()
    if not tokens:
        return False

    nlp = _get_nlp()
    doc = nlp(bare)
    doc_tokens = list(doc)
    if not doc_tokens:
        return False

    # 3. Single word, base form.
    if len(tokens) == 1:
        return len(doc_tokens) == 1 and doc_tokens[0].tag_ == "VB"

    # 4. Phrasal verb (two words).
    if len(tokens) == 2 and len(doc_tokens) >= 2:
        head, tail = doc_tokens[0], doc_tokens[1]
        if head.tag_ == "VB" and tail.text.lower() in PARTICLES:
            return True

    # 5. Idiom — first token is VB.
    if doc_tokens[0].tag_ == "VB":
        return True

    return False


def to_prefix(word: str) -> str:
    """Return ``word`` with ``to `` prepended iff it is a verb. Idempotent."""

    if not word:
        return word
    if word.startswith("to "):
        return word
    return f"to {word}" if is_verb(word) else word
