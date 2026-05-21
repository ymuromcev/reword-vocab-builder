"""Tests for reword_vocab.backup_reader (BL-02 / RFC-002).

Synthetic SQLite DB is built programmatically in a fixture — no real
Reword backup is ever committed or required.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from reword_vocab.backup_reader import (
    SECONDS_PER_DAY,
    ClassifiedWord,
    classify,
    normalize_key,
    read_backup,
)


# ---------------------------------------------------------------------------
# Fixture: build a synthetic Reword-style backup
# ---------------------------------------------------------------------------

DAY = SECONDS_PER_DAY

# One row per classification status. (word, s_rec, s_rep, i_rec, i_rep)
SYNTHETIC_ROWS = [
    # mastered: S_REP > 0, I_REP >= 60d
    ("dominate", 5, 5, 90 * DAY, 90 * DAY),
    # active-long: S_REP > 0, 14d <= I_REP < 60d
    ("orchestrate", 4, 4, 30 * DAY, 30 * DAY),
    # active: S_REP > 0, I_REP < 14d
    ("ponder", 2, 2, 5 * DAY, 5 * DAY),
    # passive-mastered: S_REP = 0, S_REC > 0, I_REC >= 60d
    ("juxtapose", 5, 0, 90 * DAY, 0),
    # passive-long: S_REP = 0, S_REC > 0, 14d <= I_REC < 60d
    ("ostensible", 4, 0, 30 * DAY, 0),
    # passive: S_REP = 0, S_REC > 0, I_REC < 14d
    ("malleable", 2, 0, 5 * DAY, 0),
    # seen-only: S_REP = 0, S_REC = 0
    ("nascent", 0, 0, 0, 0),
]


@pytest.fixture()
def synthetic_db(tmp_path: Path) -> Path:
    """Build a synthetic Reword-style SQLite at tmp_path/reword_test.db."""
    db_path = tmp_path / "reword_test.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE WORD (
                WORD TEXT PRIMARY KEY,
                S_REC INTEGER,
                S_REP INTEGER,
                I_REC REAL,
                I_REP REAL,
                E_REC REAL,
                E_REP REAL
            )
            """
        )
        conn.executemany(
            "INSERT INTO WORD (WORD, S_REC, S_REP, I_REC, I_REP, E_REC, E_REP) "
            "VALUES (?, ?, ?, ?, ?, 0, 0)",
            SYNTHETIC_ROWS,
        )
        conn.commit()
    return db_path


# ---------------------------------------------------------------------------
# classify() — parametrized truth table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "s_rec, s_rep, i_rec, i_rep, expected",
    [
        # mastered
        (5, 5, 90 * DAY, 60 * DAY, "mastered"),
        (5, 5, 0, 60 * DAY, "mastered"),  # exactly at threshold
        # active-long
        (5, 5, 0, 14 * DAY, "active-long"),
        (5, 5, 0, 59 * DAY, "active-long"),
        # active
        (5, 5, 0, 0, "active"),
        (5, 5, 0, 13 * DAY, "active"),
        # passive-mastered
        (5, 0, 60 * DAY, 0, "passive-mastered"),
        (5, 0, 90 * DAY, 0, "passive-mastered"),
        # passive-long
        (5, 0, 14 * DAY, 0, "passive-long"),
        (5, 0, 59 * DAY, 0, "passive-long"),
        # passive
        (5, 0, 0, 0, "passive"),
        (5, 0, 13 * DAY, 0, "passive"),
        # seen-only
        (0, 0, 0, 0, "seen-only"),
        # active dominates passive even if both counters > 0
        (5, 1, 90 * DAY, 0, "active"),
    ],
)
def test_classify(s_rec, s_rep, i_rec, i_rep, expected):
    assert classify(s_rec, s_rep, i_rec, i_rep) == expected


# ---------------------------------------------------------------------------
# normalize_key()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("To Leverage ", "leverage"),
        ("  Leverage  ", "leverage"),
        ("to leverage", "leverage"),
        ("leverage", "leverage"),
        ("TO LEVERAGE", "leverage"),
        ("tomato", "tomato"),  # not a "to " prefix
        ("to  spaced", "spaced"),  # double space after `to ` collapses
        ("", ""),
    ],
)
def test_normalize_key(raw, expected):
    assert normalize_key(raw) == expected


# ---------------------------------------------------------------------------
# read_backup() — end-to-end against synthetic DB
# ---------------------------------------------------------------------------


def test_read_backup_returns_all_seven_statuses(synthetic_db):
    result = read_backup(str(synthetic_db))
    statuses = {entry.status for entry in result.values()}
    expected = {
        "mastered",
        "active-long",
        "active",
        "passive-mastered",
        "passive-long",
        "passive",
        "seen-only",
    }
    assert statuses == expected


def test_read_backup_keys_are_normalized(synthetic_db):
    result = read_backup(str(synthetic_db))
    # All keys should be lowercase + stripped (none of our rows have "to ")
    for key in result:
        assert key == key.strip().lower()
    assert "dominate" in result


def test_read_backup_entry_shape(synthetic_db):
    result = read_backup(str(synthetic_db))
    mastered = result["dominate"]
    assert isinstance(mastered, ClassifiedWord)
    assert mastered.word == "dominate"
    assert mastered.status == "mastered"
    assert mastered.interval_days == pytest.approx(90.0)


def test_read_backup_is_readonly(tmp_path, synthetic_db):
    """Reading must not mutate the file (mtime stable after read)."""
    mtime_before = synthetic_db.stat().st_mtime_ns
    read_backup(str(synthetic_db))
    mtime_after = synthetic_db.stat().st_mtime_ns
    assert mtime_before == mtime_after


def test_read_backup_readonly_rejects_writes(synthetic_db):
    """Internal sanity: the URI-mode connection cannot insert rows."""
    from reword_vocab.backup_reader import _connect_readonly

    with _connect_readonly(str(synthetic_db)) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO WORD (WORD, S_REC, S_REP, I_REC, I_REP, "
                "E_REC, E_REP) VALUES ('x', 0, 0, 0, 0, 0, 0)"
            )


def test_read_backup_dedup_keeps_max_interval(tmp_path):
    """If two rows normalize to the same key, the longer interval wins."""
    db_path = tmp_path / "dup.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE WORD (WORD TEXT PRIMARY KEY, S_REC INTEGER, "
            "S_REP INTEGER, I_REC REAL, I_REP REAL, E_REC REAL, E_REP REAL)"
        )
        conn.executemany(
            "INSERT INTO WORD VALUES (?, ?, ?, ?, ?, 0, 0)",
            [
                ("leverage", 5, 5, 0, 90 * DAY),  # mastered, 90d
                ("to leverage", 1, 1, 0, 1 * DAY),  # active, 1d
            ],
        )
        conn.commit()
    result = read_backup(str(db_path))
    assert "leverage" in result
    assert result["leverage"].status == "mastered"
    assert result["leverage"].interval_days == pytest.approx(90.0)
