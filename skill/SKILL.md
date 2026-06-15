---
name: reword-vocab
description: Generate a Reword-ready English vocabulary CSV from a topic or a source file (PDF/EPUB/HTML/text). Use when the user asks to build, generate, or extract vocabulary for interview prep, reading, or a domain topic.
trigger-phrases:
  - "build vocab for *"
  - "build vocabulary for *"
  - "generate vocabulary from *"
  - "extract vocab from *"
  - "extract vocabulary from *"
  - "make a reword csv for *"
  - "prep vocab for *"
  - "создай словарь для *"
  - "построй словарь для *"
  - "вытащи слова из *"
  - "вытащи словарь из *"
  - "сделай словарь по *"
---

# reword-vocab skill

When invoked inside Claude Code, **Claude does the work directly** —
read the source, extract words, dedup against the Reword backup and
prior CSVs in `output/`, enrich (IPA + RU translation + example
sentences), and write the CSV. No external CLI call, no
`ANTHROPIC_API_KEY` env var, no `pip install` — Claude is already an
LLM in this session and can do every step.

The Python CLI (`reword-vocab topic ...`, `reword-vocab source ...`)
exists as a **standalone fallback** for environments without a Claude
session: cron jobs, scripts, headless runs. Inside Claude Code, do
not shell out to it.

## When to invoke

- User asks to build vocabulary for a topic / domain / role.
- User shares a book, article, or transcript and asks to extract
  vocabulary from it.
- User is preparing for an interview and mentions wanting domain vocab.

## Before running — confirm with the user

This is a hard rule: **never run the CLI without first confirming the
topic or source with the user**. The CLI consumes LLM tokens and writes
files; silent runs are not OK.

For topic mode, confirm:
- The exact topic prompt (paraphrased back, not just yes/no).
- Target word count (default 200; offer 100 / 200 / 500).

For source mode, confirm:
- The file path you'll pass in.
- The one-line `--instruction` (what slice of vocabulary to extract).

## File locations — assume these and stop asking

The user has settled on these defaults. Do not ask again:

- **Output dir (single source of truth)** — `$REWORD_VOCAB_OUTPUT_DIR`
  if set, otherwise `~/Documents/reword-vocab-output/`. This is the ONE
  canonical location: the skill both **writes** new CSVs here and
  **reads** this same dir for prior-CSV dedup. Never write decks to one
  place and dedup-scan another. The installer creates the dir; ensure
  it exists before writing.
- **Reword backup** — canonical source is the iCloud Reword folder
  on macOS (`~/Library/Mobile Documents/iCloud~ru~poas~englishwords/Documents/reword_en.backup`), or `$REWORD_BACKUP_PATH` if the user
  set one, or Google Drive via MCP as a last resort.
- **Output naming** — `<output_dir>/<YYYY-MM-DD>-<slug>.csv`. Stable
  convention; do not override.

If the user mentions a vocab CSV outside the canonical output dir
above, move it into that dir and proceed — do not ask.

## Dedup behavior — always against prior vocab CSVs

The CLI dedupes against the Reword backup by default. The skill adds
a **second dedup layer**: prior vocabulary CSVs already in `output/`.

These prior CSVs represent words the user has already imported to
Reword (or intends to). Emitting a new CSV with overlapping words
wastes the user's time and breaks the SRS schedule.

Process:

1. Before invoking the CLI, list `output/*.csv` and remember them as
   "prior CSVs" (exclude the file the CLI is about to write).
2. After the CLI emits its CSV, post-filter: for each row, drop it if
   the `word` field (case-insensitive, normalised — strip any leading
   `to `) matches a word in any prior CSV's first column.
3. Save the deduped CSV in place. Report: "<N> rows after backup
   dedup, <M> rows after prior-CSV dedup".

Skip step 2 only if the user explicitly says "include duplicates from
prior CSVs". Default is always dedup.

## Default candidate-word filter

When the user asks for "all vocabulary" / "все слова" from a source,
translate that into the following baseline `--instruction` (extend as
needed for the specific case):

> "Extract every content word from the source: nouns, verbs (including
> phrasal verbs), adjectives, adverbs, idioms, fixed expressions, and
> domain-specific terms. Exclude function words (the, a, an, of,
> with, was, has, do, my, your, etc.) and A1/A2 basic vocabulary (I,
> you, get, go, time, day, work as common noun, etc.). Include rare,
> figurative, or technical items even if they appear only once."

The user's stated default (2026-05-20) is: include everything that
isn't basic English or a stop-word, even one-shot occurrences. Encode
that into the instruction unless the user says otherwise.

## Inline Python harness — how to import helpers

The skill ships its pure-Python helpers at
`~/.claude/skills/reword-vocab/lib/` (copied there by
`install-skill.sh`). When you need them, write an inline `python3`
script via the `Bash` tool and prepend that path to `sys.path` so the
helpers are importable without `pip install`:

```python
import os, sys
sys.path.insert(0, os.path.expanduser("~/.claude/skills/reword-vocab/lib"))

import backup_reader, dedup, ipa, csv_writer
from generators import source as src_gen
```

