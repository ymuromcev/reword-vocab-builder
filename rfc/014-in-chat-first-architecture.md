---
id: RFC-014
bl: BL-16
title: In-chat-first skill architecture (no CLI install, no API key)
status: implemented
date: 2026-05-21
---

## Goal

Make `reword-vocab` work for Claude Desktop users the way a Claude
Desktop skill is supposed to work: one-time install into
`~/.claude/skills/`, then any chat → trigger phrase → CSV on disk. No
`pip install`, no `spacy download`, no `ANTHROPIC_API_KEY`.

The CLI does not go away. It moves from "the primary surface" to
"the headless surface for cron and CI" — same behavior, secondary
status in docs.

This RFC also bundles **BL-17** (pyproject entry-point bug —
`src.cli:main` raises `ModuleNotFoundError: No module named 'src'`
without `PYTHONPATH=.`) because the fix is one motion: rename
`src/` → `reword_vocab/`.

## User-facing shape

### Default path — Claude Desktop user

```
# one-time install (from cloned repo, or a future curl|bash)
$ bash install-skill.sh
✓ Installed skill into ~/.claude/skills/reword-vocab/
✓ Output dir: ~/Documents/reword-vocab-output/
```

Then, in any Claude Desktop / Claude Code chat:

```
> build vocab for system design interview
```

Claude (this session, no subprocess):
1. Confirms topic / target count.
2. Generates candidate words directly.
3. Calls bundled Python helpers (`backup_reader`, `dedup`, `ipa`,
   `csv_writer`) via inline `python3` — no `pip install` required
   because the helpers ship inside the installed skill at
   `~/.claude/skills/reword-vocab/lib/`.
4. Writes
   `~/Documents/reword-vocab-output/2026-05-21-system-design.csv`.
5. Shows path + count + first 10 rows.

User does **not** do: `git clone`, `pip install`,
`export ANTHROPIC_API_KEY`, `spacy download`.

### Headless path — cron / CI (unchanged)

```
$ pip install -e .
$ export ANTHROPIC_API_KEY=sk-ant-...
$ reword-vocab topic "PM interview vocabulary"
→ output/2026-05-21-pm-interview-vocabulary.csv
```

Same as today. Described in README under "Power user / headless",
not in Quick start.

### Author's path — me (Jared), already-cloned repo

Same as the Claude Desktop path. After `bash install-skill.sh`, all
my existing sessions trigger the installed skill, not a per-repo
copy. The repo stays cloned for development of the skill itself, but
day-to-day vocab building does not depend on it being present.

## Design

### 1. Package rename: `src/` → `reword_vocab/`

Closes BL-17 simultaneously.

- Move `src/*.py` and `src/generators/` → `reword_vocab/`.
- Update all in-tree imports: `from src import X` → `from reword_vocab import X`. Affected: `src/cli.py`, `src/dedup.py`,
  `src/generators/topic.py`, all `tests/test_*.py`.
- `pyproject.toml`:
  - `[project.scripts] reword-vocab = "reword_vocab.cli:main"`.
  - `[tool.setuptools.packages.find]` becomes implicit (top-level
    `reword_vocab/` is discovered automatically).
- `tests/` keep their pytest discovery via existing
  `pythonpath = ["."]`.

After this, `pip install -e .` produces a working `reword-vocab`
shell command (BL-17 closed).

### 2. Skill installer (`install-skill.sh`)

New file at repo root. Idempotent bash script:

```
#!/usr/bin/env bash
set -euo pipefail
TARGET="${HOME}/.claude/skills/reword-vocab"
REPO="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "${TARGET}/lib"
cp "${REPO}/skill/SKILL.md" "${TARGET}/SKILL.md"
cp "${REPO}/reword_vocab/"*.py "${TARGET}/lib/"
cp -r "${REPO}/reword_vocab/generators" "${TARGET}/lib/generators"
mkdir -p "${HOME}/Documents/reword-vocab-output"
echo "✓ Installed skill into ${TARGET}"
echo "✓ Output dir: ${HOME}/Documents/reword-vocab-output/"
```

