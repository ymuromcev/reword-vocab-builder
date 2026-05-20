---
id: RFC-002
bl: BL-02
title: SQLite backup reader + word state classifier
status: approved
date: 2026-05-19
---

## Goal

Pure function that opens a Reword SQLite backup and returns a dict of
classified words keyed by normalized form.

## Public API

```python
from src.backup_reader import read_backup, classify, normalize_key

words: dict[str, ClassifiedWord] = read_backup(path: str)
```

`ClassifiedWord` is a frozen dataclass:

```python
@dataclass(frozen=True)
class ClassifiedWord:
    word: str            # original casing from DB
    status: str          # one of seven values below
    interval_days: float # max(I_REP, I_REC) / 86400
```

`status ∈ {mastered, active-long, active, passive-mastered, passive-long, passive, seen-only}`.

## Classification thresholds

| status            | condition (E_REP/E_REC in seconds → days) |
|-------------------|-------------------------------------------|
| mastered          | S_REP > 0 AND I_REP ≥ 60d                 |
| active-long       | S_REP > 0 AND I_REP ≥ 14d                 |
| active            | S_REP > 0 AND I_REP < 14d                 |
| passive-mastered  | S_REP = 0 AND S_REC > 0 AND I_REC ≥ 60d   |
| passive-long      | S_REP = 0 AND S_REC > 0 AND I_REC ≥ 14d   |
| passive           | S_REP = 0 AND S_REC > 0 AND I_REC < 14d   |
| seen-only         | S_REP = 0 AND S_REC = 0                   |

## Key normalization

`normalize_key(word) = word.strip().lower()`, then strip leading `"to "`
if present. This is used as the dict key so BL-06 dedup can match
`"leverage"` against `"to leverage"`.

## File handling

Use `sqlite3.connect(path)` inside a `with` block (or explicit try/finally).
Open read-only via `file:{path}?mode=ro` URI to avoid accidental writes.

## Tests

- `tests/fixtures/reword_test.db` — synthetic SQLite built programmatically
  in a fixture (not checked in as `.backup`). Contains one row per status.
- Parametrized test: `(s_rec, s_rep, i_rec, i_rep) → expected status`.
- `read_backup` returns ≥1 row per status given the fixture.
- `normalize_key("To Leverage ") == "leverage"`.

## Out of scope

- Drive fetching (BL-03).
- Dedup logic (BL-06).

## Risks / decisions

- **Read-only URI mode** chosen so a buggy code path can never corrupt
  the user's Reword backup.
- **Frozen dataclass over dict** for value type to catch typos early.
