---
id: RFC-013
bl: BL-13
title: End-to-end smoke test for the deterministic pipeline
status: approved
date: 2026-05-20
---

## Goal

Most modules already ship unit tests from layer-1 (BL-02/03/04/05/
07/08/09/10) and layer-2 BL-06. This RFC closes the remaining gap:
**one integration smoke test** that wires the deterministic pieces
together (backup-read → dedup → verb-prefix → CSV-write) and asserts
the output file is what Reword expects.

Anything LLM-shaped (BL-07/08/10) is faked at the API boundary —
no real network, no API keys. The smoke covers the glue between
modules, not the modules themselves.

## What is in scope

- `tests/test_integration_smoke.py`
- `tests/fixtures/integration/reword_test.backup` — small SQLite
  built **programmatically** in a `conftest.py` fixture (never a
  copy of the real backup).
- `tests/fixtures/integration/expected.csv` (or byte-level expected
  string inside the test) — what the pipeline must produce.

## What is out of scope

- Per-module unit tests — already shipped by layer-1 and BL-06.
- End-to-end with a real LLM — that's a manual pre-release smoke,
  not a pytest case.
- CI workflow (`.github/workflows/*.yml`) — flagged as P2 in BL-13,
  add later in a separate task.
- CLI invocation testing — BL-11 has its own tests.

## Pipeline under test

```
fake topic generator (BL-07 stub)
   ├─ returns: [{"word": "leverage", ...}, {"word": "to align", ...},
   │            {"word": "iterate", ...}, {"word": "dominate", ...}]
   ▼
dedup(words, read_backup(fixture_path))   # BL-02 + BL-06
   ├─ "dominate" is mastered in the fixture → dropped
   ▼
fake IPA + fake enricher (BL-09 + BL-10 stubs)
   ├─ deterministic, returns canned (ipa, ex1, ex2, ru) per word
   ▼
to_prefix() applied (BL-04)
   ├─ "leverage" → "to leverage"; "to align" stays; nouns stay
   ▼
write_csv(rows, tmp_path / "out.csv")     # BL-05
   ▼
read back → assert columns, count, sample row
```

## Fixture details

- `reword_test.backup` fixture (fresh per test, via `tmp_path`):
  - `dominate` — mastered (S_REP=5, I_REP=90 days).
  - `leverage` — `passive` (S_REC=1, I_REC=2 days). Stays in CSV.
- Verb-detector fake uses `set_nlp(...)` from BL-04 to inject a
  small TAGS table so the test doesn't depend on `en_core_web_sm`.
- LLM-shaped stubs (`enrich`, `transcribe`) are local fakes; no
  Anthropic SDK call, no CMU dict lookup needed.

## Assertions

- The output CSV has exactly N rows (computed from input minus
  `mastered`).
- Each row has all 7 columns populated (verifies BL-05 validation
  reached).
- Verbs carry the `to ` prefix; non-verbs do not.
- `dominate` is absent (dedup actually filtered it).
- `DedupReport.reasons["mastered"] == 1`.

## Tests in this BL

Just one file:

```
tests/test_integration_smoke.py
  test_pipeline_produces_expected_csv
  test_pipeline_drops_mastered
  test_pipeline_applies_to_prefix_only_to_verbs
```

## Risks / decisions

- **One smoke, not many** — every additional integration test
  doubles maintenance for low marginal value. Unit tests already
  cover the matrix; smoke proves the glue.
- **Fakes at module boundary** — patch
  `src.generators.topic.generate`, `src.ipa.transcribe`,
  `src.enricher.enrich_many` via `monkeypatch`. Keeps the test
  hermetic.
- **No coverage gate** — BL-13's "coverage > 80%" goal lives at the
  module level (already met by layer-1 + BL-06 unit tests). Adding
  a pytest-cov dependency just for a gate is yak-shaving.