Why copy, not symlink: a copy is robust to the user later deleting
the repo. Skill is self-contained after install.

What gets copied:
- `SKILL.md`
- `lib/backup_reader.py`, `lib/csv_writer.py`, `lib/dedup.py`,
  `lib/ipa.py`, `lib/drive_mcp.py`, `lib/verb_detector.py`
- `lib/generators/source.py`, `lib/generators/topic.py`
  (pure parts — LLM-calling parts of `enricher.py` / `topic.py` are
  NOT used by the in-chat path and are not copied)

The skill's helpers must be **importable without `pip install`**.
Achieved by SKILL.md telling Claude to prepend
`~/.claude/skills/reword-vocab/lib` to `sys.path` in the inline
Python harness (see §4 below). No external dependencies inside
those helpers other than stdlib + `cmudict` (handled by §5).

### 3. Output directory default

- New default: `${REWORD_VOCAB_OUTPUT_DIR:-${HOME}/Documents/reword-vocab-output}`.
- Installer creates the dir.
- `SKILL.md` writes there.
- CLI (headless mode) writes there too — same env var, same default.
- Dedup against prior CSVs: SKILL.md globs both
  `${output_dir}/*.csv` AND, if the repo is present at
  `~/Desktop/Claude Code/reword-vocab-builder/output/`, that legacy
  dir too. Backward compatible for me.
- Legacy `<repo>/output/` is no longer the default but still
  honored by the CLI when `--output` is passed explicitly.

### 4. SKILL.md tweaks (small, not a rewrite)

`skill/SKILL.md` already prescribes the in-chat flow. Two edits:

a. **Where to find helpers.** Add a short section
   "Inline Python harness — how to import helpers" with the
   `sys.path.insert(0, os.path.expanduser("~/.claude/skills/reword-vocab/lib"))` boilerplate Claude must use at the top of any inline
   script. Document the helper API surface (one paragraph per
   helper) so Claude does not need to read source.

b. **Output dir convention.** Replace any reference to `output/`
   (repo-relative) with the env-aware default from §3.

c. **No-CLI rule (already present, sharpen language).** Change
   "Do not shell out to the `reword-vocab` CLI from inside Claude
   Code unless the user explicitly asks for it" → "Never call the
   CLI from inside a Claude chat. The CLI exists for headless use
   only (cron / CI). If the user explicitly asks for the CLI path,
   tell them to run it from their shell, not from this session."

### 5. cmudict dependency for IPA

`reword_vocab/ipa.py` imports `cmudict`. Three options:

- **(A)** Vendor a frozen `cmudict.json` (~6 MB) into the skill
  bundle so it works with zero pip installs. Trade-off: 6 MB bigger
  install. → **Chosen.** Skill is self-contained.
- **(B)** Document `pip install cmudict` in the installer. Trade-off:
  brings `pip` back into the user story. Rejected.
- **(C)** Do without CMU dict; rely entirely on Claude-generated IPA
  via in-chat fallback. Trade-off: bigger LLM workload per word,
  more drift. Rejected — CMU dict is exactly the kind of cheap pure
  function that we want to keep.

Implementation: `install-skill.sh` dumps `cmudict.dict()` to JSON
once during install, ships it as `lib/cmudict_frozen.json`. `ipa.py`
prefers the frozen file if present, falls back to the `cmudict`
package if not (so the CLI / dev path is unaffected).

### 6. README rewrite

Order of sections after rewrite (top → bottom):

1. **What it is** (1 paragraph).
2. **Quick start — Claude Desktop** (one `bash install-skill.sh`,
   one chat trigger, done).
