---
id: RFC-007
bl: BL-07
title: Topic-mode vocab generator (LLM)
status: approved
date: 2026-05-19
---

## Goal

Given a topic string, return ~200 base-form English words/phrases
relevant to that domain, no duplicates, no fluff.

## Public API

```python
from src.generators.topic import generate

words: list[dict] = generate(topic: str, target_count: int = 200)
# each item: {"word": "leverage", "part_of_speech": "verb",
#             "context_note": "common in PM/strategy"}
```

Output items contain only `word` / `part_of_speech` / `context_note`.
IPA / examples / translation are added downstream (BL-09, BL-10).

## LLM backend

Use the Anthropic SDK (`claude-sonnet-4-6` by default — fast and cheap,
quality is fine for word lists). Read `ANTHROPIC_API_KEY` from env.
Single user-facing message; system prompt configured in the module.

For unit tests: backend is injected. `generate(topic, *, llm=fake_llm)`
must allow a fake that returns deterministic JSON.

## Prompt design

System prompt (sketch):

```
You are an expert vocabulary curator for English learners preparing for
{domain} contexts. Output ONLY a JSON array of objects with fields:
word, part_of_speech (verb|noun|adjective|adverb|phrase|idiom),
context_note (short, ≤8 words).

Rules:
- Base form only. Verbs without "to" prefix.
- No obvious words (project, team, work, manager, plan).
- No company names, no brand names.
- No duplicates.
- Mix: ~40% verbs/phrasal verbs, ~30% nouns, ~20% adjectives/adverbs,
  ~10% idioms.
- Cover collocations a non-native speaker would not naturally produce.
```

Domain auto-detect: include the raw topic verbatim in the user message.

## Batching for target_count

Single call asks for `target_count + 20%`. Dedup by lowercased word.
If under target_count after dedup, one retry with "extend the list,
avoiding these words: {seen}". Max 2 calls.

## Output sanitation

- Strip whitespace, lowercase the dedup key.
- Drop items with empty `word` or missing fields.
- Drop items whose `word` contains digits or `$%→/+xK`.

## Tests

- Fake LLM returns canned JSON → `generate()` returns parsed list of
  correct shape.
- Dedup within batch (fake returns duplicates).
- Sanitation drops invalid items.
- Empty topic raises `ValueError`.

## Out of scope

- IPA / examples / translation (BL-09, BL-10).
- Source-mode extraction (BL-08).
- Interactive review UI (P3).

## Risks / decisions

- **JSON output over freeform** — parsing reliability outweighs prompt
  brittleness; Anthropic API supports it well with a clear schema in
  the system prompt.
- **Inject LLM client** — keeps unit tests offline; real client lives
  in a thin factory used by CLI.
