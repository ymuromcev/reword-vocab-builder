---
id: RFC-004
bl: BL-04
title: Verb detector and `to ` prefix rule
status: approved
date: 2026-05-19
---

## Goal

Detect English verbs (base form, phrasal, idiomatic) and prepend `to `
exactly once. Idempotent.

## Public API

```python
from src.verb_detector import is_verb, to_prefix

is_verb("leverage")     # True
is_verb("circle back")  # True
is_verb("running")      # False (gerund)
is_verb("trade-off")    # False (noun)

to_prefix("leverage")   # "to leverage"
to_prefix("to align")   # "to align"  (idempotent)
to_prefix("trade-off")  # "trade-off"
```

## Detection pipeline

Tried in order, first hit wins:

1. **Manual override** — `config/verb_overrides.yaml` with two lists:
   `verbs:` and `not_verbs:`. Loaded once at module import.
2. **`to `-prefixed input** — already a verb, strip prefix for the rest
   of the pipeline (to handle re-runs).
3. **Single word, base form** — spaCy POS tagging. Treat as verb iff
   `token.tag_ == "VB"` (base form). Reject `VBG/VBD/VBN`.
4. **Phrasal verb (two-word)** — head word is base-form verb AND second
   word is preposition/particle (`back, in, out, up, down, into, over,
   through, off, on`). Examples: `circle back`, `dive in`, `roll out`.
5. **Idiom (≥2 words)** — first token is base-form verb per spaCy.
   Examples: `raise the bar`, `bake in`, `move the needle`.
6. Default: not a verb.

## Dependencies

- `spacy` + `en_core_web_sm` (downloaded on first run via setup script
  documented in README; do not auto-download at import).
- No NLTK / WordNet dependency.

## `to_prefix` rule

```python
def to_prefix(word: str) -> str:
    if word.startswith("to "):
        return word
    return f"to {word}" if is_verb(word) else word
```

## Tests

- Cherry-picked set of 50+ verbs and 50+ non-verbs from PM vocab list.
- Phrasal verbs: `circle back`, `push back`, `dive in`, `roll out`.
- Idioms: `raise the bar`, `move the needle`, `bake in`.
- Idempotency: `to_prefix(to_prefix(x)) == to_prefix(x)`.
- Override file precedence: override marks `data` as not_verb even
  though spaCy would say VB.

## Out of scope

- Articles for nouns (`a/an/the`).
- Non-English verb detection.

## Risks / decisions

- **spaCy over NLTK** — better POS accuracy, single dep, easier model
  download.
- **Override file** — escape hatch for known model misfires; checked
  into repo at `config/verb_overrides.yaml`.
- **Model not auto-downloaded** — explicit setup keeps tests
  hermetic; CI uses a tiny mock.
