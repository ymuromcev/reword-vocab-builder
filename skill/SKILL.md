---
name: reword-vocab
description: Generate a Reword-ready English vocabulary CSV from a topic or source file
trigger-phrases:
  - "build vocab for *"
  - "generate vocabulary from *"
  - "extract vocab from <file>"
  - "make a reword csv for *"
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

## How

```bash
reword-vocab topic "<query>"
reword-vocab source <path> --instruction "<text>"
```

Output: CSV at `./output/<timestamp>-<slug>.csv`, ready to import into
Reword.

## What the skill should NOT do

- Do not run vocabulary generation without confirming the topic /
  source with the user.
- Do not push the output CSV anywhere — leave it as a local file for
  the user to import manually.
- Do not commit the Reword backup or any vocabulary the tool reads.
