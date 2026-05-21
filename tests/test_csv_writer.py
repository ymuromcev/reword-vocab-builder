"""Tests for src/csv_writer.py.

Covers:
- 3-row round trip (write then read with the same dialect)
- Validation: empty value and missing key
- Byte-level fixture comparison (semicolons + embedded quotes in values)
- UTF-8 re-read with Cyrillic content
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from reword_vocab.csv_writer import COLUMNS, write_csv


def _row(word, ipa, ru, ex1_en, ex1_ru, ex2_en, ex2_ru):
    return {
        "word": word,
        "ipa": ipa,
        "ru": ru,
        "ex1_en": ex1_en,
        "ex1_ru": ex1_ru,
        "ex2_en": ex2_en,
        "ex2_ru": ex2_ru,
    }


def test_round_trip_three_rows(tmp_path: Path) -> None:
    rows = [
        _row("to leverage", "[ˈlevərɪdʒ]", "использовать",
             "We leverage data.", "Мы используем данные.",
             "Leverage your skills.", "Используй свои навыки."),
        _row("trade-off", "[ˈtreɪd ɒf]", "компромисс",
             "It is a trade-off.", "Это компромисс.",
             "Every choice has a trade-off.", "В каждом выборе есть компромисс."),
        _row("to align", "[əˈlaɪn]", "согласовывать",
             "Align the team.", "Согласуй команду.",
             "Goals align with vision.", "Цели согласуются с видением."),
    ]
    path = tmp_path / "out.csv"
    write_csv(rows, path)

    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter=";", quotechar='"')
        read_back = [dict(zip(COLUMNS, r)) for r in reader]

    assert read_back == rows


def test_empty_value_raises(tmp_path: Path) -> None:
    rows = [
        _row("ok", "[ok]", "ок", "a", "а", "b", "б"),
        _row("to align", "[əˈlaɪn]", "   ",  # whitespace-only
             "Align it.", "Согласуй.", "It aligns.", "Согласуется."),
    ]
    with pytest.raises(ValueError) as exc:
        write_csv(rows, tmp_path / "out.csv")
    msg = str(exc.value)
    assert "row 1" in msg
    assert "'ru'" in msg


def test_missing_key_raises(tmp_path: Path) -> None:
    bad = {
        "word": "to align",
        "ipa": "[əˈlaɪn]",
        "ru": "согласовывать",
        "ex1_en": "Align the team.",
        "ex1_ru": "Согласуй команду.",
        "ex2_en": "Goals align.",
        # ex2_ru missing
    }
    with pytest.raises(ValueError) as exc:
        write_csv([bad], tmp_path / "out.csv")
    msg = str(exc.value)
    assert "row 0" in msg
    assert "'ex2_ru'" in msg


def test_byte_level_fixture(tmp_path: Path) -> None:
    """Hand-craft expected bytes including semicolons and embedded quotes.

    csv.QUOTE_ALL wraps every field in double quotes; embedded `"`
    is escaped by doubling to `""`. Semicolons inside fields stay
    literal because the field is already quoted.
    """
    rows = [
        _row(
            "to quote",
            "[kwoʊt]",
            'цитировать',
            'He said "hello".',
            'Он сказал "привет".',
            'Quote; cite.',
            'Цитируй; ссылайся.',
        ),
        _row(
            "trade-off",
            "[ˈtreɪd ɒf]",
            "компромисс",
            "A; B.",
            "А; Б.",
            'She said "ok".',
            'Она сказала "ок".',
        ),
    ]
    path = tmp_path / "out.csv"
    write_csv(rows, path)

    expected = (
        '"to quote";"[kwoʊt]";"цитировать";'
        '"He said ""hello"".";"Он сказал ""привет"".";'
        '"Quote; cite.";"Цитируй; ссылайся."\n'
        '"trade-off";"[ˈtreɪd ɒf]";"компромисс";'
        '"A; B.";"А; Б.";'
        '"She said ""ok"".";"Она сказала ""ок""."\n'
    ).encode("utf-8")

    assert path.read_bytes() == expected


def test_utf8_reread(tmp_path: Path) -> None:
    rows = [
        _row("to embrace", "[ɪmˈbreɪs]", "принимать",
             "Embrace change.", "Принимай изменения.",
             "She embraces it.", "Она это принимает."),
    ]
    path = tmp_path / "out.csv"
    write_csv(rows, path)

    text = path.read_text(encoding="utf-8")
    assert "принимать" in text
    assert "Принимай изменения." in text
