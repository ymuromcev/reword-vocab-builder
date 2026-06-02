"""CLI entrypoint for reword-vocab. Two modes: topic, source.

Glues every layer-1/2 module into one shippable command. See
``rfc/011-cli.md`` for the user-facing shape and exit-code table.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys
from pathlib import Path
from typing import Sequence

from reword_vocab import backup_reader, csv_writer, dedup, drive_mcp, enricher, ipa, verb_detector
from reword_vocab.generators import source as source_mod
from reword_vocab.generators import topic as topic_mod


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reword-vocab",
        description="Generate Reword-ready English vocabulary CSV.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    topic_p = subparsers.add_parser(
        "topic", help="Generate from a topic prompt"
    )
    topic_p.add_argument("prompt", help="Topic prompt (e.g. \"PM vocabulary\")")
    topic_p.add_argument("--target-count", type=int, default=200)
    topic_p.add_argument("--output", type=Path, default=None)
    topic_p.add_argument("--backup-path", type=Path, default=None)

    source_p = subparsers.add_parser(
        "source", help="Extract from a PDF/EPUB/HTML/text file"
    )
    source_p.add_argument("file", type=Path)
    source_p.add_argument("--instruction", required=True)
    source_p.add_argument("--output", type=Path, default=None)
    source_p.add_argument("--backup-path", type=Path, default=None)

    return parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _UserError(Exception):
    """Raised for user-facing failures; mapped to exit code 2."""


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, limit: int = 64) -> str:
    """Lowercase, replace non-alnum runs with a single dash, trim."""
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    if len(s) > limit:
        s = s[:limit].rstrip("-")
    return s or "vocab"


def _topic_slug(prompt: str) -> str:
    return _slugify(prompt)


def _source_slug(file_path: Path, instruction: str) -> str:
    base = file_path.stem
    instr = _slugify(instruction, limit=32)
    combined = f"{_slugify(base, limit=32)}-{instr}" if instr else _slugify(base)
    return _slugify(combined)


_OUTPUT_DIR_ENV = "REWORD_VOCAB_OUTPUT_DIR"
_OUTPUT_DIR_DEFAULT = Path.home() / "Documents" / "reword-vocab-output"


def _resolve_output_dir() -> Path:
    """Where new CSVs are written.

    Resolution: ``$REWORD_VOCAB_OUTPUT_DIR`` if set, else
    ``~/Documents/reword-vocab-output/``. The installer creates the
    default dir; callers ``mkdir(parents=True, exist_ok=True)`` before
    writing so a fresh shell still works.
    """
    override = os.environ.get(_OUTPUT_DIR_ENV)
    return Path(override).expanduser() if override else _OUTPUT_DIR_DEFAULT


def _output_path(explicit: Path | None, slug: str) -> Path:
    if explicit is not None:
        return explicit
    today = _dt.date.today().isoformat()
    return _resolve_output_dir() / f"{today}-{slug}.csv"


def _resolve_backup(backup_path: Path | None) -> Path:
    """Return a local backup file path or raise ``_UserError``."""
    if backup_path is not None:
        if not backup_path.exists():
            raise _UserError(f"backup file not found: {backup_path}")
        return backup_path
    print("→ Fetching backup via Drive MCP…")
    try:
        return drive_mcp.fetch_latest_backup()
    except drive_mcp.DriveUnavailableError as exc:
        raise _UserError(str(exc)) from exc


def _build_llm() -> topic_mod.LLMClient:
    """Build the default Anthropic-backed LLM client; raise on missing key."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise _UserError("ANTHROPIC_API_KEY environment variable is required")
    return topic_mod._build_default_client()


def _ipa_callable(llm: topic_mod.LLMClient):
    """Adapt the LLMClient (``.complete``) to the callable ipa expects."""

    def call(prompt: str) -> str:
        return llm.complete("", prompt)

    return call


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


_CSV_COLUMNS = csv_writer.COLUMNS  # ("word","ipa","ru","ex1_en",...)


