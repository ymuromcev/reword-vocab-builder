"""Tests for reword_vocab.cli — argparse shape + two end-to-end smokes.

All external boundaries (Drive, backup SQLite, LLM, IPA, enricher) are
monkeypatched so the tests run hermetically. Verifies that the wiring
produces a Reword-shaped CSV.
"""

from __future__ import annotations

import csv as _csv
from pathlib import Path

import pytest

from reword_vocab import backup_reader, csv_writer
from reword_vocab import cli as cli_mod
from reword_vocab.backup_reader import ClassifiedWord


# ---------------------------------------------------------------------------
# Slug + argparse unit tests
# ---------------------------------------------------------------------------


def test_slugify_basic():
    assert cli_mod._slugify("PM interview vocabulary") == "pm-interview-vocabulary"


def test_slugify_unicode_dropped():
    assert cli_mod._slugify("café résumé") == "caf-r-sum"


def test_slugify_truncates():
    long = "a" * 200
    assert len(cli_mod._slugify(long)) <= 64


def test_slugify_empty_falls_back():
    assert cli_mod._slugify("***") == "vocab"


def test_output_dir_default(monkeypatch):
    monkeypatch.delenv(cli_mod._OUTPUT_DIR_ENV, raising=False)
    assert cli_mod._resolve_output_dir() == cli_mod._OUTPUT_DIR_DEFAULT


def test_output_dir_env_override(monkeypatch, tmp_path):
    target = tmp_path / "custom-out"
    monkeypatch.setenv(cli_mod._OUTPUT_DIR_ENV, str(target))
    assert cli_mod._resolve_output_dir() == target


def test_output_path_uses_resolved_dir(monkeypatch, tmp_path):
    monkeypatch.setenv(cli_mod._OUTPUT_DIR_ENV, str(tmp_path))
    out = cli_mod._output_path(None, "pm-vocab")
    assert out.parent == tmp_path
    assert out.name.endswith("-pm-vocab.csv")


def test_parser_topic_minimal():
    parser = cli_mod._build_parser()
    args = parser.parse_args(["topic", "PM vocabulary"])
    assert args.command == "topic"
    assert args.prompt == "PM vocabulary"
    assert args.target_count == 200
    assert args.output is None


def test_parser_source_requires_instruction():
    parser = cli_mod._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["source", "/tmp/foo.pdf"])


def test_parser_source_with_instruction():
    parser = cli_mod._build_parser()
    args = parser.parse_args(
        ["source", "/tmp/foo.pdf", "--instruction", "PM"]
    )
    assert args.command == "source"
    assert args.instruction == "PM"


def test_parser_target_count_custom():
    parser = cli_mod._build_parser()
    args = parser.parse_args(["topic", "x", "--target-count", "50"])
    assert args.target_count == 50


