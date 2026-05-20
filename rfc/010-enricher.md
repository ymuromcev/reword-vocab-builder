---
id: RFC-010
bl: BL-10
title: Example sentences + RU translation enricher
status: approved
date: 2026-05-19
---

## Goal

Given a word object (already has `word`, may have `source_quote` from
BL-08), produce 5 fields: `ru`, `ex1_en`, `ex1_ru`, `ex2_en`, `ex2_ru`.

## Public API

```python
from src.enricher import enrich

enriched = enrich(word_obj: dict) -> dict
# input:  {"word": "to leverage", "source_quote": "..."}  (source_quote optional)
# output: {"word": ..., "ru": "...", "ex1_en": ..., "ex1_ru": ...,
#          "ex2_en": ..., "ex2_ru": ...}
```

Batch helper:

```python
enrich_many(words: list[dict], *, llm) -> list[dict]
```

Both accept `llm=` for dependency injection.

## Prompt design

System prompt:

```
You are a bilingual translator (English ↔ Russian) helping a learner
build vocabulary. Output JSON with keys: ru, ex1_en, ex1_ru, ex2_en,
ex2_ru.

Rules:
- ru: 1-3 word natural Russian translation. Not a literal calque.
- ex1_en: short (≤10 words), conversational.
- ex2_en: medium (10-18 words), shows a different usage context.
- ex*_ru: natural Russian rendering, not word-for-word.
- ABSOLUTELY NO of these symbols in any English example:
  $, %, →, +, /, K, x, $$ (anything dollar-related), parens with
  numbers. They break Reword's read-aloud.
- Quote signals: examples are spoken aloud by TTS — anything that
  doesn't pronounce naturally is forbidden.
```

If `source_quote` is provided in the word_obj, append:

```
Use this real sentence (lightly adapted if needed) as ex2_en:
"{source_quote}"
```

## Sanitation

After LLM returns:

- Strip whitespace, ensure all 5 fields non-empty.
- Forbidden-symbol regex check on `ex1_en` and `ex2_en`. If any hit:
  one retry with explicit "previous response contained {sym} — remove
  it and reissue".
- Max 2 LLM calls per word.

## Batching

`enrich_many` chunks input into batches of 20 words per LLM call where
the response is `{word: {ru, ex1_en, ...}}` keyed by word. Saves
tokens.

## Tests

- Fake LLM returns canned JSON → output has all 5 fields populated.
- Forbidden-symbol filter triggers retry on `$` / `%` / `K`.
- `source_quote` shows up in the user message of the LLM call (assert
  via fake LLM capturing inputs).
- Batch path: 25 words → 2 calls (20 + 5).

## Out of scope

- Other target languages (P3).
- ML-based translation (LLM only).

## Risks / decisions

- **Symbol blacklist** — Reword reads everything aloud; one stray `$`
  ruins the example. Hard fail + retry is the cheap way to enforce.
- **Batching by 20** — empirical sweet spot between context cost and
  call overhead.
- **Inject LLM client** — same pattern as BL-07, keeps tests offline.
