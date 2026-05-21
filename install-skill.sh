#!/usr/bin/env bash
# Install the reword-vocab skill into Claude's skill library.
#
# After this runs, any Claude Desktop / Claude Code chat in any project
# can trigger "build vocab for X" without git clone / pip install /
# ANTHROPIC_API_KEY. See RFC 014 in this repo.
#
# Idempotent: re-running overwrites the installed copy with the
# current repo state.

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
TARGET="${HOME}/.claude/skills/reword-vocab"
LIB="${TARGET}/lib"
OUTPUT_DIR="${HOME}/Documents/reword-vocab-output"
FROZEN_DICT="${LIB}/cmudict_frozen.json"

echo "→ Installing reword-vocab skill from ${REPO}"
echo "→ Target: ${TARGET}"

# 1. Lay out target dirs.
mkdir -p "${LIB}/generators"
mkdir -p "${OUTPUT_DIR}"

# 2. Copy SKILL.md (chat-time instructions for Claude).
cp "${REPO}/skill/SKILL.md" "${TARGET}/SKILL.md"

# 3. Copy pure-Python helpers. Only the ones the in-chat path uses
#    — LLM-calling parts (enricher, topic generator) stay in the repo
#    for the CLI / headless path, not the skill bundle.
HELPERS=(
  "backup_reader.py"
  "csv_writer.py"
  "dedup.py"
  "ipa.py"
  "verb_detector.py"
  "drive_mcp.py"
)
for f in "${HELPERS[@]}"; do
  cp "${REPO}/reword_vocab/${f}" "${LIB}/${f}"
done

# 4. Copy generators/source.py (pure file-parsing helpers — no LLM).
cp "${REPO}/reword_vocab/generators/__init__.py" "${LIB}/generators/__init__.py"
cp "${REPO}/reword_vocab/generators/source.py" "${LIB}/generators/source.py"

# 5. Rewrite intra-package imports so the bundle imports from itself,
#    not from a (possibly absent) ``reword_vocab`` install on sys.path.
#    Helpers currently do ``from reword_vocab.X import Y``; replace
#    those with relative imports that work when ``lib/`` is added to
#    sys.path by the in-chat harness.
python3 - "${LIB}" <<'PY'
import re, sys
from pathlib import Path

lib = Path(sys.argv[1])
patterns = [
    (re.compile(r"\bfrom reword_vocab\.generators "), "from generators "),
    (re.compile(r"\bfrom reword_vocab\.generators\."), "from generators."),
    (re.compile(r"\bfrom reword_vocab import "), "from . import "),
    (re.compile(r"\bfrom reword_vocab\."), "from "),
    (re.compile(r"\bimport reword_vocab\b"), "import sys  # noqa"),
]
for f in lib.rglob("*.py"):
    txt = f.read_text()
    new = txt
    for pat, repl in patterns:
        new = pat.sub(repl, new)
    if new != txt:
        f.write_text(new)
PY

# 6. Freeze the CMU dict so the in-chat path can transcribe IPA
#    without pip-installing cmudict. If cmudict isn't on the path
#    (rare), skip — the LLM fallback still works in chat.
if python3 -c "import cmudict" 2>/dev/null; then
  python3 "${REPO}/scripts/freeze_cmudict.py" "${FROZEN_DICT}"
else
  echo "→ Skipping CMU dict freeze (cmudict not importable). The"
  echo "  in-chat path will rely on Claude's IPA generation only."
fi

echo "✓ Installed skill into ${TARGET}"
echo "✓ Output dir: ${OUTPUT_DIR}"
echo ""
echo "Usage: open any Claude Desktop / Claude Code chat and say"
echo "       \"build vocab for <topic>\"."
