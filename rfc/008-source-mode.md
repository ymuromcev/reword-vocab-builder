---
id: RFC-008
bl: BL-08
title: Source-mode ingestor (PDF/EPUB/text/HTML)
status: approved
date: 2026-05-19
---

## Goal

Given a file path + one-line instruction, extract a vocabulary list
grounded in the source. Preserve the original sentence each word came
from (for BL-10 example sentence reuse).

## Public API

```python
from src.generators.source import extract

words = extract(source_path: str | Path, instruction: str) -> list[dict]
# each item:
#   {"word": "leverage", "part_of_speech": "verb",
#    "source_quote": "We leveraged our existing CRM data...",
#    "context_note": "from chapter 3"}
```

## File-type dispatch

| extension       | parser                  |
|-----------------|-------------------------|
| `.pdf`          | `pypdf` (PyPDF2 fork)   |
| `.epub`         | `ebooklib`              |
| `.txt`, `.md`   | stdlib (read text)      |
| `.html`, `.htm` | `beautifulsoup4`        |

Unknown extension: raise `UnsupportedSourceError`.

PDFs that are image-only (OCR needed): out of scope, raise an explicit
error so the user knows.

## Chunking

Read all text → split into chunks of ≤4000 tokens (use `tiktoken`
approximation or a `len(text)//4` heuristic). Maintain a chunk index so
each extracted word can carry the original sentence.

## LLM prompt per chunk

System prompt asks the model to return JSON:

```
[
  {"word": "...", "part_of_speech": "...", "source_quote": "..."}
]
```

with `source_quote` = the sentence containing the word, verbatim from the
chunk. Drop items where `source_quote` is not actually a substring of the
chunk (basic defense against hallucination).

User message: `Instruction: {instruction}\n\nText:\n{chunk}`.

## Merging chunks

After all chunks processed:

1. Concatenate lists.
2. Dedup by `normalize_key(word)` (same helper as BL-02).
3. Keep the longest / most informative `source_quote` per duplicated
   word.

## Tests

- 3 fixture files under `tests/fixtures/sources/`:
  - `sample.txt` (small).
  - `sample.html` (small).
  - A tiny synthetic PDF generated in the test (with `reportlab` dev
    dependency) so we don't commit a real book.
- Mock the LLM client; verify chunk count and dedup behaviour.
- `UnsupportedSourceError` raised on `.docx`.
- Hallucination filter: LLM returns a `source_quote` not in the chunk →
  item dropped.

## Out of scope

- OCR for scanned PDFs (P3).
- Audio transcripts (separate BL with Whisper).
- DOCX (add later if needed).

## Risks / decisions

- **Substring check on `source_quote`** — cheap, catches the most
  common hallucination mode.
- **Tiny synthetic PDF in tests** — avoids checking in copyrighted
  material and keeps fixtures lightweight.
- **No streaming** — files are small enough that we can hold them in
  memory; revisit if multi-MB EPUBs come up.