# ---------------------------------------------------------------------------
# Smoke tests — full pipeline with every boundary mocked
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Stand-in LLMClient. Tests don't exercise its methods directly —
    every call site is monkeypatched."""

    def complete(self, system: str, user: str) -> str:  # pragma: no cover
        raise AssertionError("LLM should not be invoked in this test")


def _fake_index() -> dict[str, ClassifiedWord]:
    return {
        "dominate": ClassifiedWord(
            word="dominate", status="mastered", interval_days=120.0
        ),
    }


def _fake_words() -> list[dict]:
    # leverage → new, kept. dominate → mastered, skipped.
    # iterate → new, kept (verb → "to iterate"). foundation → noun, kept.
    return [
        {"word": "leverage", "part_of_speech": "verb", "context_note": ""},
        {"word": "dominate", "part_of_speech": "verb", "context_note": ""},
        {"word": "iterate", "part_of_speech": "verb", "context_note": ""},
        {"word": "foundation", "part_of_speech": "noun", "context_note": ""},
    ]


def _fake_enriched(words: list[dict]) -> list[dict]:
    out = []
    for w in words:
        enriched = dict(w)
        enriched.update(
            ru=f"{w['word']}-ru",
            ex1_en=f"Use {w['word']} every day.",
            ex1_ru=f"пример с {w['word']}",
            ex2_en=f"Another {w['word']} sentence.",
            ex2_ru=f"ещё пример {w['word']}",
        )
        out.append(enriched)
    return out


def _setup_pipeline_mocks(monkeypatch, tmp_path):
    """Patch every external module called by cli."""
    fake_backup = tmp_path / "fake.backup"
    fake_backup.touch()

    monkeypatch.setattr(
        cli_mod.drive_mcp, "fetch_latest_backup", lambda: fake_backup
    )
    monkeypatch.setattr(
        cli_mod.backup_reader, "read_backup",
        lambda path: _fake_index(),
    )
    monkeypatch.setattr(cli_mod, "_build_llm", lambda: _FakeLLM())

    # IPA: return a deterministic transcription, never flagged.
    def fake_ipa(word, *, llm):
        return (f"[{word}]", False)

    monkeypatch.setattr(cli_mod.ipa, "transcribe", fake_ipa)

    # Enricher: just augment with canned fields.
    def fake_enrich_many(words, *, llm):
        return _fake_enriched(words)

    monkeypatch.setattr(cli_mod.enricher, "enrich_many", fake_enrich_many)

    # Verb detection: minimal fake nlp tags verbs we care about.
    class _Tok:
        def __init__(self, text, tag):
            self.text = text
            self.tag_ = tag

    class _Doc:
        def __init__(self, tokens):
            self._tokens = tokens

        def __iter__(self):
            return iter(self._tokens)

    class _FakeNLP:
        TAGS = {"leverage": "VB", "iterate": "VB", "dominate": "VB",
                "foundation": "NN"}

        def __call__(self, text):
            return _Doc([_Tok(text, self.TAGS.get(text.lower(), "NN"))])

    cli_mod.verb_detector.set_nlp(_FakeNLP())


# ---------------------------------------------------------------------------


def test_topic_smoke_writes_csv(monkeypatch, tmp_path):
    _setup_pipeline_mocks(monkeypatch, tmp_path)

    monkeypatch.setattr(
        cli_mod.topic_mod, "generate",
        lambda prompt, target_count, llm: _fake_words(),
    )

    output = tmp_path / "out.csv"
    exit_code = cli_mod.main(
        ["topic", "PM interview vocabulary", "--output", str(output)]
    )
    assert exit_code == 0
    assert output.exists()

    with output.open(encoding="utf-8") as fh:
        rows = list(_csv.reader(fh, delimiter=";", quotechar='"'))
    # 4 input words - 1 mastered (dominate) = 3 rows
    assert len(rows) == 3
    # Each row has 7 columns
    for row in rows:
        assert len(row) == 7
    # First column has the verb prefix where applicable
    first_col = {row[0] for row in rows}
    assert "to leverage" in first_col
    assert "to iterate" in first_col
    assert "foundation" in first_col  # noun → no prefix
    assert "to dominate" not in first_col  # filtered by dedup


def test_topic_dedup_filters_all(monkeypatch, tmp_path):
    """When every candidate is mastered, exit 0 and write no CSV."""
    _setup_pipeline_mocks(monkeypatch, tmp_path)

    monkeypatch.setattr(
        cli_mod.topic_mod, "generate",
        lambda prompt, target_count, llm: [
            {"word": "dominate", "part_of_speech": "verb", "context_note": ""}
        ],
    )

    output = tmp_path / "out.csv"
    exit_code = cli_mod.main(
        ["topic", "PM stuff", "--output", str(output)]
    )
    assert exit_code == 0
    assert not output.exists()


def test_source_smoke_writes_csv(monkeypatch, tmp_path):
    _setup_pipeline_mocks(monkeypatch, tmp_path)

    source_file = tmp_path / "inspired.pdf"
    source_file.write_bytes(b"%PDF-1.4 fake")  # exists is enough

    monkeypatch.setattr(
        cli_mod.source_mod, "extract",
        lambda path, instruction, llm: _fake_words(),
    )

    output = tmp_path / "out.csv"
    exit_code = cli_mod.main(
        [
            "source", str(source_file),
            "--instruction", "PM vocabulary",
            "--output", str(output),
        ]
    )
    assert exit_code == 0
    assert output.exists()


def test_source_missing_file_exits_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli_mod, "_build_llm", lambda: _FakeLLM())
    exit_code = cli_mod.main(
        ["source", str(tmp_path / "missing.pdf"), "--instruction", "x"]
    )
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "source file not found" in err


def test_missing_api_key_exits_2(monkeypatch, tmp_path, capsys):
    """No ANTHROPIC_API_KEY → exit 2 with a clear message."""
    fake_backup = tmp_path / "fake.backup"
    fake_backup.touch()

    monkeypatch.setattr(
        cli_mod.drive_mcp, "fetch_latest_backup", lambda: fake_backup
    )
    monkeypatch.setattr(
        cli_mod.backup_reader, "read_backup", lambda path: {}
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    exit_code = cli_mod.main(["topic", "x"])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err


def test_backup_path_missing_file_exits_2(monkeypatch, tmp_path, capsys):
    exit_code = cli_mod.main(
        ["topic", "x", "--backup-path", str(tmp_path / "nope.backup")]
    )
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "backup file not found" in err


def test_drive_unavailable_exits_2(monkeypatch, tmp_path, capsys):
    def raise_unavailable():
        raise cli_mod.drive_mcp.DriveUnavailableError("no drive")

    monkeypatch.setattr(
        cli_mod.drive_mcp, "fetch_latest_backup", raise_unavailable
    )
    exit_code = cli_mod.main(["topic", "x"])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "no drive" in err


def test_flagged_file_written_on_ipa_failure(monkeypatch, tmp_path):
    """A word whose IPA returns None is dropped + recorded in flagged.txt."""
    _setup_pipeline_mocks(monkeypatch, tmp_path)

    def fake_ipa_one_fails(word, *, llm):
        if word == "iterate":
            return (None, True)
        return (f"[{word}]", False)

    monkeypatch.setattr(cli_mod.ipa, "transcribe", fake_ipa_one_fails)
    monkeypatch.setattr(
        cli_mod.topic_mod, "generate",
        lambda prompt, target_count, llm: _fake_words(),
    )

    output = tmp_path / "out.csv"
    exit_code = cli_mod.main(
        ["topic", "PM", "--output", str(output)]
    )
    assert exit_code == 0
    assert output.exists()

    flagged_path = output.with_name(output.stem + "-flagged.txt")
    assert flagged_path.exists()
    assert "iterate" in flagged_path.read_text()
