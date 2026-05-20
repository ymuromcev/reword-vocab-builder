# reword-vocab-builder

Generate Reword-ready English vocabulary CSVs from any topic or source file, deduplicated against your existing learning history.

[Reword](https://reword.app) is an Android/iOS flashcard app for English vocabulary with SM2-style spaced repetition. This tool builds import-ready CSVs in Reword's native 7-column format.

## Quick start

```bash
# 1. Install
git clone https://github.com/ymuromcev/reword-vocab-builder.git
cd reword-vocab-builder
pip install -e .
python -m spacy download en_core_web_sm

# 2. Set your Anthropic API key (used for word generation + IPA fallback + enrichment)
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Generate vocabulary for a topic
reword-vocab topic "PM interview vocabulary"
# → output/2026-05-20-pm-interview-vocabulary.csv

# 4. Or extract from a book / article
reword-vocab source ~/Documents/inspired.pdf --instruction "PM vocabulary"
# → output/2026-05-20-inspired-pm-vocabulary.csv
```

Import the CSV into Reword via the app's import screen. The file is in Reword's native format — no conversion needed.

## What you'll see

Running `reword-vocab topic ...` prints progress as it goes:

```
→ Fetching backup via Drive MCP…
→ Backup: 1,847 words classified
→ Generating "PM interview vocabulary" (target=200)…
→ Generated 198 candidate words
→ Dedup: 152 kept / 46 skipped
→ IPA: 152/152 (CMU 138 · LLM 14)
→ Enrich: 152/152
→ Verb prefix applied to 43 words
✓ output/2026-05-20-pm-interview-vocabulary.csv (152 rows)
```

## Two modes

**Topic mode** — describe what you want vocabulary for, get a CSV.

```bash
reword-vocab topic "PM interview vocabulary"
reword-vocab topic "fintech and payments terminology" --target-count 100
```

**Source mode** — give it a book, article, or transcript, get vocabulary extracted from that source.

```bash
reword-vocab source ~/Documents/inspired-by-cagan.pdf --instruction "product management vocabulary I should learn"
reword-vocab source ~/Downloads/article.txt --instruction "business English I don't know yet"
```

Supported source formats: PDF, EPUB, HTML, plain text.

Both modes dedupe against your existing Reword backup (fetched from Google Drive or read from a local file) so you don't relearn words you already know.

## Options

| Flag | Default | Notes |
|---|---|---|
| `--target-count N` | 200 | Topic mode only |
| `--output PATH` | `output/<auto>.csv` | Override output path |
| `--backup-path PATH` | Auto-fetch from Drive | Use a local `.backup` file instead of Drive MCP |

## Why it exists

I (Jared) studied 5,000+ English words via Reword over several years and now want to layer domain-specific vocabulary on top — PM interview language, books I'm reading, podcast transcripts. Doing this by hand once was painful. This tool makes it repeatable.

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

The tool reads your Reword backup (SQLite file) and skips words you already know well:

| State | Definition | Action |
|---|---|---|
| mastered | review interval at least 60 days | skip |
| active-long | review interval at least 14 days | skip |
| active short-term | review interval under 14 days | keep |
| passive | seen but not actively reviewed | keep |
| seen-only | dictionary entry, never studied | keep |

## Backup file resolution

The CLI resolves the Reword backup in this order:

1. `--backup-path PATH` — if you pass an explicit local path, that wins.
2. `REWORD_BACKUP_PATH` env var — same idea, set once in your shell.
3. iCloud sync (macOS only) — reads from the Reword iCloud folder.
4. Google Drive via the [Drive MCP connector](https://docs.claude.com/en/docs/claude-code/mcp).

The first three work offline. The Drive fallback requires the Drive MCP server to be configured.

## Using via Claude Code

This repo ships a Claude Code skill (`skill/SKILL.md`). Inside Claude Code, just ask:

> build me a vocabulary for system design interview

Claude will confirm the topic with you, run the CLI, and show you a preview of the first rows of the generated CSV. See `skill/SKILL.md` for trigger phrases.

## Troubleshooting

**`error: ANTHROPIC_API_KEY environment variable is required`** — Export your Anthropic API key: `export ANTHROPIC_API_KEY=sk-ant-...`. The CLI uses it for word generation, IPA fallback (when CMU dict doesn't have the word), and example-sentence enrichment.

**`error: Drive MCP client is not available...`** — Either configure the Google Drive MCP connector in Claude Code, or download your Reword backup manually and pass it with `--backup-path ~/Downloads/reword_en.backup`. You can also set `REWORD_BACKUP_PATH` once in your shell.

**`error: backup file not found: ...`** — The path you passed to `--backup-path` doesn't exist. Check the path with `ls`.

**`error: source produced no words: ...`** — The PDF/EPUB was unreadable or yielded no extractable text. Try copying its contents into a plain `.txt` file and running again with that.

**`error: unsupported source type: .docx`** — Only PDF, EPUB, HTML, and plain text are supported. Convert the file or use topic mode.

**Output mentions a `-flagged.txt` file** — These are words the CLI couldn't fully transcribe or enrich. The CSV is still valid; just open the `.txt` file to see which words to add by hand or skip.

**`→ All candidate words already mastered. Nothing to import.`** — Every word the generator produced was already in your Reword history as mastered or active-long. Try a different topic, increase `--target-count`, or narrow the prompt to a more specific niche.

## Install

```bash
pip install -e .
python -m spacy download en_core_web_sm
```

spaCy's English model is used for verb detection (so the CLI knows to prefix verbs with `to `). It's a separate download (~50 MB).

A public PyPI release will follow once the tool is stable.

## Contributing

This is a personal tool published openly for transparency. Feedback and PRs welcome, but priorities are set by my own learning needs.

## License

MIT — see [LICENSE](LICENSE).
