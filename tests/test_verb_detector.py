"""Tests for ``reword_vocab.verb_detector`` — hermetic, no real spaCy model needed."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pytest

from reword_vocab import verb_detector
from reword_vocab.verb_detector import is_verb, set_nlp, to_prefix


# ---------------------------------------------------------------------------
# Fake POS tagger
# ---------------------------------------------------------------------------


# Each entry: token text (lower-case) -> POS tag the fake tagger emits.
# Anything not listed defaults to "NN" (treated as a noun, so not a verb).
TAGS: dict[str, str] = {
    # base-form verbs ---------------------------------------------------
    "leverage": "VB",
    "align": "VB",
    "iterate": "VB",
    "deliver": "VB",
    "ship": "VB",
    "estimate": "VB",
    "prioritize": "VB",
    "scale": "VB",
    "build": "VB",
    "test": "VB",
    "validate": "VB",
    "circle": "VB",
    "push": "VB",
    "dive": "VB",
    "roll": "VB",
    "move": "VB",
    "bake": "VB",
    "raise": "VB",
    "drive": "VB",
    "frame": "VB",
    "unblock": "VB",
    "ship": "VB",
    "negotiate": "VB",
    "facilitate": "VB",
    "synthesize": "VB",
    "deprecate": "VB",
    "refactor": "VB",
    "decouple": "VB",
    "consolidate": "VB",
    "broker": "VB",
    "champion": "VB",
    "anchor": "VB",
    "translate": "VB",
    "operationalize": "VB",
    "communicate": "VB",
    "execute": "VB",
    "draft": "VB",
    # gerunds / past / participle (not VB) -----------------------------
    "running": "VBG",
    "building": "VBG",
    "shipped": "VBD",
    "delivered": "VBN",
    "iterated": "VBD",
    # nouns / others ---------------------------------------------------
    "data": "NN",
    "metric": "NN",
    "stakeholder": "NN",
    "roadmap": "NN",
    "tradeoff": "NN",
    "trade-off": "NN",
    "user": "NN",
    "north": "NN",
    "star": "NN",
    "okr": "NN",
    "kpi": "NN",
    "feature": "NN",
    "bug": "NN",
    "team": "NN",
    "epic": "NN",
    "ticket": "NN",
    "sprint": "NN",
    "retro": "NN",
    "standup": "NN",
    "demo": "NN",
    "spec": "NN",
    "brief": "NN",
    "headcount": "NN",
    "burndown": "NN",
    "velocity": "NN",
    "throughput": "NN",
    "latency": "NN",
    "p0": "NN",
    "p1": "NN",
    "release": "NN",
    "launch": "NN",
    "rollout": "NN",
    # particles --------------------------------------------------------
    "back": "RP",
    "in": "IN",
    "out": "RP",
    "up": "RP",
    "down": "RP",
    "into": "IN",
    "over": "IN",
    "through": "IN",
    "off": "RP",
    "on": "IN",
    # idiom helpers ----------------------------------------------------
    "the": "DT",
    "bar": "NN",
    "needle": "NN",
    "ball": "NN",
    "ground": "NN",
}

class _FakeToken:
    def __init__(self, text: str, tag_: str) -> None:
        self.text = text
        self.tag_ = tag_


class _FakeDoc:
    def __init__(self, tokens: list[_FakeToken]) -> None:
        self._tokens = tokens

    def __iter__(self) -> Iterable[_FakeToken]:
        return iter(self._tokens)

    def __len__(self) -> int:
        return len(self._tokens)

    def __getitem__(self, index: int) -> _FakeToken:
        return self._tokens[index]


def _fake_nlp(text: str) -> _FakeDoc:
    out: list[_FakeToken] = []
    for raw in text.split():
        tag = TAGS.get(raw.lower(), "NN")
        out.append(_FakeToken(text=raw, tag_=tag))
    return _FakeDoc(out)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _wire_fake_nlp():
    set_nlp(_fake_nlp)
    # Reset overrides to the default empty config file in the repo.
    verb_detector.reload_overrides()
    yield
    set_nlp(None)


# ---------------------------------------------------------------------------
# Single-word verbs (30+)
# ---------------------------------------------------------------------------


VERBS_SINGLE = [
    "leverage",
    "align",
    "iterate",
    "deliver",
    "ship",
    "estimate",
    "prioritize",
    "scale",
    "build",
    "test",
    "validate",
    "circle",
    "push",
    "dive",
    "roll",
    "move",
    "bake",
    "raise",
    "drive",
    "frame",
    "unblock",
    "negotiate",
    "facilitate",
    "synthesize",
    "deprecate",
    "refactor",
    "decouple",
    "consolidate",
    "broker",
    "champion",
    "anchor",
    "translate",
    "operationalize",
    "communicate",
    "execute",
    "draft",
]


@pytest.mark.parametrize("word", VERBS_SINGLE)
def test_single_word_verbs_detected(word: str) -> None:
    assert is_verb(word) is True


# ---------------------------------------------------------------------------
# Non-verbs (30+)
# ---------------------------------------------------------------------------


NOT_VERBS = [
    "data",
    "metric",
    "stakeholder",
    "roadmap",
    "tradeoff",
    "trade-off",
    "user",
    "okr",
    "kpi",
    "feature",
    "bug",
    "team",
    "epic",
    "ticket",
    "sprint",
    "retro",
    "standup",
    "demo",
    "spec",
    "brief",
    "headcount",
    "burndown",
    "velocity",
    "throughput",
    "latency",
    "p0",
    "p1",
    "release",
    "launch",
    "rollout",
    "running",   # gerund — must be rejected
    "building",  # gerund — must be rejected
    "shipped",   # past tense — must be rejected
    "delivered", # past participle — must be rejected
    "iterated",  # past tense — must be rejected
]


@pytest.mark.parametrize("word", NOT_VERBS)
def test_non_verbs_rejected(word: str) -> None:
    assert is_verb(word) is False


# ---------------------------------------------------------------------------
# Phrasal verbs
# ---------------------------------------------------------------------------


PHRASALS = [
    "circle back",
    "push back",
    "dive in",
    "roll out",
    "ship out",
    "scale up",
    "scale down",
    "deliver on",
    "iterate over",
    "drive through",
]


@pytest.mark.parametrize("phrase", PHRASALS)
def test_phrasal_verbs(phrase: str) -> None:
    assert is_verb(phrase) is True


def test_two_word_idiom_with_noun_tail() -> None:
    # Two words, head VB, tail NN — phrasal rule does NOT fire (no particle),
    # but the idiom rule does (first token is VB). Documents that the
    # idiom fallback covers VB + noun two-word phrases by design.
    assert is_verb("ship feature") is True


# ---------------------------------------------------------------------------
# Idioms
# ---------------------------------------------------------------------------


IDIOMS = [
    "raise the bar",
    "move the needle",
    "drive the bus",
    "bake in",
    "ship the feature",
]


@pytest.mark.parametrize("phrase", IDIOMS)
def test_idioms(phrase: str) -> None:
    assert is_verb(phrase) is True


def test_idiom_rejected_when_head_not_verb() -> None:
    # "data drives decisions" — head "data" is NN.
    assert is_verb("data drives decisions") is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_string() -> None:
    assert is_verb("") is False
    assert to_prefix("") == ""


def test_whitespace_only() -> None:
    assert is_verb("   ") is False


def test_gerund_rejected() -> None:
    assert is_verb("running") is False
    assert to_prefix("running") == "running"


# ---------------------------------------------------------------------------
# to_prefix behaviour & idempotency
# ---------------------------------------------------------------------------


def test_to_prefix_adds_to_for_verb() -> None:
    assert to_prefix("leverage") == "to leverage"


def test_to_prefix_skips_non_verb() -> None:
    assert to_prefix("trade-off") == "trade-off"


def test_to_prefix_idempotent_on_verbs() -> None:
    once = to_prefix("leverage")
    twice = to_prefix(once)
    assert once == twice == "to leverage"


def test_to_prefix_idempotent_on_non_verbs() -> None:
    once = to_prefix("data")
    twice = to_prefix(once)
    assert once == twice == "data"


def test_to_prefix_passthrough_already_prefixed() -> None:
    assert to_prefix("to align") == "to align"


def test_to_prefix_phrasal_idempotent() -> None:
    once = to_prefix("circle back")
    twice = to_prefix(once)
    assert once == "to circle back"
    assert once == twice


# ---------------------------------------------------------------------------
# Override file precedence
# ---------------------------------------------------------------------------


def test_override_not_verbs_wins_over_spacy(tmp_path: Path) -> None:
    cfg = tmp_path / "verb_overrides.yaml"
    cfg.write_text("verbs: []\nnot_verbs:\n  - leverage\n", encoding="utf-8")
    verb_detector.reload_overrides(cfg)
    try:
        assert is_verb("leverage") is False
        assert to_prefix("leverage") == "leverage"
    finally:
        verb_detector.reload_overrides()


def test_override_verbs_wins_over_spacy(tmp_path: Path) -> None:
    cfg = tmp_path / "verb_overrides.yaml"
    cfg.write_text("verbs:\n  - data\nnot_verbs: []\n", encoding="utf-8")
    verb_detector.reload_overrides(cfg)
    try:
        assert is_verb("data") is True
        assert to_prefix("data") == "to data"
    finally:
        verb_detector.reload_overrides()


def test_override_not_verbs_wins_when_in_both(tmp_path: Path) -> None:
    cfg = tmp_path / "verb_overrides.yaml"
    cfg.write_text(
        "verbs:\n  - data\nnot_verbs:\n  - data\n", encoding="utf-8"
    )
    verb_detector.reload_overrides(cfg)
    try:
        assert is_verb("data") is False
    finally:
        verb_detector.reload_overrides()


def test_override_missing_file_is_silent(tmp_path: Path) -> None:
    cfg = tmp_path / "does_not_exist.yaml"
    verb_detector.reload_overrides(cfg)
    try:
        # falls back to the live pipeline
        assert is_verb("leverage") is True
    finally:
        verb_detector.reload_overrides()
