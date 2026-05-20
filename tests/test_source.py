"""Tests for src/generators/source.py (BL-08).

Uses a fake LLMClient — no real network calls. PDF fixtures are
synthesized at test-time with `reportlab` to keep the repo free of
copyrighted material.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.generators import source as source_mod
from src.generators.source import (
    UnsupportedSourceError,
    _chunk_text,
    _parse_json_array,
    extract,
    normalize_key,
)


FIXTURES = Path(__file__).parent / "fixtures" / "sources"


# ----- Fake LLM client -------------------------------------------------------


class FakeLLM:
    """Fake LLMClient that returns canned responses keyed by call index.

    If `responses` is shorter than the number of calls, the last response
    is reused (handy for "every chunk returns the same thing" tests).
    """

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[idx]


def _json_response(items: list[dict]) -> str:
    return json.dumps(items)


# ----- normalize_key + chunking ---------------------------------------------


def test_normalize_key_strips_to_prefix_and_lowercases():
    assert normalize_key("to leverage") == "leverage"
    assert normalize_key("  Leverage  ") == "leverage"
    assert normalize_key("ROADMAP") == "roadmap"


def test_chunk_text_returns_single_chunk_when_under_budget():
    text = "Short paragraph.\n\nAnother one."
    chunks = _chunk_text(text)
    assert len(chunks) == 1


def test_chunk_text_splits_on_paragraph_boundaries():
    # Force chunking by setting a tiny budget.
    text = "para one is here.\n\npara two is here.\n\npara three is here."
    chunks = _chunk_text(text, max_chars=20)
    assert len(chunks) >= 3
    for c in chunks:
        assert c.strip()


def test_chunk_text_handles_paragraph_larger_than_budget():
    text = "a" * 100
    chunks = _chunk_text(text, max_chars=30)
    assert len(chunks) == 4  # 30+30+30+10
    assert "".join(chunks) == text


def test_chunk_text_empty_input_returns_empty_list():
    assert _chunk_text("") == []
    assert _chunk_text("   \n\n   ") == []


# ----- JSON parsing tolerance ------------------------------------------------


def test_parse_json_array_handles_markdown_fence():
    raw = "```json\n[{\"word\": \"x\"}]\n```"
    assert _parse_json_array(raw) == [{"word": "x"}]


def test_parse_json_array_extracts_array_from_chatter():
    raw = "Sure! Here you go: [{\"word\": \"x\"}] hope that helps."
    assert _parse_json_array(raw) == [{"word": "x"}]


def test_parse_json_array_returns_empty_on_garbage():
    assert _parse_json_array("nope") == []


# ----- Text fixture ---------------------------------------------------------


def test_extract_from_txt_returns_grounded_items():
    items = [
        {
            "word": "leverage",
            "part_of_speech": "verb",
            "source_quote": (
                "During discovery, we leverage prototypes and rapid customer "
                "interviews to de-risk assumptions before writing any "
                "production code."
            ),
        },
        {
            "word": "roadmap",
            "part_of_speech": "noun",
            "source_quote": "Roadmaps should be treated as living artifacts.",
        },
    ]
    llm = FakeLLM([_json_response(items)])
    out = extract(FIXTURES / "sample.txt", "PM vocabulary", llm=llm)
    words = {row["word"] for row in out}
    assert "leverage" in words
    assert "roadmap" in words
    # context_note carries chunk index
    assert all(row["context_note"].startswith("chunk ") for row in out)


def test_hallucination_filter_drops_items_whose_quote_is_not_in_chunk():
    items = [
        {
            "word": "leverage",
            "part_of_speech": "verb",
            "source_quote": (
                "During discovery, we leverage prototypes and rapid customer "
                "interviews to de-risk assumptions before writing any "
                "production code."
            ),
        },
        {
            "word": "synergize",
            "part_of_speech": "verb",
            # This sentence is NOT in the fixture — must be dropped.
            "source_quote": "We synergize cross-functionally at scale.",
        },
    ]
    llm = FakeLLM([_json_response(items)])
    out = extract(FIXTURES / "sample.txt", "PM vocab", llm=llm)
    words = {row["word"] for row in out}
    assert "leverage" in words
    assert "synergize" not in words


# ----- HTML fixture ----------------------------------------------------------


def test_extract_from_html_strips_scripts_and_styles():
    items = [
        {
            "word": "cultivate",
            "part_of_speech": "verb",
            "source_quote": (
                "Great leaders cultivate clarity by distilling complex "
                "tradeoffs into decisions their teams can act on."
            ),
        }
    ]
    llm = FakeLLM([_json_response(items)])
    out = extract(FIXTURES / "sample.html", "leadership vocab", llm=llm)
    assert any(row["word"] == "cultivate" for row in out)
    # The script body must not have been passed to the LLM as text.
    _, user_msg = llm.calls[0]
    assert "console.log" not in user_msg


# ----- Chunking + dedup across chunks ---------------------------------------


def test_dedup_across_chunks_keeps_longest_quote():
    # Force two chunks by setting a small budget on a large input.
    text = ("alpha. " * 200) + "\n\n" + ("beta. " * 200)
    big = FIXTURES / "_big.txt"
    big.write_text(text, encoding="utf-8")
    try:
        # Mock chunker to a small budget by monkey-patching the constant
        # is awkward — instead drive dedup by giving the fake LLM two calls
        # with the SAME word but different quotes.
        short_quote = "alpha."
        long_quote = "alpha. alpha. alpha."
        responses = [
            _json_response(
                [
                    {
                        "word": "alpha",
                        "part_of_speech": "noun",
                        "source_quote": short_quote,
                    }
                ]
            ),
            _json_response(
                [
                    {
                        "word": "alpha",
                        "part_of_speech": "noun",
                        "source_quote": long_quote,
                    }
                ]
            ),
        ]
        llm = FakeLLM(responses)

        # Manually invoke the chunk-level helper twice to simulate two
        # chunks, then merge — keeps the test independent of chunk
        # heuristics.
        c1 = source_mod._extract_from_chunk(
            "alpha. " * 5, "x", llm, chunk_index=0
        )
        c2 = source_mod._extract_from_chunk(
            "alpha. alpha. alpha. " * 3, "x", llm, chunk_index=1
        )
        merged = source_mod._merge_items(c1 + c2)
        assert len(merged) == 1
        assert merged[0]["source_quote"] == long_quote
    finally:
        big.unlink(missing_ok=True)


def test_chunking_drives_multiple_llm_calls(monkeypatch):
    # Shrink the chunk budget so the fixture splits.
    monkeypatch.setattr(source_mod, "MAX_CHUNK_CHARS", 200)
    llm = FakeLLM([_json_response([])])
    extract(FIXTURES / "sample.txt", "PM vocab", llm=llm)
    assert len(llm.calls) >= 2


def test_to_prefix_dedup_across_chunks():
    """`leverage` and `to leverage` are the same word — keep one."""
    c1 = [
        {
            "word": "leverage",
            "part_of_speech": "verb",
            "source_quote": "We leverage prototypes.",
            "context_note": "chunk 1",
        }
    ]
    c2 = [
        {
            "word": "to leverage",
            "part_of_speech": "verb",
            "source_quote": "We leverage prototypes during discovery.",
            "context_note": "chunk 2",
        }
    ]
    merged = source_mod._merge_items(c1 + c2)
    assert len(merged) == 1


# ----- Unsupported sources --------------------------------------------------


def test_docx_raises_unsupported_source_error(tmp_path):
    fake = tmp_path / "doc.docx"
    fake.write_bytes(b"PK\x03\x04")  # fake zip header
    with pytest.raises(UnsupportedSourceError):
        extract(fake, "vocab", llm=FakeLLM([_json_response([])]))


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract(tmp_path / "nope.txt", "x", llm=FakeLLM([""]))


def test_empty_instruction_raises():
    with pytest.raises(ValueError):
        extract(FIXTURES / "sample.txt", "  ", llm=FakeLLM([""]))


def test_missing_llm_raises():
    with pytest.raises(ValueError):
        extract(FIXTURES / "sample.txt", "vocab")


# ----- PDF (synthesized at test time) ---------------------------------------


def _make_pdf(path: Path, text: str) -> None:
    reportlab = pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import letter  # noqa: WPS433
    from reportlab.pdfgen import canvas  # noqa: WPS433

    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - 72
    for line in text.splitlines():
        c.drawString(72, y, line)
        y -= 14
        if y < 72:
            c.showPage()
            y = height - 72
    c.save()


def test_extract_from_pdf(tmp_path):
    pytest.importorskip("reportlab")
    pytest.importorskip("pypdf")

    text = "We leverage discovery to de-risk assumptions before delivery."
    pdf = tmp_path / "tiny.pdf"
    _make_pdf(pdf, text)

    items = [
        {
            "word": "leverage",
            "part_of_speech": "verb",
            "source_quote": "leverage discovery",
        }
    ]
    llm = FakeLLM([_json_response(items)])
    out = extract(pdf, "PM vocab", llm=llm)
    assert any(row["word"] == "leverage" for row in out)
