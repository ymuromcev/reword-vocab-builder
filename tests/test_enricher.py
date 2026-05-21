"""Tests for src/enricher.py (BL-10 / RFC-010).

The LLM is injected as a fake that captures inputs and returns canned
responses.  No network, no API keys.
"""

from __future__ import annotations

import json

import pytest

from reword_vocab.enricher import (
    EnrichmentError,
    REQUIRED_FIELDS,
    enrich,
    enrich_many,
)


# ---------------------------------------------------------------------------
# Fake LLM helpers
# ---------------------------------------------------------------------------


class FakeLLM:
    """Records every (system, user) call and returns scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self._responses.pop(0)


def _single_response(
    ru="разрабатывать",
    ex1_en="We need to design a simple onboarding.",
    ex1_ru="Нам нужно спроектировать простой онбординг.",
    ex2_en="Let us design the new feature together this afternoon.",
    ex2_ru="Давайте спроектируем новую функцию вместе сегодня днём.",
):
    return json.dumps(
        {
            "ru": ru,
            "ex1_en": ex1_en,
            "ex1_ru": ex1_ru,
            "ex2_en": ex2_en,
            "ex2_ru": ex2_ru,
        },
        ensure_ascii=False,
    )


def _batch_response(words, ex1_overrides=None):
    """Build a JSON batch response covering ``words``.

    ``ex1_overrides`` maps a word to a custom ex1_en (used to inject
    forbidden symbols in retry tests).
    """
    ex1_overrides = ex1_overrides or {}
    payload = {}
    for w in words:
        payload[w] = {
            "ru": "слово",
            "ex1_en": ex1_overrides.get(w, "We can use this word naturally."),
            "ex1_ru": "Мы можем использовать это слово естественно.",
            "ex2_en": "Let us see how the team uses this in real meetings.",
            "ex2_ru": "Посмотрим, как команда использует это на реальных встречах.",
        }
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# enrich() — single word
# ---------------------------------------------------------------------------


def test_enrich_populates_all_fields():
    llm = FakeLLM([_single_response()])
    out = enrich({"word": "to design"}, llm=llm)

    for field in REQUIRED_FIELDS:
        assert out[field], f"missing field {field}"
    assert out["word"] == "to design"
    assert len(llm.calls) == 1


def test_enrich_preserves_extra_input_keys():
    llm = FakeLLM([_single_response()])
    out = enrich(
        {
            "word": "to design",
            "part_of_speech": "verb",
            "context_note": "common in PM",
        },
        llm=llm,
    )

    assert out["part_of_speech"] == "verb"
    assert out["context_note"] == "common in PM"
    # Required fields are still populated.
    assert out["ru"]
    assert out["ex1_en"]


def test_enrich_source_quote_in_user_message():
    llm = FakeLLM([_single_response()])
    quote = "We had to redesign the onboarding from scratch."
    enrich({"word": "to redesign", "source_quote": quote}, llm=llm)

    assert len(llm.calls) == 1
    _system, user = llm.calls[0]
    assert quote in user
    assert "ex2_en" in user  # prompt mentions target field


def test_enrich_retries_on_forbidden_symbol_then_succeeds():
    bad = _single_response(ex1_en="Save 50% on the launch this week.")
    good = _single_response()
    llm = FakeLLM([bad, good])

    out = enrich({"word": "to launch"}, llm=llm)

    assert len(llm.calls) == 2
    assert "%" not in out["ex1_en"]
    # The retry user message should mention the offending symbol.
    _system, second_user = llm.calls[1]
    assert "%" in second_user


def test_enrich_two_strikes_raises():
    bad1 = _single_response(ex1_en="Cost is $200 for this round.")
    bad2 = _single_response(ex2_en="Then divide by 2 / 3 of the team.")
    llm = FakeLLM([bad1, bad2])

    with pytest.raises(EnrichmentError):
        enrich({"word": "to estimate"}, llm=llm)

    assert len(llm.calls) == 2


def test_enrich_rejects_empty_word():
    llm = FakeLLM([])
    with pytest.raises(EnrichmentError):
        enrich({"word": ""}, llm=llm)


# ---------------------------------------------------------------------------
# enrich_many() — batching
# ---------------------------------------------------------------------------


def test_enrich_many_batches_by_twenty():
    words = [{"word": f"word_{i}"} for i in range(25)]
    first_batch = [w["word"] for w in words[:20]]
    second_batch = [w["word"] for w in words[20:]]

    llm = FakeLLM(
        [
            _batch_response(first_batch),
            _batch_response(second_batch),
        ]
    )

    out = enrich_many(words, llm=llm)

    assert len(out) == 25
    assert len(llm.calls) == 2  # 20 + 5, one call per batch
    for item in out:
        for field in REQUIRED_FIELDS:
            assert item[field], f"missing {field} in {item}"


def test_enrich_many_preserves_input_keys():
    words = [
        {"word": "to design", "part_of_speech": "verb"},
        {"word": "to launch", "context_note": "PM staple"},
    ]
    llm = FakeLLM([_batch_response(["to design", "to launch"])])

    out = enrich_many(words, llm=llm)

    assert out[0]["part_of_speech"] == "verb"
    assert out[1]["context_note"] == "PM staple"


def test_enrich_many_retries_batch_on_forbidden_symbol():
    words = [{"word": "to ship"}, {"word": "to land"}]
    bad = _batch_response(
        ["to ship", "to land"],
        ex1_overrides={"to ship": "We will ship in 2 weeks for $1000."},
    )
    good = _batch_response(["to ship", "to land"])
    llm = FakeLLM([bad, good])

    out = enrich_many(words, llm=llm)

    assert len(llm.calls) == 2
    assert "$" not in out[0]["ex1_en"]


def test_enrich_many_empty_input_no_calls():
    llm = FakeLLM([])
    assert enrich_many([], llm=llm) == []
    assert llm.calls == []
