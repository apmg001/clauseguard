"""Tests for OCR ingestion and the native->OCR fallback parser.

All offline: a fake OCR backend stands in for Tesseract, so the parser and
fallback-routing logic are verified without the OCR toolchain or a real scan.
"""

from __future__ import annotations

from clauseguard.adapters.ingestion.fallback import FallbackDocumentParser
from clauseguard.adapters.ingestion.ocr import OcrBackend, OcrDocumentParser
from clauseguard.ports.ingestion import DocumentParser, ParsedDocument


class FakeOcrBackend:
    """Return canned OCR text (no Tesseract/poppler needed)."""

    def __init__(self, text: str) -> None:
        self._text = text

    def image_pdf_to_text(self, content: bytes) -> str:
        return self._text


class StubParser:
    """A DocumentParser returning a fixed ParsedDocument (for the primary path)."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    def parse(self, content: bytes, *, source_ref: str) -> ParsedDocument:
        self.calls += 1
        return ParsedDocument(
            text=self._text, page_count=1, source_ref=source_ref, tables=[]
        )


def test_ocr_parser_returns_backend_text() -> None:
    backend: OcrBackend = FakeOcrBackend("INVOICE\nItem A 100")
    doc = OcrDocumentParser(backend).parse(b"%PDF-fake", source_ref="scan.pdf")
    assert "INVOICE" in doc.text
    assert doc.tables == []
    assert doc.source_ref == "scan.pdf"


def test_fallback_uses_primary_when_text_is_present() -> None:
    primary = StubParser("plenty of real digital text here, well over threshold")
    ocr = StubParser("OCR SHOULD NOT RUN")
    parser: DocumentParser = FallbackDocumentParser(primary=primary, ocr=ocr)
    doc = parser.parse(b"%PDF-digital", source_ref="digital.pdf")
    assert "digital text" in doc.text
    assert ocr.calls == 0  # OCR never invoked for a digital PDF


def test_fallback_escalates_to_ocr_when_primary_empty() -> None:
    primary = StubParser("")  # scanned PDF: no text layer
    ocr = OcrDocumentParser(FakeOcrBackend("scanned invoice text via OCR"))
    parser = FallbackDocumentParser(primary=primary, ocr=ocr)
    doc = parser.parse(b"%PDF-scan", source_ref="scan.pdf")
    assert "via OCR" in doc.text


def test_preprocess_returns_greyscale_image() -> None:
    from PIL import Image

    from clauseguard.adapters.ingestion.ocr import preprocess_for_ocr

    colour = Image.new("RGB", (12, 12), (10, 200, 60))
    out = preprocess_for_ocr(colour)
    assert out.mode == "L"          # greyscaled
    assert out.size == (12, 12)     # dimensions preserved
