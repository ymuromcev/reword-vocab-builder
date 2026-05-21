#!/usr/bin/env python3
"""Freeze the CMU Pronouncing Dictionary to a JSON file.

The installer (``install-skill.sh``) runs this to produce
``cmudict_frozen.json`` next to the skill's other helpers, so the
in-chat path can transcribe IPA without ``pip install cmudict``.

Usage:
    python3 scripts/freeze_cmudict.py <output.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import cmudict
except ImportError:
    sys.stderr.write(
        "error: cmudict is not installed. Run `pip install cmudict` once "
        "before invoking this freezer.\n"
    )
    sys.exit(1)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write(f"usage: {argv[0]} <output.json>\n")
        return 2
    out = Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    data = cmudict.dict()
    out.write_text(json.dumps(data, separators=(",", ":")))
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"✓ Wrote {out} ({len(data):,} entries, {size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
