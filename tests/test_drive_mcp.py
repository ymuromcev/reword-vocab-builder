"""Unit tests for ``reword_vocab.drive_mcp``.

All Drive interaction is faked via the injected client. No real network.
iCloud-specific test is skipped on non-macOS platforms.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Sequence

import pytest

from reword_vocab.drive_mcp import (
    DEFAULT_TTL_HOURS,
    DriveFile,
    DriveUnavailableError,
    fetch_latest_backup,
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


@dataclass
class FakeDriveClient:
    """Records calls and serves canned matches / download bytes."""

    matches: Sequence[DriveFile] = ()
    payload: bytes = b"FAKE BACKUP BYTES"
    search_calls: List[str] = field(default_factory=list)
    download_calls: List[tuple[str, Path]] = field(default_factory=list)

    def search(self, filename: str) -> Sequence[DriveFile]:
        self.search_calls.append(filename)
        return self.matches

    def download(self, file_id: str, dest: Path) -> None:
        self.download_calls.append((file_id, Path(dest)))
        Path(dest).write_bytes(self.payload)


@pytest.fixture
def clean_env(monkeypatch):
    """Ensure REWORD_BACKUP_PATH never leaks in from the host shell."""
    monkeypatch.delenv("REWORD_BACKUP_PATH", raising=False)


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    return tmp_path / "cache" / "reword_en.backup"


# --------------------------------------------------------------------------- #
# 1. Env override fast path
# --------------------------------------------------------------------------- #


def test_env_override_returns_path_without_touching_mcp(
    monkeypatch, tmp_path, cache_path
):
    override = tmp_path / "user_supplied.backup"
    override.write_bytes(b"x")
    monkeypatch.setenv("REWORD_BACKUP_PATH", str(override))

    client = FakeDriveClient()
    result = fetch_latest_backup(
        client=client,
        cache_path=cache_path,
        icloud_path=tmp_path / "no_icloud_here",
    )

    assert result == override
    assert client.search_calls == []
    assert client.download_calls == []
    assert not cache_path.exists()


# --------------------------------------------------------------------------- #
# 2. iCloud fallback (macOS only)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(sys.platform != "darwin", reason="iCloud path is macOS only")
def test_icloud_fallback_copies_into_cache(clean_env, tmp_path, cache_path):
    icloud = tmp_path / "icloud" / "reword_en.backup"
    icloud.parent.mkdir(parents=True)
    icloud.write_bytes(b"icloud-bytes")

    client = FakeDriveClient()
    result = fetch_latest_backup(
        client=client,
        cache_path=cache_path,
        icloud_path=icloud,
    )

    assert result == cache_path
    assert cache_path.read_bytes() == b"icloud-bytes"
    assert client.search_calls == []  # MCP not consulted


def test_icloud_fallback_skipped_on_non_darwin(
    monkeypatch, clean_env, tmp_path, cache_path
):
    """Even if a path that looks like iCloud exists, non-mac platforms ignore it."""
    monkeypatch.setattr("reword_vocab.drive_mcp.sys.platform", "linux")

    fake_icloud = tmp_path / "fake_icloud" / "reword_en.backup"
    fake_icloud.parent.mkdir(parents=True)
    fake_icloud.write_bytes(b"should-be-ignored")

    client = FakeDriveClient(
        matches=[DriveFile(id="abc", name="reword_en.backup", modified_time=10.0)],
        payload=b"from-drive",
    )

    result = fetch_latest_backup(
        client=client,
        cache_path=cache_path,
        icloud_path=fake_icloud,
    )

    assert result == cache_path
    assert cache_path.read_bytes() == b"from-drive"
    assert client.search_calls == ["reword_en.backup"]


# --------------------------------------------------------------------------- #
# 3. Drive MCP path
# --------------------------------------------------------------------------- #


def test_drive_search_picks_latest_and_writes_cache(
    monkeypatch, clean_env, tmp_path, cache_path
):
    # Force non-mac so we go straight to Drive.
    monkeypatch.setattr("reword_vocab.drive_mcp.sys.platform", "linux")

    client = FakeDriveClient(
        matches=[
            DriveFile(id="old", name="reword_en.backup", modified_time=1.0),
            DriveFile(id="new", name="reword_en.backup", modified_time=999.0),
            DriveFile(id="mid", name="reword_en.backup", modified_time=42.0),
        ],
        payload=b"latest-payload",
    )

    result = fetch_latest_backup(
        client=client,
        cache_path=cache_path,
        icloud_path=tmp_path / "no_icloud",
    )

    assert result == cache_path
    assert cache_path.read_bytes() == b"latest-payload"
    assert client.search_calls == ["reword_en.backup"]
    # Downloaded file id should be the newest one.
    assert [fid for fid, _ in client.download_calls] == ["new"]
    # Atomic .tmp must be gone after the rename.
    assert not cache_path.with_suffix(cache_path.suffix + ".tmp").exists()


def test_drive_unavailable_when_no_client(monkeypatch, clean_env, tmp_path, cache_path):
    monkeypatch.setattr("reword_vocab.drive_mcp.sys.platform", "linux")

    with pytest.raises(DriveUnavailableError) as excinfo:
        fetch_latest_backup(
            client=None,
            cache_path=cache_path,
            icloud_path=tmp_path / "no_icloud",
        )
    assert "REWORD_BACKUP_PATH" in str(excinfo.value)


def test_drive_unavailable_when_search_empty(monkeypatch, clean_env, tmp_path, cache_path):
    monkeypatch.setattr("reword_vocab.drive_mcp.sys.platform", "linux")

    client = FakeDriveClient(matches=[])
    with pytest.raises(DriveUnavailableError):
        fetch_latest_backup(
            client=client,
            cache_path=cache_path,
            icloud_path=tmp_path / "no_icloud",
        )


# --------------------------------------------------------------------------- #
# 4. TTL behaviour
# --------------------------------------------------------------------------- #


def test_fresh_cache_skips_mcp(monkeypatch, clean_env, tmp_path, cache_path):
    monkeypatch.setattr("reword_vocab.drive_mcp.sys.platform", "linux")

    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"cached-bytes")
    # mtime = now → definitely fresh under default TTL
    now = time.time()
    import os as _os
    _os.utime(cache_path, (now, now))

    client = FakeDriveClient(
        matches=[DriveFile(id="x", name="reword_en.backup", modified_time=1.0)],
        payload=b"should-not-be-written",
    )

    result = fetch_latest_backup(
        ttl_hours=DEFAULT_TTL_HOURS,
        client=client,
        cache_path=cache_path,
        icloud_path=tmp_path / "no_icloud",
    )

    assert result == cache_path
    assert cache_path.read_bytes() == b"cached-bytes"
    assert client.search_calls == []
    assert client.download_calls == []


def test_stale_cache_triggers_refetch(monkeypatch, clean_env, tmp_path, cache_path):
    monkeypatch.setattr("reword_vocab.drive_mcp.sys.platform", "linux")

    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"old-bytes")
    # Backdate mtime to 1 day ago.
    import os as _os
    old = time.time() - 24 * 3600
    _os.utime(cache_path, (old, old))

    client = FakeDriveClient(
        matches=[DriveFile(id="x", name="reword_en.backup", modified_time=100.0)],
        payload=b"new-bytes",
    )

    result = fetch_latest_backup(
        ttl_hours=6,
        client=client,
        cache_path=cache_path,
        icloud_path=tmp_path / "no_icloud",
    )

    assert result == cache_path
    assert cache_path.read_bytes() == b"new-bytes"
    assert client.search_calls == ["reword_en.backup"]


def test_force_bypasses_fresh_cache(
    monkeypatch, clean_env, tmp_path, cache_path
):
    monkeypatch.setattr("reword_vocab.drive_mcp.sys.platform", "linux")

    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"old-bytes")

    client = FakeDriveClient(
        matches=[DriveFile(id="x", name="reword_en.backup", modified_time=100.0)],
        payload=b"forced-bytes",
    )

    result = fetch_latest_backup(
        force=True,
        client=client,
        cache_path=cache_path,
        icloud_path=tmp_path / "no_icloud",
    )

    assert result == cache_path
    assert cache_path.read_bytes() == b"forced-bytes"
    assert client.download_calls  # forced re-fetch happened
