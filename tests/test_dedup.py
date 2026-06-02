"""Tests for src/dedup.py (RFC-006 routing logic)."""

from __future__ import annotations

import pytest

from reword_vocab.backup_reader import ClassifiedWord
from reword_vocab.dedup import DedupReport, dedup, dedup_only


def _cw(word: str, status: str, interval_days: float = 0.0) -> ClassifiedWord:
    return ClassifiedWord(word=word, status=status, interval_days=interval_days)


@pytest.fixture
def backup_index() -> dict[str, ClassifiedWord]:
    """Synthetic index covering all 7 SRS statuses."""
    return {
        "leverage": _cw("to leverage", "mastered", 90),
        "ramp up": _cw("to ramp up", "active-long", 20),
        "endeavor": _cw("endeavor", "active", 5),
        "scrutinize": _cw("to scrutinize", "passive-mastered", 75),
        "obfuscate": _cw("to obfuscate", "passive-long", 20),
        "elucidate": _cw("to elucidate", "passive", 3),
        "wistful": _cw("wistful", "seen-only", 0),
    }


def _by_word(decisions, word):
    return [(d, r) for w, d, r in decisions if w == word]


def test_new_word_is_kept(backup_index):
    words = [{"word": "to deliberate"}]
    kept, report = dedup(words, backup_index)
    assert kept == [{"word": "to deliberate"}]
    assert report.kept == 1
    assert report.skipped == 0
    assert report.reasons == {"new": 1}


def test_mastered_is_skipped(backup_index):
    kept, report = dedup([{"word": "to leverage"}], backup_index)
    assert kept == []
    assert report.skipped == 1
    assert report.reasons == {"mastered": 1}


def test_active_long_is_skipped(backup_index):
    kept, report = dedup([{"word": "to ramp up"}], backup_index)
    assert kept == []
    assert report.reasons == {"active-long": 1}


@pytest.mark.parametrize(
    "word, status",
    [
        ("endeavor", "active"),
        ("to scrutinize", "passive-mastered"),
        ("to obfuscate", "passive-long"),
        ("to elucidate", "passive"),
        ("wistful", "seen-only"),
    ],
)
def test_weak_statuses_are_skipped(backup_index, word, status):
    # BL-18: any word already in the backup is a duplicate, even weak ones.
    kept, report = dedup([{"word": word}], backup_index)
    assert kept == []
    assert report.kept == 0
    assert report.skipped == 1
    assert report.reasons == {status: 1}


def test_normalize_input_has_to_backup_does_not(backup_index):
    # BL-18: "to endeavor" matches "endeavor" (active) in backup -> dup.
    kept, report = dedup([{"word": "to endeavor"}], backup_index)
    assert kept == []
    assert report.reasons == {"active": 1}


def test_normalize_input_no_to_backup_has_to(backup_index):
    kept, report = dedup([{"word": "leverage"}], backup_index)
    assert kept == []
    assert report.reasons == {"mastered": 1}


def test_case_and_whitespace_normalized(backup_index):
    kept, report = dedup([{"word": "  LEVERAGE  "}], backup_index)
    assert kept == []
    assert report.reasons == {"mastered": 1}


def test_in_list_duplicate_keeps_first(backup_index):
    words = [
        {"word": "to deliberate", "n": 1},
        {"word": "to deliberate", "n": 2},
        {"word": "deliberate", "n": 3},
    ]
    kept, report = dedup(words, backup_index)
    assert kept == [{"word": "to deliberate", "n": 1}]
    assert report.kept == 1
    assert report.skipped == 2
    assert report.reasons == {"new": 1, "in-list-duplicate": 2}


def test_empty_and_whitespace_words(backup_index):
    words = [{"word": ""}, {"word": "   "}, {"word": "\t\n"}]
    kept, report = dedup(words, backup_index)
    assert kept == []
    assert report.skipped == 3
    assert report.reasons == {"empty-word": 3}


def test_missing_word_key_treated_as_empty(backup_index):
    kept, report = dedup([{"other": "x"}], backup_index)
    assert kept == []
    assert report.reasons == {"empty-word": 1}


def test_reasons_counts_match_decisions(backup_index):
    words = [
        {"word": "to leverage"},
        {"word": "new1"},
        {"word": "new2"},
        {"word": "endeavor"},
        {"word": "to ramp up"},
        {"word": "wistful"},
        {"word": ""},
        {"word": "new1"},
    ]
    _, report = dedup(words, backup_index)
    decision_counts: dict[str, int] = {}
    for _w, _d, reason in report.decisions:
        decision_counts[reason] = decision_counts.get(reason, 0) + 1
    assert decision_counts == report.reasons
    assert report.kept + report.skipped == len(report.decisions)
    assert len(report.decisions) == len(words)


def test_dedup_only_matches_dedup(backup_index):
    words = [
        {"word": "to leverage"},
        {"word": "novel"},
        {"word": "endeavor"},
    ]
    kept_pair, _ = dedup(words, backup_index)
    assert dedup_only(words, backup_index) == kept_pair


def test_all_seven_statuses_route_correctly(backup_index):
    words = [
        {"word": "leverage"},
        {"word": "ramp up"},
        {"word": "endeavor"},
        {"word": "scrutinize"},
        {"word": "obfuscate"},
        {"word": "elucidate"},
        {"word": "wistful"},
    ]
    kept, report = dedup(words, backup_index)
    kept_words = [k["word"] for k in kept]
    # BL-18: every word is in the backup, so all 7 are skipped as dups.
    assert kept_words == []
    assert report.kept == 0
    assert report.skipped == 7
    assert report.reasons == {
        "mastered": 1,
        "active-long": 1,
        "active": 1,
        "passive-mastered": 1,
        "passive-long": 1,
        "passive": 1,
        "seen-only": 1,
    }


def test_report_str_has_header_and_lines(backup_index):
    words = [
        {"word": "new1"},
        {"word": "new2"},
        {"word": "to leverage"},
    ]
    _, report = dedup(words, backup_index)
    text = str(report)
    assert text.startswith("Dedup: 2 kept / 1 skipped")
    assert "new:" in text
    assert "mastered:" in text


def test_report_str_skip_only(backup_index):
    _, report = dedup([{"word": "to leverage"}], backup_index)
    text = str(report)
    assert "Dedup: 0 kept / 1 skipped" in text
    assert "mastered:" in text


def test_report_is_frozen():
    report = DedupReport(kept=0, skipped=0, reasons={}, decisions=[])
    with pytest.raises(Exception):
        report.kept = 1  # type: ignore[misc]
