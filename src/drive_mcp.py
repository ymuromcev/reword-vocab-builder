"""Fetch latest ``reword_en.backup`` via Drive MCP, with cache + fallbacks.

Public entry point: :func:`fetch_latest_backup`.

Resolution order (see ``rfc/003-drive-fetcher.md``):

1. ``REWORD_BACKUP_PATH`` env var — explicit override, returned as-is.
2. iCloud fallback (macOS only) — copy into cache if cache is stale.
3. Google Drive via an injected MCP client — search + download, atomic
   write to cache.

The Drive call is behind a :class:`DriveMCPClient` Protocol so unit tests
can inject a fake client. No real network calls happen inside this
module — the caller wires up a concrete MCP client at the boundary.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


CACHE_DIR = Path.home() / ".cache" / "reword-vocab-builder"
CACHE_FILE = CACHE_DIR / "reword_en.backup"

ICLOUD_PATH = (
    Path.home()
    / "Library"
    / "Mobile Documents"
    / "iCloud~ru~poas~englishwords"
    / "Documents"
    / "reword_en.backup"
)

BACKUP_FILENAME = "reword_en.backup"
DEFAULT_TTL_HOURS = 6


class DriveUnavailableError(RuntimeError):
    """Raised when no Drive MCP client is configured and no fallback works.

    The message points users at the ``REWORD_BACKUP_PATH`` env var so they
    can unblock themselves without setting up MCP.
    """


@dataclass(frozen=True)
class DriveFile:
    """Minimal metadata returned by Drive MCP searches."""

    id: str
    name: str
    modified_time: float  # epoch seconds; higher = newer


class DriveMCPClient(Protocol):
    """Abstraction over the Google Drive MCP connector.

    Two methods, one search + one download. Implementations live outside
    this module (the real MCP wrapper, or test fakes).
    """

    def search(self, filename: str) -> Sequence[DriveFile]:  # pragma: no cover - protocol
        ...

    def download(self, file_id: str, dest: Path) -> None:  # pragma: no cover - protocol
        ...


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _cache_is_fresh(cache_path: Path, ttl_hours: int) -> bool:
    if not cache_path.exists():
        return False
    if ttl_hours <= 0:
        return False
    age_seconds = time.time() - cache_path.stat().st_mtime
    return age_seconds < ttl_hours * 3600


def _atomic_write_copy(src: Path, dest: Path) -> None:
    """Copy ``src`` to ``dest`` atomically (write to ``.tmp`` then rename)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)


def _atomic_download(client: DriveMCPClient, file_id: str, dest: Path) -> None:
    """Download via MCP into a ``.tmp`` sibling, then rename onto ``dest``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        client.download(file_id, tmp)
        os.replace(tmp, dest)
    except BaseException:
        # Don't leave a partial .tmp lying around.
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def fetch_latest_backup(
    ttl_hours: int = DEFAULT_TTL_HOURS,
    force: bool = False,
    *,
    client: DriveMCPClient | None = None,
    cache_path: Path | None = None,
    icloud_path: Path | None = None,
) -> Path:
    """Return a local :class:`Path` to a fresh ``reword_en.backup``.

    :param ttl_hours: max age of the cache before it's considered stale.
    :param force: if True, ignore cache freshness and re-fetch.
    :param client: optional Drive MCP client. Injected for tests; in
        production the caller wires the real connector.
    :param cache_path: override the cache file location (test hook).
    :param icloud_path: override the iCloud sync path (test hook).

    Raises :class:`DriveUnavailableError` when Drive MCP is the only
    option but no client was provided.
    """
    cache = cache_path if cache_path is not None else CACHE_FILE
    icloud = icloud_path if icloud_path is not None else ICLOUD_PATH

    # 1. Env override — fast path, no copy, no cache.
    env_override = os.environ.get("REWORD_BACKUP_PATH")
    if env_override:
        return Path(env_override)

    fresh = (not force) and _cache_is_fresh(cache, ttl_hours)

    # 2. iCloud fallback (macOS only). Refresh cache if stale.
    if _is_macos() and icloud.exists():
        if not fresh:
            _atomic_write_copy(icloud, cache)
        return cache

    # 3. Drive MCP. If cache is still fresh, skip the MCP roundtrip.
    if fresh:
        return cache

    if client is None:
        raise DriveUnavailableError(
            "Drive MCP client is not available. Set REWORD_BACKUP_PATH to a "
            "local copy of reword_en.backup, or run in an environment where "
            "the Google Drive MCP connector is configured."
        )

    matches = list(client.search(BACKUP_FILENAME))
    if not matches:
        raise DriveUnavailableError(
            f"No file named {BACKUP_FILENAME!r} found on Drive."
        )
    latest = max(matches, key=lambda f: f.modified_time)
    _atomic_download(client, latest.id, cache)
    return cache
