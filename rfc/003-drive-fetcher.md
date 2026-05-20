---
id: RFC-003
bl: BL-03
title: Drive MCP fetcher for reword_en.backup
status: approved
date: 2026-05-19
---

## Goal

Resolve a fresh local path to `reword_en.backup`. The fetcher hides where
the file comes from (Drive MCP, iCloud sync folder, explicit env override).

## Public API

```python
from src.drive_mcp import fetch_latest_backup

path = fetch_latest_backup(ttl_hours: int = 6, force: bool = False) -> Path
```

## Resolution order

1. `REWORD_BACKUP_PATH` env var — if set, return as-is (no copy, no cache).
   Fast path for tests and power users.
2. iCloud fallback if file exists at
   `~/Library/Mobile Documents/iCloud~ru~poas~englishwords/Documents/reword_en.backup`
   — copy to cache only if cache is stale.
3. Google Drive via MCP — search for the file named `reword_en.backup`,
   download most-recently-modified copy.

Cache location: `~/.cache/reword-vocab-builder/reword_en.backup`.
TTL via `mtime` of cache file. `force=True` skips TTL check.

## Drive MCP integration

Drive MCP tool names depend on the connector. Implementation should:

- Search by exact filename `reword_en.backup` (no path required).
- If multiple matches, pick the one with latest `modifiedTime`.
- Download bytes, write atomically to cache (write to `.tmp`, then rename).

When MCP is unavailable in the runtime (e.g. CI), raise
`DriveUnavailableError` with a clear message pointing at
`REWORD_BACKUP_PATH`.

## Tests

- Env override path resolves immediately, no MCP call.
- iCloud path resolves when file is present (use `monkeypatch` to fake the
  iCloud location with a tmpdir).
- Drive path: mock MCP client, verify search → download → cache write.
- TTL: stale cache triggers re-fetch, fresh cache does not.

## Out of scope

- Upload / write back to Drive.
- OAuth flows (MCP handles auth).

## Risks / decisions

- **No tokens stored in repo.** All auth is delegated to the MCP server.
- **Atomic write** (`.tmp` + rename) so a partial download can't replace a
  good cache.
- **iCloud fallback** is opt-in implicit: only used if the file exists.
  Never look for iCloud paths on non-Mac platforms.