3. **What you'll see** (chat transcript snippet).
4. **Output format** (CSV columns — unchanged).
5. **Dedup rules** (unchanged).
6. **Power user / headless CLI** (the current Quick start, demoted).
7. **Backup file resolution** (unchanged).
8. **Troubleshooting** (CLI troubleshooting moves under "Power user";
   add 2-3 in-chat entries).
9. **Contributing / License** (unchanged).

The "Using via Claude Code" paragraph and the troubleshooting
`error: ANTHROPIC_API_KEY environment variable is required` entry
both go away (replaced by the Quick start being chat-first).

## Migration

- **Existing `<repo>/output/` CSVs** — left in place. Dedup honors
  them via §3.
- **Existing CLI users** — `pip install -e .` still works after
  `src/` → `reword_vocab/` rename. The shell command name
  `reword-vocab` does not change.
- **Existing skill copies** — none in `~/.claude/skills/`. No prior
  installation to migrate from.
- **My local `output/` from BL-16's day** — copy
  `2026-05-21-jd-vocab.csv` (and other recent runs) to the new
  default dir as part of installer, so dedup picks them up next
  time. Done by the installer when it detects the legacy dir.

## DoD

- [ ] `src/` renamed to `reword_vocab/`. All in-tree imports updated.
      Tests green: `pytest`.
- [ ] `pyproject.toml`: entry-point is `reword_vocab.cli:main`.
      `pip install -e . && reword-vocab --help` works in a fresh
      venv with no `PYTHONPATH` hack.
- [ ] `install-skill.sh` at repo root, executable, idempotent.
      Running twice = no harm.
- [ ] After `bash install-skill.sh`, `~/.claude/skills/reword-vocab/`
      contains `SKILL.md`, `lib/*.py`, `lib/generators/`, and
      `lib/cmudict_frozen.json`.
- [ ] `SKILL.md` updated per §4 (harness boilerplate, output dir,
      sharpened no-CLI rule).
- [ ] `README.md` rewritten per §6 — Claude Desktop quick start
      first, CLI as power user.
- [ ] In a fresh Claude Desktop chat (new session), triggering
      `build vocab for X` produces a CSV in
      `~/Documents/reword-vocab-output/` with no question about
      API keys or pip install.
- [ ] Existing tests pass. New test added for the in-chat helper
      import path (importing `lib/*.py` directly works without
      `pip install`).
- [ ] Index updated: `rfc/000-index.md` lists RFC-014.
- [ ] BL-17 closed (or marked subsumed by BL-16) in
      `private/backlog/`.

## Out of scope

- claude-skills-marketplace publication (separate BL when the
  marketplace stabilizes).
- Changing the CSV format (7 columns, semicolon, double-quoted —
  unchanged).
- Changing dedup / IPA / verb-prefix logic.
- Removing `cmudict` from CLI dependencies (CLI keeps full deps;
  only the bundled skill ships the frozen dict).
- Windows support (still mac + Linux only).

## Risks

1. **6 MB skill bundle** — `cmudict_frozen.json` makes the skill
   directory larger. Mitigation: acceptable trade-off for
   self-containment; documented in install output.
2. **Diverging skill copy** — `~/.claude/skills/reword-vocab/lib/`
   can drift from `reword_vocab/` in the repo. Mitigation:
   installer is the only update path; user reruns it after `git
   pull` (documented in README).
3. **In-chat path silently shells out** — Claude could still
   subprocess the CLI by accident. Mitigation: SKILL.md §4(c) is
   explicit; pre-merge check is the smoke test in fresh session.

## Implementation order

Three sub-tasks, executed in this order (each its own commit):

1. **Package rename** (`src/` → `reword_vocab/`) — pure mechanical,
   tests prove it. Closes BL-17.
2. **Installer + helper bundle** — `install-skill.sh`, cmudict
   freeze step, SKILL.md updates.
3. **README rewrite** — restructure as §6.

Final step: smoke test in a fresh Claude Desktop chat.
