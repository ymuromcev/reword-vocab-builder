"""US-English IPA transcription via CMU Pronouncing Dictionary.

Pipeline (per rfc/009-ipa.md):

1. Normalize the input: strip a leading ``to `` (Reword verb marker),
   lowercase, trim whitespace.
2. For each whitespace-separated token, look it up in the CMU
   Pronouncing Dictionary (the ``cmudict`` PyPI package, ships
   offline). Convert the first pronunciation from ARPAbet to IPA via a
   fixed table baked into this module. Stress markers are preserved:
   primary stress (``1``) becomes ``ˈ`` immediately before the
   syllable's vowel, secondary stress (``2``) becomes ``ˌ``, and
   unstressed schwa-ish vowels (``0``) collapse to the appropriate
   reduced form (``AH0`` → ``ə``, ``IH0`` → ``ɪ``, etc.).
3. Multi-token inputs (phrasal verbs, idioms) are joined by a single
   space inside one pair of square brackets.
4. If any token is missing from CMU, we fall back to the supplied
   ``llm`` callable. The prompt asks for the US IPA in square
   brackets only; the response is validated against
   ``^\\[[^\\[\\]]+\\]$``. A successful fallback returns
   ``(ipa, True)``; a missing or malformed response returns
   ``(None, True)``.

The ARPAbet → IPA table follows the convention documented in the CMU
Pronouncing Dictionary README and the Wikipedia ARPAbet article (which
is the de-facto reference used by ``g2p``-style projects). The mapping
is intentionally narrow to US-English approximants — rhotic ``ER`` →
``ɝ``/``ɚ``, dark ``L`` collapsed to ``l``, no glottal stop variants.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

try:  # pragma: no cover - import shim for offline CI
    import cmudict as _cmudict
except ImportError:  # pragma: no cover
    _cmudict = None


# ---------------------------------------------------------------------------
# ARPAbet → IPA mapping
# ---------------------------------------------------------------------------
#
# Vowels carry a trailing stress digit in CMU dict: ``0`` (unstressed),
# ``1`` (primary), ``2`` (secondary). We map the digit to the IPA stress
# mark (``ˈ`` / ``ˌ``) which is *prepended* before the syllable that
# contains that vowel, and we strip the digit from the vowel symbol
# itself. Unstressed vowels are reduced where convention calls for it
# (notably ``AH0`` → ``ə``, ``ER0`` → ``ɚ``).
#
# Sources: CMU Pronouncing Dictionary README (cmudict.0.7b) and the
# ARPAbet/IPA reference table maintained at en.wikipedia.org/wiki/ARPABET.

_ARPABET_TO_IPA: dict[str, str] = {
    # --- Vowels (no stress digit) ---
    # We follow the Cambridge / learner-dictionary US style used by
    # Reword imports rather than the narrowest IPA: EH → ``e`` (not
    # ``ɛ``), ER → ``ər`` (decomposed, never ``ɝ``/``ɚ``). This is
    # the convention behind the canonical fixtures in rfc/009-ipa.md
    # (e.g. ``leverage`` → ``[ˈlevərɪdʒ]``).
    "AA": "ɑ",   # father
    "AE": "æ",   # cat
    "AH": "ʌ",   # cut  (reduced to ə when AH0)
    "AO": "ɔ",   # caught
    "AW": "aʊ",  # cow
    "AY": "aɪ",  # hide
    "EH": "e",   # red
    "ER": "ər",  # bird (rhotic; stress mark slots before this token)
    "EY": "eɪ",  # say
    "IH": "ɪ",   # big
    "IY": "i",   # bee
    "OW": "oʊ",  # show
    "OY": "ɔɪ",  # toy
    "UH": "ʊ",   # book
    "UW": "u",   # boot
    # --- Consonants ---
    "B": "b",
    "CH": "tʃ",
    "D": "d",
    "DH": "ð",
    "F": "f",
    "G": "ɡ",
    "HH": "h",
    "JH": "dʒ",
    "K": "k",
    "L": "l",
    "M": "m",
    "N": "n",
    "NG": "ŋ",
    "P": "p",
    "R": "ɹ",
    "S": "s",
    "SH": "ʃ",
    "T": "t",
    "TH": "θ",
    "V": "v",
    "W": "w",
    "Y": "j",
    "Z": "z",
    "ZH": "ʒ",
}

# Reductions applied when the ARPAbet vowel carries stress digit ``0``.
# ``ER`` keeps the same ``ər`` rendering in stressed and unstressed
# positions; the stress mark on the syllable is the only differentiator.
_UNSTRESSED_REDUCTIONS: dict[str, str] = {
    "AH": "ə",
}

_VOWEL_SYMBOLS = {
    "AA", "AE", "AH", "AO", "AW", "AY",
    "EH", "ER", "EY",
    "IH", "IY",
    "OW", "OY",
    "UH", "UW",
}

_STRESS_MARK = {"1": "ˈ", "2": "ˌ"}

_BRACKETED_RE = re.compile(r"^\[[^\[\]]+\]$")


# ---------------------------------------------------------------------------
# CMU dict accessor
# ---------------------------------------------------------------------------

_cached_dict: Optional[dict[str, list[list[str]]]] = None


def _get_dict() -> dict[str, list[list[str]]]:
    """Load the CMU dict once per process. Returns a plain ``dict``."""
    global _cached_dict
    if _cached_dict is None:
        if _cmudict is None:  # pragma: no cover - guarded at import time
            raise RuntimeError(
                "cmudict is not installed; add it to project dependencies"
            )
        _cached_dict = _cmudict.dict()
    return _cached_dict


# ---------------------------------------------------------------------------
# ARPAbet → IPA conversion
# ---------------------------------------------------------------------------


def _arpa_to_ipa(phones: list[str]) -> str:
    """Convert one CMU pronunciation (list of ARPAbet phones) to IPA.

    Stress digits attached to vowels are stripped; the corresponding IPA
    stress mark is inserted immediately before the *onset of the
    syllable* that owns the vowel. We approximate "syllable onset" as
    "the first consonant in the run of consonants that precedes this
    vowel, but no earlier than the previous vowel". This matches
    Merriam-Webster / Cambridge conventions for the common case of
    English words.
    """
    # First pass: split into (symbol, stress_digit) tuples for vowels and
    # (symbol, None) for consonants.
    decoded: list[tuple[str, Optional[str]]] = []
    for phone in phones:
        if phone and phone[-1].isdigit() and phone[:-1] in _VOWEL_SYMBOLS:
            decoded.append((phone[:-1], phone[-1]))
        else:
            decoded.append((phone, None))

    # Second pass: render to IPA tokens, recording stress placement.
    ipa_tokens: list[str] = []
    stress_at: dict[int, str] = {}  # token index -> stress mark

    # Find vowel indices in the decoded list for syllable onset lookup.
    vowel_indices = [i for i, (_, s) in enumerate(decoded) if s is not None]

    for idx, (sym, stress) in enumerate(decoded):
        if stress is not None:
            base = sym
            if stress == "0" and base in _UNSTRESSED_REDUCTIONS:
                ipa = _UNSTRESSED_REDUCTIONS[base]
            else:
                ipa = _ARPABET_TO_IPA.get(base)
                if ipa is None:
                    return ""  # unmappable - signal failure
            ipa_tokens.append(ipa)
            if stress in _STRESS_MARK:
                # Walk back to the start of this syllable: include the
                # consonants between the previous vowel (or start) and
                # this vowel.
                pos_in_vowels = vowel_indices.index(idx)
                if pos_in_vowels == 0:
                    onset_idx = 0
                else:
                    onset_idx = vowel_indices[pos_in_vowels - 1] + 1
                stress_at[onset_idx] = _STRESS_MARK[stress]
        else:
            ipa = _ARPABET_TO_IPA.get(sym)
            if ipa is None:
                return ""
            ipa_tokens.append(ipa)

    # Render with stress marks inserted before the syllable onset.
    out_parts: list[str] = []
    for i, tok in enumerate(ipa_tokens):
        if i in stress_at:
            out_parts.append(stress_at[i])
        out_parts.append(tok)
    return "".join(out_parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _normalize(word: str) -> str:
    """Lowercase, trim, and strip the Reword ``to `` prefix."""
    w = word.strip().lower()
    if w.startswith("to "):
        w = w[3:].strip()
    return w


def _lookup_cmu(token: str) -> Optional[str]:
    """Return the IPA body (no brackets) for a single CMU token, or None."""
    d = _get_dict()
    entries = d.get(token)
    if not entries:
        return None
    ipa = _arpa_to_ipa(entries[0])
    return ipa or None


def transcribe(
    word: str,
    *,
    llm: Optional[Callable[[str], str]] = None,
) -> tuple[Optional[str], bool]:
    """Transcribe ``word`` into bracketed US IPA.

    Returns ``(ipa, flagged_for_review)``. ``ipa`` is ``None`` when
    transcription failed entirely; in that case ``flagged_for_review``
    is ``True`` so the caller can record the miss.

    Parameters
    ----------
    word:
        The input string. May carry a leading ``to `` (Reword verb
        marker) and may contain multiple whitespace-separated tokens
        (phrasal verb or idiom).
    llm:
        Optional callable ``(prompt: str) -> str``. Invoked when CMU
        can't resolve every token. The callable must return a string
        whose content is exactly the IPA wrapped in square brackets
        (``[...]``). Anything else triggers ``(None, True)``.
    """
    normalized = _normalize(word)
    if not normalized:
        return (None, True)

    tokens = normalized.split()
    parts: list[str] = []
    cmu_complete = True
    for tok in tokens:
        ipa_body = _lookup_cmu(tok)
        if ipa_body is None:
            cmu_complete = False
            break
        parts.append(ipa_body)

    if cmu_complete:
        return (f"[{' '.join(parts)}]", False)

    # CMU miss — fall back to the LLM if one was supplied.
    if llm is None:
        return (None, True)

    prompt = (
        "Return the US-English IPA transcription of the following word "
        "wrapped in square brackets, with no other text:\n"
        f"{normalized}"
    )
    try:
        raw = llm(prompt)
    except Exception:
        return (None, True)

    if not isinstance(raw, str):
        return (None, True)
    candidate = raw.strip()
    if not _BRACKETED_RE.match(candidate):
        return (None, True)
    return (candidate, True)


__all__ = ["transcribe"]