Helper API (one-line each):

- `backup_reader.read_backup(path) -> dict[str, ClassifiedWord]` —
  reads Reword's SQLite backup and classifies each word's SRS state.
- `dedup.dedup(candidates, backup_index) -> (kept, DedupReport)` —
  drops any candidate already present in the backup, in **any** SRS
  status (BL-18). Only words absent from the backup survive. The
  report still tallies the dropped words by their status.
- `ipa.transcribe(word, llm=None) -> (ipa_str, flagged)` — CMU-first
  US IPA. The skill bundle ships a frozen CMU dict at
  `lib/cmudict_frozen.json` so this works offline. Pass a callable
  for the LLM fallback if you want non-CMU words covered (in chat,
  do the fallback yourself — read the prompt's last line as the word
  and respond with `[ˌipaˌstring]`).
- `csv_writer.write_csv(rows, path)` — writes the 7-column Reword
  CSV (`word, ipa, ru, ex1_en, ex1_ru, ex2_en, ex2_ru`).
- `src_gen.read_source_file(path)` / pure parsing helpers — text
  extraction from PDF / EPUB / HTML / plain text.

## Execution recipe (inside Claude Code — the default path)

Do the following yourself, step by step. **Never** shell out to the
`reword-vocab` CLI from inside this chat. The CLI exists only for
headless / cron use; if the user explicitly wants the CLI, tell them
to run it from their own shell. The LLM steps below are *you*, not a
subprocess.

1. **Read source.**
   - Topic mode: generate ~200 candidate content words / idioms /
     fixed expressions for the topic, applying the Default
     candidate-word filter (above).
   - Source mode: read the file (`Read` tool). Extract EN content.
     Tokenise, lemma-normalise lightly, keep content words and
     multi-word expressions per the Default filter.

2. **Dedup vs Reword backup (strict — BL-18).** The backup is a
   SQLite file at `$REWORD_BACKUP_PATH` (preferred) or fetched from
   Google Drive via MCP. Build the `backup_index` via
   `backup_reader.read_backup(...)` and drop **any** candidate whose
   normalized key is present — in **any** SRS status, not just
   `mastered` / `active-long`. Rationale: Reword's importer creates a
   duplicate card for a word it already has (even a barely
   `seen-only` one), so re-emitting any known word leaks duplicates.
   Keep only words absent from the backup. If the backup isn't
   accessible, say so and proceed without it (warn the user once).

3. **Dedup vs prior CSVs.** Glob the single canonical output dir
   (`$REWORD_VOCAB_OUTPUT_DIR` or `~/Documents/reword-vocab-output/`) —
   the same dir step 5 writes to. Read column 1 of each CSV (exclude
   the file about to be written); drop any candidate already present
   (case-insensitive, strip leading `to `).

4. **For each remaining word, build the row:**
   - `word` — base form (prefix `to ` for verbs in base form; phrasal
     verbs and idioms stay unprefixed).
   - `IPA_US` — generate IPA (you know this directly; if unsure,
     produce best-effort and flag the row).
   - `ru_translation` — concise Russian gloss (1-3 senses if needed,
     comma-separated).
   - `example1_en` / `example2_en` — in **source mode**, use literal
     sentences from the source where the word appears (best 1-2 for
     showcasing usage). In **topic mode**, generate natural example
     sentences.
   - `example1_ru` / `example2_ru` — Russian translations of the
     above (natural, not calque).

5. **Write CSV** to
   `<output_dir>/<YYYY-MM-DD>-<slug>.csv` (output_dir resolves per
   the "File locations" section above) via
   `csv_writer.write_csv(rows, path)` from the inline harness so the
   format is identical to CLI output (7 columns, semicolon, all
   values double-quoted, UTF-8, no header, LF newlines).

6. **Show the user:**
   - Absolute path to the CSV.
   - Counts: `<N> candidates → <after_backup> after backup dedup →
     <after_prior> after prior-CSV dedup → <final> written`.
   - First 10 rows as a markdown table (word + IPA + RU translation
     only; full 7 columns are too wide for chat).
   - If any words were flagged (couldn't be fully enriched), list
     them.

## What the skill must NOT do

- Do not invoke vocabulary generation without confirming the topic /
  source with the user first.
- Do not push the output CSV anywhere or open it in another app —
  leave it as a local file for the user to import manually into Reword.
- Do not commit the Reword backup or any vocabulary the tool reads —
  the backup contains personal SRS history and is gitignored.
- Do not bypass dedup ("just give me all 200 words anyway") —
  re-importing any word already in Reword (any status) creates a
  duplicate card and breaks the user's SRS schedule.
- **Never** shell out to the `reword-vocab` CLI from inside a Claude
  chat. The CLI exists for headless / cron use only. If the user
  explicitly asks for the CLI path, tell them to run it from their
  own shell — do not invoke it from this session.
- Do not propose `pip install`, `spacy download`, or
  `export ANTHROPIC_API_KEY`. The skill works in-chat with zero
  setup beyond `bash install-skill.sh` (which the user runs once).