def _run_pipeline(
    words: list[dict],
    index: dict,
    llm: topic_mod.LLMClient,
    output_path: Path,
) -> int:
    kept, report = dedup.dedup(words, index)
    print(f"→ Dedup: {report.kept} kept / {report.skipped} skipped")
    if not kept:
        print("→ All candidate words are already in your Reword library. Nothing to import.")
        return 0

    # IPA transcription
    flagged: list[tuple[str, str]] = []
    cmu_hits = 0
    llm_hits = 0
    surviving: list[dict] = []
    ipa_llm = _ipa_callable(llm)
    for word_obj in kept:
        ipa_value, was_flagged = ipa.transcribe(word_obj["word"], llm=ipa_llm)
        if ipa_value is None:
            flagged.append((word_obj["word"], "ipa-failed"))
            continue
        if was_flagged:
            llm_hits += 1
        else:
            cmu_hits += 1
        word_obj["ipa"] = ipa_value
        surviving.append(word_obj)
    print(
        f"→ IPA: {len(surviving)}/{len(kept)} "
        f"(CMU {cmu_hits} · LLM {llm_hits})"
    )

    if not surviving:
        print("→ No words could be transcribed. Nothing to import.")
        _write_flagged(output_path, flagged)
        return 0

    # Enrichment
    try:
        enriched = enricher.enrich_many(surviving, llm=llm)
    except enricher.EnrichmentError as exc:
        raise _UserError(f"enrichment failed: {exc}") from exc
    print(f"→ Enrich: {len(enriched)}/{len(surviving)}")

    # Verb prefix
    verbs = 0
    for word_obj in enriched:
        prefixed = verb_detector.to_prefix(word_obj["word"])
        if prefixed != word_obj["word"]:
            verbs += 1
            word_obj["word"] = prefixed
    print(f"→ Verb prefix applied to {verbs} words")

    # CSV write — keep only the columns Reword expects.
    rows = [{k: row[k] for k in _CSV_COLUMNS} for row in enriched]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    csv_writer.write_csv(rows, output_path)
    print(f"✓ {output_path} ({len(rows)} rows)")

    _write_flagged(output_path, flagged)
    return 0


def _write_flagged(output_path: Path, flagged: list[tuple[str, str]]) -> None:
    if not flagged:
        return
    flagged_path = output_path.with_name(f"{output_path.stem}-flagged.txt")
    flagged_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{word}\t{reason}" for word, reason in flagged]
    flagged_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"⚠ {flagged_path} ({len(flagged)} flagged)")


# ---------------------------------------------------------------------------
# Subcommand runners
# ---------------------------------------------------------------------------


def _run_topic(args: argparse.Namespace) -> int:
    if not args.prompt.strip():
        raise _UserError("prompt must be a non-empty string")
    if args.target_count <= 0:
        raise _UserError("--target-count must be positive")

    backup_file = _resolve_backup(args.backup_path)
    index = backup_reader.read_backup(str(backup_file))
    print(f"→ Backup: {len(index)} words classified")

    llm = _build_llm()
    print(f"→ Generating \"{args.prompt}\" (target={args.target_count})…")
    words = topic_mod.generate(
        args.prompt, target_count=args.target_count, llm=llm
    )
    print(f"→ Generated {len(words)} candidate words")

    output = _output_path(args.output, _topic_slug(args.prompt))
    return _run_pipeline(words, index, llm, output)


def _run_source(args: argparse.Namespace) -> int:
    if not args.file.exists():
        raise _UserError(f"source file not found: {args.file}")
    if not args.instruction.strip():
        raise _UserError("--instruction must be a non-empty string")

    backup_file = _resolve_backup(args.backup_path)
    index = backup_reader.read_backup(str(backup_file))
    print(f"→ Backup: {len(index)} words classified")

    llm = _build_llm()
    print(f"→ Extracting from {args.file.name}…")
    try:
        words = source_mod.extract(args.file, args.instruction, llm=llm)
    except source_mod.UnsupportedSourceError as exc:
        raise _UserError(str(exc)) from exc
    except source_mod.EmptySourceError as exc:
        raise _UserError(f"source produced no words: {exc}") from exc
    print(f"→ Extracted {len(words)} candidate words")

    output = _output_path(args.output, _source_slug(args.file, args.instruction))
    return _run_pipeline(words, index, llm, output)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "topic":
            return _run_topic(args)
        if args.command == "source":
            return _run_source(args)
    except _UserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Should never reach here — argparse enforces required subcommand.
    parser.error("no command specified")
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
