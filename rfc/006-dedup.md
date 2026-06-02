---
id: RFC-006
bl: BL-06
title: Dedup pass against Reword backup using SRS state
status: approved
date: 2026-05-20
amended: 2026-06-01
amended_by: BL-18
---

## Amendment — BL-18 (2026-06-01): strict dedup is the default

The original rule kept "weak" statuses (`passive`, `passive-long`,
`passive-mastered`, `seen-only`, `active`) on the theory that those
words were still worth practicing actively. In practice this leaked
duplicates: Reword's CSV importer **creates a new card** for a word it
already has rather than rescheduling it. So any word present in the
backup — in *any* status — becomes a duplicate on import.

New rule (now implemented): **drop a candidate if its key exists in
`backup_index` at all.** Only `reason == "new"` (key absent) survives.
The report still records the skip reason as the word's status, so the
user sees how many `seen-only` / `passive` / `mastered` words were
dropped. The "Filter rules" and "Risks / decisions" sections below
describe the original design and are kept for history; where they
conflict with this amendment, the amendment wins.

## Goal

Filter a freshly generated word list against the user's existing
Reword vocabulary so the CSV only contains words worth importing —
words not already in Reword. Any word present in the backup (any SRS
status) is dropped to avoid duplicate cards on import.

## Public API

```python
from src.dedup import dedup, DedupReport

filtered, report = dedup(words, backup_index)
# words:         list[dict] from BL-07/08 (each has at least "word")
# backup_index:  dict[str, ClassifiedWord] from BL-02 read_backup()
# filtered:      list[dict] — input items that survived
# report:        DedupReport with kept / skipped counters + breakdown
```

A thin convenience wrapper returns only the list:

```python
filtered = dedup_only(words, backup_index)
```

## Filter rules

For each input item:

1. Compute key = `normalize_key(item["word"])` (reuse BL-02 helper:
   strip → lowercase → drop leading `to `).
2. If `key` is empty → skip with reason `"empty-word"`.
3. Lookup `backup_index.get(key)`:
   - Not found → **keep**, reason `"new"`.
   - status `mastered` → **skip**, reason `"mastered"`.
   - status `active-long` → **skip**, reason `"active-long"`.
   - any other status (`active`, `passive-mastered`, `passive-long`,
     `passive`, `seen-only`) → **keep**, reason matches the status
     (so the report shows which weak state the word is in).
4. In-list dedup: if the same `key` appears twice in `words`, keep
   the first occurrence, drop the rest with reason `"in-list-duplicate"`.

## DedupReport shape

```python
@dataclass(frozen=True)
class DedupReport:
    kept: int
    skipped: int
    reasons: dict[str, int]   # reason -> count
    decisions: list[tuple[str, str, str]]
    # decisions: (word, "kept"|"skipped", reason) for every input item;
    # CLI uses this for the per-run log.
```

`__str__` returns a short multi-line summary suitable for CLI output:

```
Dedup: 137 kept / 63 skipped
  new:               104
  passive:           20
  seen-only:         13
  ─────────────────
  mastered:          42
  active-long:       15
  in-list-duplicate: 6
```

## Tests

- Synthetic `backup_index` (built directly, not from SQLite) covers
  all 7 statuses. Each status routes to the expected kept/skipped
  bucket.
- `to leverage` in input matches `leverage` in backup (and vice
  versa) — `normalize_key` parity with BL-02.
- In-list duplicate (two `to leverage` rows) keeps only the first.
- Empty / whitespace word → skipped with `empty-word`.
- `DedupReport.reasons` counts match `decisions`.
- `dedup_only` returns the same list as `dedup(...)[0]`.

## Out of scope

- Fuzzy / typo matching (P3).
- Threshold customization at runtime (P3) — thresholds live in BL-02.
- Reading the SQLite backup — that's BL-02; `dedup` accepts the
  already-parsed dict.

## Risks / decisions

- **Skip both `mastered` and `active-long`** — RFC mirrors BL-06
  spec verbatim; user spent SRS effort already, no value re-learning.
- **Keep `passive-mastered`** — recognition isn't production, so the
  word is still worth practicing actively. Matches user intent.
- **Report by reason, not by status alone** — `"new"` and
  `"in-list-duplicate"` are not Reword statuses but matter for the
  CLI log; treat reason as the primary axis.
- **Pure function** — no I/O, no logging side effects. The CLI logs
  from the returned `DedupReport`.
