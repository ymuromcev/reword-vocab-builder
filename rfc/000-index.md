---
title: RFC index
---

# RFC index

| RFC  | BL    | Title                              | Status      |
|------|-------|------------------------------------|-------------|
| 002  | BL-02 | SQLite backup reader               | implemented |
| 003  | BL-03 | Drive MCP fetcher                  | implemented |
| 004  | BL-04 | Verb detector + `to ` prefix       | implemented |
| 006  | BL-06 | Dedup against backup               | approved    |
| 007  | BL-07 | Topic-mode generator               | implemented |
| 008  | BL-08 | Source-mode ingestor               | implemented |
| 009  | BL-09 | IPA US transcription               | implemented |
| 010  | BL-10 | Example sentences + RU enricher    | implemented |
| 011  | BL-11 | CLI entrypoint                     | approved    |
| 013  | BL-13 | Integration smoke test             | implemented |
| 014  | BL-16 | In-chat-first skill architecture   | implemented |

BL-05 (CSV writer) is XS tier — no RFC needed; design lives in
`private/backlog/BL-05.md`.

## Conventions

- File: `NNN-short-slug.md`. NNN matches the BL number where 1:1.
- Frontmatter: `id`, `bl`, `title`, `status`, `date`.
- Status flow: `draft → approved → implemented → archived`.
- One RFC per BL for M/L tier work.
