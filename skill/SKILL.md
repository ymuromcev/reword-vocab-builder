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

The user has settled on these defaults (2026-05-20). Do not ask again:

- **Vocab CSVs (current + prior generations)** live in `output/` of
  this repo. Both new outputs and previously-imported libraries
  (e.g. `pm_interview_vocab.csv`) sit here. The folder is gitignored.
- **Reword backup** — canonical source is Google Drive, fetched via
  the Drive MCP connector (the CLI's default last-step fallback). If
  the user has a faster local snapshot they want to use, they set
  `REWORD_BACKUP_PATH` once in their shell — not per command.
- **Output naming** — the CLI's default (`output/<YYYY-MM-DD>-<slug>.csv`)
  is the standard. Don't override `--output` unless the user asks.

If you find a vocab CSV the user mentions sitting outside `output/`
(e.g. on the Desktop), move it into `output/` and proceed — do not
ask whether to move it. This convention exists so the dedup step
below works without further configuration.

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

## Execution recipe (inside Claude Code — the default path)

Do the following yourself, step by step. No external CLI.

1. **Read source.**
   - Topic mode: generate ~200 candidate content words / idioms /
     fixed expressions for the topic, applying the Default
     candidate-word filter (above).
   - Source mode: read the file (`Read` tool). Extract EN content.
     Tokenise, lemma-normalise lightly, keep content words and
     multi-word expressions per the Default filter.

2. **Dedup vs Reword backup.** The backup is a SQLite file at
   `$REWORD_BACKUP_PATH` (preferred) or fetched from Google Drive via
   MCP. Connect via the `Bash` tool's `sqlite3` and pull words whose
   SRS state is `mastered` (review interval ≥ 60 days) or `active-long`
   (≥ 14 days). Drop those from candidates. If the backup isn't
   accessible, say so and proceed without it (warn the user once).

3. **Dedup vs prior CSVs.** Glob `output/*.csv`, read column 1 of
   each, drop any candidate already there (case-insensitive, strip
   leading `to `).

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

5. **Write CSV** to `output/<YYYY-MM-DD>-<slug>.csv` in Reword's
   7-column format (semicolon-separated, double-quoted, UTF-8, no
   header). Use the existing CSV writer style from prior outputs in
   `output/` if any exist.

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
  re-importing mastered words breaks the user's SRS schedule.
- Do not shell out to the `reword-vocab` CLI from inside Claude Code
  unless the user explicitly asks for it — Claude in this session
  does the work natively.
