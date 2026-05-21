"""Tests for src/ipa.py — CMU-first US IPA transcription with LLM fallback.

The CMU coverage assertion uses a curated PM/interview vocabulary
fixture (50+ words). Per BL-09 DOD, ≥90% must resolve from CMU without
falling back to the LLM.
"""

from __future__ import annotations

import re

import pytest

from reword_vocab.ipa import transcribe


# ---------------------------------------------------------------------------
# Common PM-domain words. 50+ entries (DOD: 100-word fixture target; we
# ship 60 here and let the test assert ≥90% coverage).
# ---------------------------------------------------------------------------

PM_DOMAIN_WORDS = [
    "leverage", "punt", "needle", "move", "circle", "back",
    "scope", "stakeholder", "roadmap", "metric", "metrics",
    "milestone", "iterate", "iteration", "agile", "scrum",
    "sprint", "backlog", "story", "epic", "user", "research",
    "interview", "survey", "feedback", "ship", "launch", "release",
    "deploy", "feature", "bug", "fix", "issue", "ticket", "blocker",
    "dependency", "tradeoff", "risk", "mitigation", "owner", "team",
    "lead", "manage", "manager", "product", "design", "engineer",
    "engineering", "data", "analytics", "dashboard", "funnel",
    "conversion", "retention", "churn", "growth", "scale", "scaling",
    "review", "decision",
]


def test_normalize_strips_to_prefix():
    """A leading ``to `` must be stripped before lookup."""
    ipa_plain, flagged_plain = transcribe("leverage")
    ipa_to, flagged_to = transcribe("to leverage")
    assert ipa_plain is not None
    assert ipa_plain == ipa_to
    assert flagged_plain is False
    assert flagged_to is False


def test_leverage_primary_stress_marker():
    """Stress digit ``1`` must materialise as the ``ˈ`` marker."""
    ipa, flagged = transcribe("leverage")
    assert ipa == "[ˈlevərɪdʒ]"
    assert flagged is False


def test_returns_bracketed_string():
    """Successful CMU transcription is always wrapped in square brackets."""
    ipa, flagged = transcribe("scope")
    assert ipa is not None
    assert ipa.startswith("[") and ipa.endswith("]")
    assert flagged is False


def test_phrasal_circle_back_joined_with_space():
    ipa, flagged = transcribe("circle back")
    assert ipa is not None
    assert flagged is False
    # One bracket pair; two whitespace-separated IPA bodies inside.
    assert ipa.startswith("[") and ipa.endswith("]")
    inner = ipa[1:-1]
    assert " " in inner, f"expected joined transcription, got {ipa!r}"
    assert len(inner.split(" ")) == 2


def test_idiom_move_the_needle_three_tokens():
    ipa, flagged = transcribe("move the needle")
    assert ipa is not None
    assert flagged is False
    inner = ipa[1:-1]
    parts = inner.split(" ")
    assert len(parts) == 3, f"expected 3 joined transcriptions, got {ipa!r}"


def test_cmu_coverage_on_pm_vocab_at_least_90_percent():
    """≥90% of curated PM vocab must resolve from CMU without flagging."""
    resolved = 0
    for word in PM_DOMAIN_WORDS:
        ipa, flagged = transcribe(word)
        if ipa is not None and flagged is False:
            resolved += 1
    coverage = resolved / len(PM_DOMAIN_WORDS)
    assert coverage >= 0.9, (
        f"CMU coverage {coverage:.0%} below 90% target "
        f"({resolved}/{len(PM_DOMAIN_WORDS)})"
    )


def test_llm_fallback_path_flags_the_word():
    """When CMU misses, the LLM result is returned with ``flagged=True``."""
    calls: list[str] = []

    def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        return "[ˌhaɪpərˈskeɪlər]"

    ipa, flagged = transcribe("hyperscalerzz", llm=fake_llm)
    assert len(calls) == 1, "LLM should be invoked exactly once"
    assert ipa == "[ˌhaɪpərˈskeɪlər]"
    assert flagged is True


def test_llm_garbage_output_yields_none_and_flagged():
    """LLM response that doesn't match ``^\\[[^\\[\\]]+\\]$`` → (None, True)."""

    def garbage_llm(prompt: str) -> str:
        return "sorry I don't know"

    ipa, flagged = transcribe("xyzqq", llm=garbage_llm)
    assert ipa is None
    assert flagged is True


def test_llm_empty_brackets_rejected():
    """Empty brackets are not a valid IPA payload."""

    def empty_llm(prompt: str) -> str:
        return "[]"

    ipa, flagged = transcribe("xyzqq", llm=empty_llm)
    assert ipa is None
    assert flagged is True


def test_llm_nested_brackets_rejected():
    """Square brackets inside the payload are not allowed."""

    def nested_llm(prompt: str) -> str:
        return "[[wat]]"

    ipa, flagged = transcribe("xyzqq", llm=nested_llm)
    assert ipa is None
    assert flagged is True


def test_no_llm_supplied_returns_none_when_cmu_misses():
    """Without an LLM, a CMU miss is a hard miss."""
    ipa, flagged = transcribe("zzzqqxx")
    assert ipa is None
    assert flagged is True


def test_phrasal_falls_back_to_llm_when_any_token_misses():
    """A single missing token in a phrasal forces the LLM path."""

    def fake_llm(prompt: str) -> str:
        return "[wʌt ɛvər]"

    ipa, flagged = transcribe("zzzqqxx whatever", llm=fake_llm)
    assert ipa == "[wʌt ɛvər]"
    assert flagged is True


def test_empty_input_is_a_miss():
    ipa, flagged = transcribe("")
    assert ipa is None
    assert flagged is True


def test_to_prefix_case_insensitive():
    """``To leverage`` (capitalised) should also normalise."""
    ipa, flagged = transcribe("To Leverage")
    assert ipa == "[ˈlevərɪdʒ]"
    assert flagged is False


def test_llm_called_with_normalized_word():
    """The LLM prompt must contain the normalized (no ``to ``) word."""
    captured: dict[str, str] = {}

    def capture_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return "[zzz]"

    transcribe("to zzzqqxx", llm=capture_llm)
    assert "zzzqqxx" in captured["prompt"]
    assert "to zzzqqxx" not in captured["prompt"]


def test_llm_exception_yields_none_and_flagged():
    """If the LLM raises, we return ``(None, True)`` instead of propagating."""

    def boom_llm(prompt: str) -> str:
        raise RuntimeError("boom")

    ipa, flagged = transcribe("zzzqqxx", llm=boom_llm)
    assert ipa is None
    assert flagged is True


@pytest.mark.parametrize(
    "word",
    ["roadmap", "stakeholder", "agile", "metric", "dashboard"],
)
def test_common_words_match_bracket_regex(word):
    """Successful CMU output passes the same regex used for LLM output."""
    ipa, flagged = transcribe(word)
    assert flagged is False
    assert ipa is not None
    assert re.match(r"^\[[^\[\]]+\]$", ipa)
