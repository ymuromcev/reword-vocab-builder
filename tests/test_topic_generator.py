"""Unit tests for src/generators/topic.py.

The LLM is faked — no network, no API key required.
"""

from __future__ import annotations

import json

import pytest

from src.generators.topic import generate


class FakeLLM:
    """Deterministic LLM stub.

    ``responses`` is a list of raw strings; each ``.complete()`` call
    pops the next one. ``calls`` records (system, user) tuples so tests
    can assert on retry behavior.
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if not self._responses:
            return "[]"
        return self._responses.pop(0)


def _payload(items: list[dict]) -> str:
    return json.dumps(items)


def test_generate_returns_parsed_shape():
    items = [
        {"word": "leverage", "part_of_speech": "verb", "context_note": "strategy"},
        {"word": "stakeholder", "part_of_speech": "noun", "context_note": "PM"},
    ]
    llm = FakeLLM([_payload(items)])
    result = generate("PM interview", target_count=2, llm=llm)

    assert result == [
        {"word": "leverage", "part_of_speech": "verb", "context_note": "strategy"},
        {"word": "stakeholder", "part_of_speech": "noun", "context_note": "PM"},
    ]
    assert len(llm.calls) == 1


def test_generate_dedupes_within_batch():
    items = [
        {"word": "leverage", "part_of_speech": "verb", "context_note": "a"},
        {"word": "Leverage", "part_of_speech": "verb", "context_note": "b"},
        {"word": "stakeholder", "part_of_speech": "noun", "context_note": "c"},
        {"word": "leverage", "part_of_speech": "verb", "context_note": "d"},
    ]
    llm = FakeLLM([_payload(items)])
    result = generate("PM interview", target_count=10, llm=llm)

    words = [item["word"].lower() for item in result]
    assert words == ["leverage", "stakeholder"]


def test_generate_sanitizes_invalid_items():
    items = [
        {"word": "leverage", "part_of_speech": "verb", "context_note": ""},
        {"word": "", "part_of_speech": "verb", "context_note": "empty"},
        {"word": "  ", "part_of_speech": "noun", "context_note": "whitespace"},
        {"word": "$100", "part_of_speech": "noun", "context_note": "money"},
        {"word": "10x", "part_of_speech": "adjective", "context_note": "growth"},
        {"word": "100", "part_of_speech": "noun", "context_note": "digits"},
        {"word": "growth", "part_of_speech": "noun", "context_note": "ok"},
        {"word": "split/merge", "part_of_speech": "verb", "context_note": "slash"},
        {"word": "uplift", "part_of_speech": "bogus-pos", "context_note": "bad pos"},
        {"word": "scope", "part_of_speech": "noun"},  # missing note allowed
    ]
    llm = FakeLLM([_payload(items)])
    result = generate("PM interview", target_count=50, llm=llm)

    words = [item["word"] for item in result]
    assert words == ["leverage", "growth", "scope"]
    # Missing context_note defaults to empty string.
    scope = [item for item in result if item["word"] == "scope"][0]
    assert scope["context_note"] == ""


def test_generate_empty_topic_raises():
    llm = FakeLLM(["[]"])
    with pytest.raises(ValueError):
        generate("", llm=llm)
    with pytest.raises(ValueError):
        generate("   ", llm=llm)


def test_generate_triggers_extension_call_when_under_target():
    first_batch = [
        {"word": "leverage", "part_of_speech": "verb", "context_note": "a"},
        {"word": "stakeholder", "part_of_speech": "noun", "context_note": "b"},
    ]
    second_batch = [
        {"word": "uplift", "part_of_speech": "noun", "context_note": "c"},
        {"word": "scope", "part_of_speech": "noun", "context_note": "d"},
        {"word": "leverage", "part_of_speech": "verb", "context_note": "dup"},
    ]
    llm = FakeLLM([_payload(first_batch), _payload(second_batch)])

    result = generate("PM interview", target_count=4, llm=llm)

    assert len(llm.calls) == 2
    words = [item["word"].lower() for item in result]
    assert words == ["leverage", "stakeholder", "uplift", "scope"]
    # Extension prompt should reference seen words.
    _, extend_user = llm.calls[1]
    assert "leverage" in extend_user.lower()
    assert "stakeholder" in extend_user.lower()


def test_generate_does_not_retry_when_target_met():
    # ASCII letters only — digits would be filtered by sanitation.
    fillers = [
        "alpha", "beta", "gamma", "delta", "epsilon",
        "zeta", "eta", "theta", "iota", "kappa",
    ]
    items = [
        {"word": w, "part_of_speech": "noun", "context_note": ""}
        for w in fillers
    ]
    llm = FakeLLM([_payload(items), _payload([])])
    result = generate("topic", target_count=5, llm=llm)

    assert len(llm.calls) == 1
    assert len(result) == 5


def test_generate_tolerates_markdown_fenced_json():
    items = [
        {"word": "leverage", "part_of_speech": "verb", "context_note": "x"},
    ]
    fenced = f"Here you go:\n```json\n{_payload(items)}\n```\n"
    llm = FakeLLM([fenced])
    result = generate("PM interview", target_count=1, llm=llm)
    assert result[0]["word"] == "leverage"


def test_generate_handles_malformed_json_gracefully():
    llm = FakeLLM(["not json at all", "[]"])
    result = generate("PM interview", target_count=5, llm=llm)
    # Both calls return empty after parsing -> result is empty list.
    assert result == []
    # Second call still happens because we were under target.
    assert len(llm.calls) == 2
