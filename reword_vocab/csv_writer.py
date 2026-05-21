"""Write Reword 7-column CSV (semicolon-separated, all quoted, no header).

Reword's importer is strict about CSV shape:
- Exactly 7 columns per row, in fixed order
- Semicolon delimiter, double-quote quoting on every field
- No header row
- LF line terminator, UTF-8 encoding

Any deviation (missing field, empty value, stray header) breaks import,
so this module validates aggressively and raises ValueError rather than
silently writing a bad file.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping

# Column order is part of Reword's contract — do not reorder.
COLUMNS: tuple[str, ...] = (
    "word",
    "ipa",
    "ru",
    "ex1_en",
    "ex1_ru",
    "ex2_en",
    "ex2_ru",
)


def _validate_row(index: int, row: Mapping[str, str]) -> None:
    for key in COLUMNS:
        if key not in row:
            raise ValueError(
                f"row {index}: missing key {key!r}"
            )
        value = row[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"row {index}: empty value for key {key!r}"
            )


def write_csv(rows: Iterable[Mapping[str, str]], path: str | Path) -> None:
    """Write rows to a Reword-format CSV file.

    Args:
        rows: iterable of dicts; each must contain all keys in COLUMNS,
            none of them empty or whitespace-only.
        path: destination file path. Parent dirs are NOT auto-created.

    Raises:
        ValueError: on any missing key or empty/whitespace value, with the
            offending row index and key in the message.
    """
    materialized = list(rows)
    for i, row in enumerate(materialized):
        _validate_row(i, row)

    out_path = Path(path)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(
            fh,
            delimiter=";",
            quotechar='"',
            quoting=csv.QUOTE_ALL,
            lineterminator="\n",
        )
        for row in materialized:
            writer.writerow([row[key] for key in COLUMNS])
