"""Read Reword SQLite backup, classify word states.

Implements RFC-002 / BL-02:

- `read_backup(path)` opens the Reword `*.backup` (SQLite) file in
  read-only URI mode and returns `dict[str, ClassifiedWord]` keyed by
  the normalized form (lowercase, stripped, no leading "to ").
- `classify(...)` is a pure function over the four counters/intervals
  used by Reword's SRS engine.
- `normalize_key(word)` produces the dedup key shared with BL-06.

The intervals stored in the DB (`I_REC`, `I_REP`) are in **seconds**;
classification thresholds are in **days** (14 / 60).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from urllib.parse import quote

SECONDS_PER_DAY = 86_400
LONG_THRESHOLD_DAYS = 14
MASTERED_THRESHOLD_DAYS = 60


@dataclass(frozen=True)
class ClassifiedWord:
    """One word + its classified SRS state."""

    word: str
    status: str
    interval_days: float


def normalize_key(word: str) -> str:
    """Lowercase, strip whitespace, drop a leading 'to ' if present.

    Used as the dict key so BL-06 dedup can match `"leverage"` against
    `"to leverage"`.
    """
    key = word.strip().lower()
    if key.startswith("to "):
        key = key[3:].lstrip()
    return key


def classify(s_rec: int, s_rep: int, i_rec: float, i_rep: float) -> str:
    """Classify a word into one of seven SRS states.

    Args:
        s_rec: number of recognition successes.
        s_rep: number of reproduction (active) successes.
        i_rec: recognition interval in seconds.
        i_rep: reproduction interval in seconds.

    Returns one of: mastered, active-long, active, passive-mastered,
    passive-long, passive, seen-only.
    """
    i_rec_days = i_rec / SECONDS_PER_DAY
    i_rep_days = i_rep / SECONDS_PER_DAY

    if s_rep > 0:
        if i_rep_days >= MASTERED_THRESHOLD_DAYS:
            return "mastered"
        if i_rep_days >= LONG_THRESHOLD_DAYS:
            return "active-long"
        return "active"

    if s_rec > 0:
        if i_rec_days >= MASTERED_THRESHOLD_DAYS:
            return "passive-mastered"
        if i_rec_days >= LONG_THRESHOLD_DAYS:
            return "passive-long"
        return "passive"

    return "seen-only"


def _connect_readonly(path: str) -> sqlite3.Connection:
    """Open the SQLite file via a read-only URI so we can't corrupt it."""
    # `quote` keeps the URI valid for paths with spaces / unicode.
    uri = f"file:{quote(path)}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def read_backup(path: str) -> dict[str, ClassifiedWord]:
    """Read the Reword backup and return classified words.

    Returns a dict keyed by `normalize_key(WORD)`. If duplicate
    normalized keys exist, the row with the higher `interval_days`
    wins (more progress beats less).
    """
    out: dict[str, ClassifiedWord] = {}
    with _connect_readonly(path) as conn:
        cursor = conn.execute(
            "SELECT WORD, S_REC, S_REP, I_REC, I_REP FROM WORD"
        )
        for word, s_rec, s_rep, i_rec, i_rep in cursor:
            s_rec = int(s_rec or 0)
            s_rep = int(s_rep or 0)
            i_rec = float(i_rec or 0)
            i_rep = float(i_rep or 0)
            status = classify(s_rec, s_rep, i_rec, i_rep)
            interval_days = max(i_rep, i_rec) / SECONDS_PER_DAY
            entry = ClassifiedWord(
                word=word,
                status=status,
                interval_days=interval_days,
            )
            key = normalize_key(word)
            prev = out.get(key)
            if prev is None or entry.interval_days > prev.interval_days:
                out[key] = entry
    return out
