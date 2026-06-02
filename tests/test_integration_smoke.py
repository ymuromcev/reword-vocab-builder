"""Integration smoke test for the full vocab pipeline (BL-13).

Exercises the deterministic pieces end-to-end without LLM or spaCy:

    raw words --to_prefix--> prefixed --dedup--> filtered --enrich (faked)
        --> rows --write_csv--> CSV on disk

The enrichment step is faked: we hand-build rows with canned IPA / RU /
example sentences so the CSV write surface is exercised without depending
on the live IPA dictionary or LLM. The spaCy POS tagger is replaced with
a tiny in-memory lookup via `verb_detector.set_nlp`.

This test runs against the documented module contracts:

- BL-02 / RFC-002: `backup_index` is a `dict[str, ClassifiedWord]` keyed by
  lowercased word (no `to ` prefix). We construct it directly here.
- BL-04 / RFC-004: `verb_detector.to_prefix(word)` is idempotent and only
  prefixes verbs; non-verbs pass through.
- BL-06 / RFC-006: `dedup(words, backup_index) -> tuple[list[dict],
  DedupReport]` and `dedup_only(words, backup_index) -> list[dict]`.
  Skips entries whose backup status is `mastered` (>= 60d) or
  `active-long` (>= 14d); keeps everything else. Matching is done on a
  normalized key (lowercase, strip, `to ` stripped). Input dicts carry at
  least a `"word"` key; output preserves the dicts of kept entries.
- BL-08 / RFC-013: `csv_writer.write_csv(rows, path)` produces a 7-column
  CSV: `en, ipa, ru, ex1_en, ex1_ru, ex2_en, ex2_ru`. Semicolon-separated,
  every field quoted, no header row.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass

import pytest

from reword_vocab import dedup as dedup_mod
from reword_vocab import verb_detector
from reword_vocab.csv_writer import write_csv


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class ClassifiedWord:
    """Local stand-in for backup_reader.ClassifiedWord.

    The dedup module only reads `.status` (and possibly `.interval_days`),
    so a duck-typed dataclass is sufficient for the smoke test.
    """

    word: str
    status: str
    interval_days: int


class _FakeToken:
    """Minimal spaCy-like token: exposes `.text`, `.pos_`, `.tag_`."""

    def __init__(self, text: str, pos: str, tag: str) -> None:
        self.text = text
        self.pos_ = pos
        self.tag_ = tag


class _FakeDoc(list):
    """spaCy-like Doc: an iterable of tokens."""


class _FakeNLP:
    """spaCy-like callable.

    Looks each whitespace-split token up in `pos_map`. Unknown tokens
    default to NOUN (NN) so we never accidentally tag a non-verb as a
    verb — keeps the test deterministic.
    """

    def __init__(self, pos_map: dict[str, str]) -> None:
        self._pos_map = pos_map

    def __call__(self, text: str) -> _FakeDoc:
        tokens: list[_FakeToken] = []
        for piece in text.split():
            pos = self._pos_map.get(piece.lower(), "NOUN")
            tag = "VB" if pos == "VERB" else "NN"
            tokens.append(_FakeToken(piece, pos, tag))
        return _FakeDoc(tokens)


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline_env():
    """Set up a deterministic environment for the pipeline.

    - Injects a fake POS tagger so spaCy / en_core_web_sm aren't needed.
    - Builds a synthetic `backup_index` with one mastered and one passive
      word.
    - Returns the raw generated word list plus a hand-built enrichment
      table the test uses to fake the enricher output.

    After the test, the injected nlp is cleared so module state doesn't
    leak into unrelated tests in the same session.
    """

    fake_nlp = _FakeNLP(
        {
            "leverage": "VERB",
            "align": "VERB",
            "iterate": "VERB",
            "dominate": "VERB",
            "stakeholder": "NOUN",
        }
    )
    verb_detector.set_nlp(fake_nlp)

    backup_index: dict[str, ClassifiedWord] = {
        "dominate": ClassifiedWord(word="dominate", status="mastered", interval_days=90),
        "leverage": ClassifiedWord(word="leverage", status="passive", interval_days=2),
    }

    raw_generated = [
        "leverage",
        "to align",
        "iterate",
        "dominate",
        "stakeholder",
    ]

    # Canned enrichment payload — keyed by the prefixed form so the test
    # can build CSV rows after dedup without invoking the live enricher.
    enrichment_table: dict[str, dict[str, str]] = {
        "to leverage": {
            "ipa": "/ˈlɛv.ər.ɪdʒ/",
            "ru": "использовать",
            "ex1_en": "We leverage the new tooling.",
            "ex1_ru": "Мы используем новый инструментарий.",
            "ex2_en": "She leveraged her network.",
            "ex2_ru": "Она использовала свои связи.",
        },
        "to align": {
            "ipa": "/əˈlaɪn/",
            "ru": "согласовать",
            "ex1_en": "Let's align on goals.",
            "ex1_ru": "Давайте согласуем цели.",
            "ex2_en": "The teams aligned quickly.",
            "ex2_ru": "Команды быстро согласовались.",
        },
        "to iterate": {
            "ipa": "/ˈɪt.ə.reɪt/",
            "ru": "итерировать",
            "ex1_en": "We iterate on the design.",
            "ex1_ru": "Мы итерируем по дизайну.",
            "ex2_en": "Iterate until it ships.",
            "ex2_ru": "Итерируй, пока не зарелизишь.",
        },
        "to dominate": {
            "ipa": "/ˈdɒm.ɪ.neɪt/",
            "ru": "доминировать",
            "ex1_en": "They dominate the market.",
            "ex1_ru": "Они доминируют на рынке.",
            "ex2_en": "Dominate the conversation.",
            "ex2_ru": "Доминируй в разговоре.",
        },
        "stakeholder": {
            "ipa": "/ˈsteɪkˌhoʊl.dər/",
            "ru": "стейкхолдер",
            "ex1_en": "Talk to every stakeholder.",
            "ex1_ru": "Поговори с каждым стейкхолдером.",
            "ex2_en": "Stakeholders signed off.",
            "ex2_ru": "Стейкхолдеры дали добро.",
        },
    }

    try:
        yield {
            "backup_index": backup_index,
            "raw_generated": raw_generated,
            "enrichment_table": enrichment_table,
        }
    finally:
        # Best-effort teardown: pass None so a re-init in another test sees
        # a clean slate. If the production module doesn't accept None it
        # will be a no-op next time anyone calls set_nlp.
        try:
            verb_detector.set_nlp(None)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


CSV_COLUMNS = ("en", "ipa", "ru", "ex1_en", "ex1_ru", "ex2_en", "ex2_ru")


def _prefix_all(words: list[str]) -> list[dict[str, str]]:
    """Apply `to_prefix` then wrap as dicts the way the real pipeline does.

    The pipeline shape downstream of verb detection is a list of dicts so
    `dedup` and the enricher can hang additional fields off the same
    object. Each dict carries at minimum a `"word"` key with the
    (possibly prefixed) English form.
    """
    return [{"word": verb_detector.to_prefix(w)} for w in words]


def _enrich(
    filtered: list[dict[str, str]],
    enrichment_table: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    """Stand-in for the LLM enricher: looks up canned fields by `en`."""
    rows: list[dict[str, str]] = []
    for entry in filtered:
        en = entry["word"]
        canned = enrichment_table[en]
        rows.append(
            {
                "word": en,
                "ipa": canned["ipa"],
                "ru": canned["ru"],
                "ex1_en": canned["ex1_en"],
                "ex1_ru": canned["ex1_ru"],
                "ex2_en": canned["ex2_en"],
                "ex2_ru": canned["ex2_ru"],
            }
        )
    return rows


def _read_csv(path) -> list[list[str]]:
    """Read the CSV back in the same dialect `write_csv` writes."""
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter=";", quotechar='"')
        return [row for row in reader]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pipeline_produces_expected_csv(tmp_path, pipeline_env):
    """End-to-end smoke: dedup drops mastered, CSV has all 7 columns."""
    backup_index = pipeline_env["backup_index"]
    raw_generated = pipeline_env["raw_generated"]
    enrichment_table = pipeline_env["enrichment_table"]

    prefixed = _prefix_all(raw_generated)
    filtered, report = dedup_mod.dedup(prefixed, backup_index)
    rows = _enrich(filtered, enrichment_table)

    out_path = tmp_path / "vocab.csv"
    write_csv(rows, str(out_path))

    on_disk = _read_csv(out_path)

    # BL-18: two items are in the backup ("dominate" mastered, "leverage"
    # passive) and both are dropped as duplicates -> 3 survive.
    assert len(on_disk) == len(raw_generated) - 2 == 3

    # Every row has exactly 7 populated columns.
    for csv_row in on_disk:
        assert len(csv_row) == 7
        for cell in csv_row:
            assert cell != ""

    # DedupReport tallies both backup drops by their status.
    assert report.reasons["mastered"] == 1
    assert report.reasons["passive"] == 1


def test_pipeline_drops_backup_words(tmp_path, pipeline_env):
    """Any word already in the backup is dropped, regardless of status."""
    backup_index = pipeline_env["backup_index"]
    raw_generated = pipeline_env["raw_generated"]
    enrichment_table = pipeline_env["enrichment_table"]

    prefixed = _prefix_all(raw_generated)
    filtered = dedup_mod.dedup_only(prefixed, backup_index)
    rows = _enrich(filtered, enrichment_table)

    out_path = tmp_path / "vocab.csv"
    write_csv(rows, str(out_path))

    on_disk = _read_csv(out_path)

    en_column = [row[0] for row in on_disk]
    # `dominate` (mastered) is dropped.
    assert "to dominate" not in en_column
    assert "dominate" not in en_column

    # BL-18: `leverage` is in the backup as `passive`, which now also counts
    # as a duplicate, so it must NOT appear.
    assert "to leverage" not in en_column
    assert "leverage" not in en_column


def test_pipeline_applies_to_prefix_only_to_verbs(tmp_path, pipeline_env):
    """Verbs carry the `to ` prefix; non-verbs do not."""
    backup_index = pipeline_env["backup_index"]
    raw_generated = pipeline_env["raw_generated"]
    enrichment_table = pipeline_env["enrichment_table"]

    prefixed = _prefix_all(raw_generated)
    filtered = dedup_mod.dedup_only(prefixed, backup_index)
    rows = _enrich(filtered, enrichment_table)

    out_path = tmp_path / "vocab.csv"
    write_csv(rows, str(out_path))

    on_disk = _read_csv(out_path)
    en_column = [row[0] for row in on_disk]

    # Verbs that survived dedup must be prefixed. (BL-18: `leverage` is a
    # backup duplicate and no longer survives, so it isn't checked here.)
    assert "to align" in en_column
    assert "to iterate" in en_column

    # `to align` was already prefixed in the input — `to_prefix` must be
    # idempotent (no double prefix).
    assert "to to align" not in en_column

    # The noun must NOT be prefixed.
    assert "stakeholder" in en_column
    assert "to stakeholder" not in en_column
