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

Thin wrapper around the `reword-vocab` CLI. Surfaces the tool inside
Claude Code when the user asks for vocabulary generation during
interview prep, reading, or course work.

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

## Running

Topic mode:
```bash
reword-vocab topic "<exact prompt the user confirmed>"
```

Source mode:
```bash
reword-vocab source <path> --instruction "<one-line instruction>"
```

Both write `output/<YYYY-MM-DD>-<slug>.csv`. If any IPA failed or any
word couldn't be enriched, the CLI also writes
`output/<YYYY-MM-DD>-<slug>-flagged.txt`.

## After the run — show preview, not just the path

Once the CLI exits 0:

1. Print the absolute path to the CSV.
2. Print the summary the CLI emitted (kept / skipped / flagged counts).
3. Read the first 10 rows of the CSV and show them as a markdown table
   (columns: word, IPA, RU translation only — full 7-column row is too
   wide for chat).
4. If a `-flagged.txt` file exists, mention it and show its contents.

If the CLI exits non-zero, surface the error message verbatim — the
CLI's exit messages are designed for humans.

## What the skill must NOT do

- Do not run vocabulary generation without confirming the topic /
  source with the user first.
- Do not push the output CSV anywhere or open it in another app —
  leave it as a local file for the user to import manually into Reword.
- Do not commit the Reword backup or any vocabulary the tool reads —
  the backup contains personal SRS history and is gitignored.
- Do not bypass dedup ("just give me all 200 words anyway") —
  re-importing mastered words breaks the user's SRS schedule. If the
  user insists, point them at the CLI directly.
