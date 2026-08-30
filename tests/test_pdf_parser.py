"""Tests for NativePdfParser input-type detection.

The parser must treat plain text as text (not attempt PDF parsing) and only use
pdfplumber for real PDF bytes — the bug the end-to-end demo surfaced.
"""

from __future__ import annotations

import pytest

from clauseguard.adapters.ingestion.pdf_parser import NativePdfParser
from clauseguard.exceptions import DocumentParseError


def test_plain_text_is_parsed_as_text() -> None:
    parser = NativePdfParser()
    doc = parser.parse(b"Invoice-ID: INV-1\nVendor: Acme", source_ref="x.txt")
    assert "INV-1" in doc.text
    assert doc.page_count == 1
    assert doc.source_ref == "x.txt"


def test_non_utf8_non_pdf_raises() -> None:
    parser = NativePdfParser()
    with pytest.raises(DocumentParseError):
        parser.parse(b"\xff\xfe\x00bad", source_ref="x.bin")


def test_pdf_magic_but_corrupt_raises() -> None:
    parser = NativePdfParser()
    with pytest.raises(DocumentParseError):
        parser.parse(b"%PDF-1.4 not really a pdf", source_ref="x.pdf")
