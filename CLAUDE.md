# reword-vocab-builder — Claude Code notes

Project-level instructions for Claude Code (or any AI agent) working in
this repo. Human-facing overview lives in [README.md](README.md).

## What this project is

A CLI + Claude Code skill that generates Reword-ready English
vocabulary CSVs.

- `src/` — Python implementation (CLI, generators, backup reader, CSV writer).
- `tests/` — Pytest-based unit tests for deterministic pieces.
- `skill/SKILL.md` — Claude Code skill wrapper that calls the CLI.
- `private/backlog/` — task list (BL-NN.md). `private/` is gitignored
  except for `backlog/`.

## Running

```bash
reword-vocab topic "<topic prompt>"
reword-vocab source <file> --instruction "<one-line instruction>"
```

## Secrets

- Google Drive access via MCP only. No tokens in repo, no `.env`.
- The Reword backup (`reword_en.backup`) contains personal vocabulary
  history. Never commit it.
- Test fixtures must use synthetic data.

## Tests

```bash
pytest
```

Testing policy:

- Pytest (chosen over stdlib `unittest` for parametrize + fixtures).
- Mock the network (no real Drive / LLM calls in unit tests).
- Pure helpers default — side-effectful code isolated in `cli.py` and
  `drive_mcp.py`.
- Add a smoke test for every new module.

## Delivery surface

Both CLI and Claude Code skill ship together.

- **CLI** is canonical and testable. All logic lives here. Single
  entrypoint: `reword-vocab`.
- **Skill** is a thin wrapper at `skill/SKILL.md` with trigger phrases
  like "build vocab for X", "extract vocab from <file>". It calls the
  CLI under the hood.

Rationale: the CLI works without Claude (cron jobs, scripts, manual
runs). The skill surfaces the tool naturally during interview prep /
reading sessions inside Claude Code.

## Working rules (for Claude / any AI assistant)

- **Don't invent product decisions.** Surface decisions to the user
  before implementing.
- **Don't commit personal data.** The Reword backup is read-only and
  lives outside the repo.
- **Respect backlog gating.** Every code change maps to a `BL-NN.md`
  task. If no task exists, create one first.
- **Code + comments + var names in English.** Backlog and user-facing
  prose can be Russian (this is Jared's working language with himself).
- **Pre-code image of result.** For any non-trivial task, describe what
  the user will see / get before writing code. Wait for approval.
- **Verbs in generated CSVs must be prefixed with `to `** — base form
  only. Phrasal verbs, gerunds, nouns and idioms stay unprefixed.

## Local artifacts (gitignored)

User-personal artifacts live in the repo but never get committed:

- `output/*.csv` — generated vocab CSVs the user has imported (or will
  import) to Reword. Includes prior libraries like `pm_interview_vocab.csv`.
  This folder is the canonical home for the user's vocab library; any
  stray CSV found elsewhere (Desktop, Downloads) should be moved here.
- The Reword backup file (`reword_en.backup`) is read from Google
  Drive via MCP, or from a local path set via `REWORD_BACKUP_PATH`.
  Never copied into the repo.

The skill (`skill/SKILL.md`) treats these as conventions — see its
"File locations" and "Dedup behavior" sections — and should not ask
the user about paths on every run.

## Out of scope

- Hosted / SaaS deployment. Self-host only.
- Non-Reword export formats. Anki, Quizlet, etc. could be added later
  but aren't a priority.
- Translation pairs other than English → Russian. Architecture allows
  expansion but initial focus is single-pair.
