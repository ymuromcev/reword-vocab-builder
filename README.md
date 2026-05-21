# reword-vocab-builder

Generate Reword-ready English vocabulary CSVs from any topic or source file, deduplicated against your existing learning history.

[Reword](https://reword.app) is an Android/iOS flashcard app for English vocabulary with SM2-style spaced repetition. This tool builds import-ready CSVs in Reword's native 7-column format.

## Quick start — Claude Desktop / Claude Code

If you have Claude Desktop or Claude Code installed, you don't need Python, pip, or an Anthropic API key — the LLM is already in your chat session. One-time install:

```bash
git clone https://github.com/ymuromcev/reword-vocab-builder.git
cd reword-vocab-builder
bash install-skill.sh
```

That copies the skill into `~/.claude/skills/reword-vocab/` and creates the output directory at `~/Documents/reword-vocab-output/`. After install, you can delete the cloned repo — the skill is self-contained.

Then, in any Claude chat:

> build vocab for system design interview

Claude will confirm the topic, generate candidate words, dedupe against your Reword backup + any prior CSVs in your output dir, and write a Reword-ready CSV. Import it into Reword via the app's import screen.

## What you'll see

A typical in-chat run prints something like:

```
→ Candidates: 198 (topic: PM interview vocabulary)
→ Backup: 1,847 words classified — 46 dedup'd as mastered/active-long
→ Prior CSVs: 8 dedup'd
→ IPA: 144/144 (CMU 132 · LLM 12)
✓ ~/Documents/reword-vocab-output/2026-05-21-pm-interview-vocabulary.csv (144 rows)
```

Followed by a 10-row preview table (word + IPA + RU translation) so you can sanity-check before importing.

## Output format

Standard Reword 7-column CSV import format:

- Semicolon-separated, UTF-8 encoded, no header row.
- All values double-quoted.
- Columns: `word; IPA_US; ru_translation; example1_en; example1_ru; example2_en; example2_ru`.
- Verbs prefixed with `to ` (e.g. `to leverage`, `to circle back`).

Example row:

```
"to leverage";"[ˈlevərɪdʒ]";"использовать (по максимуму)";"We need to leverage existing customer data here.";"Нужно по максимуму использовать существующие данные о клиентах.";"Let's leverage our existing partnerships first.";"Давай сначала используем наши существующие партнёрства."
```

## Dedup rules

The skill reads your Reword backup (SQLite file) and skips words you already know well:

| State | Definition | Action |
|---|---|---|
| mastered | review interval at least 60 days | skip |
| active-long | review interval at least 14 days | skip |
| active short-term | review interval under 14 days | keep |
| passive | seen but not actively reviewed | keep |
| seen-only | dictionary entry, never studied | keep |

It also dedupes against any CSV already in your output directory (so you don't relearn words you've already imported).

## Backup file resolution

The skill (and the CLI) resolves the Reword backup in this order:

1. `REWORD_BACKUP_PATH` env var — explicit local path wins.
2. iCloud sync (macOS only) — reads `~/Library/Mobile Documents/iCloud~ru~poas~englishwords/Documents/reword_en.backup`.
3. Google Drive via the [Drive MCP connector](https://docs.claude.com/en/docs/claude-code/mcp).

The first two work fully offline. The Drive fallback requires the Drive MCP server to be configured.

## Updating the skill

After `git pull` in the cloned repo, re-run `bash install-skill.sh` to push the new SKILL.md and helpers into your skill library. The script is idempotent; running it twice is a no-op.

If you deleted the cloned repo after install: `git clone` again, then `install-skill.sh`.

---

## Power user / headless CLI

The `reword-vocab` CLI is a standalone alternative for cron jobs, CI, and any environment without a Claude session. It does the same work as the skill but uses the Anthropic API directly, so it needs an API key.

```bash
pip install -e .
python -m spacy download en_core_web_sm
export ANTHROPIC_API_KEY=sk-ant-...

reword-vocab topic "PM interview vocabulary"
# → ~/Documents/reword-vocab-output/2026-05-21-pm-interview-vocabulary.csv

reword-vocab source ~/Documents/inspired.pdf --instruction "PM vocabulary"
# → ~/Documents/reword-vocab-output/2026-05-21-inspired-pm-vocabulary.csv
```

Supported source formats: PDF, EPUB, HTML, plain text.

Override the output dir for one run with `--output PATH` or globally with `REWORD_VOCAB_OUTPUT_DIR`.

| Flag | Default | Notes |
|---|---|---|
| `--target-count N` | 200 | Topic mode only |
| `--output PATH` | `$REWORD_VOCAB_OUTPUT_DIR/<auto>.csv` | Override output path |
| `--backup-path PATH` | Auto-resolved (see above) | Force a specific backup file |

### CLI troubleshooting

**`error: ANTHROPIC_API_KEY environment variable is required`** — The CLI needs an Anthropic API key for word generation and example enrichment. If you're in a Claude Desktop chat, use the skill instead (no key needed). For headless use: `export ANTHROPIC_API_KEY=sk-ant-...`.

**`error: Drive MCP client is not available...`** — Either configure the Google Drive MCP connector, or set `REWORD_BACKUP_PATH` to a local copy of the backup file.

**`error: source produced no words: ...`** — The PDF/EPUB was unreadable. Try copying its contents into a plain `.txt` file and rerunning.

**`error: unsupported source type: .docx`** — Only PDF, EPUB, HTML, and plain text. Convert the file or use topic mode.

**`Output mentions a -flagged.txt file`** — Words the CLI couldn't fully transcribe or enrich. The CSV is still valid; the `.txt` lists what to add by hand.

## Why it exists

I (Jared) studied 5,000+ English words via Reword over several years and now want to layer domain-specific vocabulary on top — PM interview language, books I'm reading, podcast transcripts. Doing this by hand once was painful. This tool makes it repeatable.

## Contributing

This is a personal tool published openly for transparency. Feedback and PRs welcome, but priorities are set by my own learning needs.

## License

MIT — see [LICENSE](LICENSE).
