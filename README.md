# reword-vocab-builder

Generate Reword-ready English vocabulary CSVs from any topic or source file, deduplicated against your existing learning history.

[Reword](https://reword.app) is an Android/iOS flashcard app for English vocabulary with SM2-style spaced repetition. This tool builds import-ready CSVs in Reword's native 7-column format.

## What it does

Two modes:

**Topic mode** — describe what you want vocabulary for, get a CSV.

```bash
reword-vocab topic "PM interview vocabulary"
reword-vocab topic "fintech and payments terminology"
```

**Source mode** — give it a book, article, or transcript, get vocabulary extracted from that source.

```bash
reword-vocab source ~/Documents/inspired-by-cagan.pdf --instruction "product management vocabulary I should learn"
reword-vocab source ~/Downloads/article.txt --instruction "business English I don't know yet"
```

Both modes dedupe against your existing Reword backup (fetched from Google Drive) so you don't relearn words you already know.

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

The tool reads your Reword backup (SQLite file) from Google Drive and skips words you already know well:

| State | Definition | Action |
|---|---|---|
| mastered | review interval at least 60 days | skip |
| active-long | review interval at least 14 days | skip |
| active short-term | review interval under 14 days | keep |
| passive | seen but not actively reviewed | keep |
| seen-only | dictionary entry, never studied | keep |

## Install

Not yet shipped. Track [BL-15](private/backlog/BL-15.md) for the first public release.

```bash
pip install reword-vocab-builder  # placeholder
```

## Contributing

This is a personal tool published openly for transparency. Feedback and PRs welcome, but priorities are set by my own learning needs.

## License

MIT — see [LICENSE](LICENSE).
