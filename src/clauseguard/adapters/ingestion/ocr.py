"""Adapter: OCR document parser (for scanned / image-only PDFs).

Native (text-layer) PDFs are handled by
:class:`~clauseguard.adapters.ingestion.pdf_parser.NativePdfParser`. Scanned
invoices are just images with no text layer, so they need Optical Character
Recognition. This module renders each PDF page to an image and runs Tesseract
over it, producing a :class:`ParsedDocument` whose ``text`` is the OCR output.

OCR yields text but **no reliable table geometry**, so ``tables`` is empty — the
downstream extraction cascade will skip the geometry tier and rely on the text
tier and (for the messy output typical of OCR) the LLM tier.

Decoupling & testability
------------------------
The image-to-text step is injected behind :class:`OcrBackend`, so the parser
logic is unit-testable with a trivial fake and the heavy, environment-specific
dependencies (``pytesseract`` + ``pdf2image``, and the system ``tesseract`` and
``poppler`` binaries) are imported lazily by the default backend only.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from clauseguard.exceptions import DocumentParseError
from clauseguard.logging_config import get_logger
from clauseguard.ports.ingestion import ParsedDocument

logger = get_logger(__name__)


@runtime_checkable
class OcrBackend(Protocol):
    """Turns raw document bytes (an image-PDF) into text via OCR."""

    def image_pdf_to_text(self, content: bytes) -> str:
        """Return the OCR-extracted text for a PDF's rendered pages.

        Raises:
            DocumentParseError: If OCR cannot be performed.
        """
        ...


class TesseractOcrBackend:
    """Default :class:`OcrBackend`: ``pdf2image`` (poppler) + ``pytesseract``.

    Args:
        dpi: Rasterisation resolution; higher is slower but more accurate.
        lang: Tesseract language(s), e.g. ``"eng"``.
    """

    def __init__(self, *, dpi: int = 300, lang: str = "eng") -> None:
        self._dpi = dpi
        self._lang = lang

    def image_pdf_to_text(self, content: bytes) -> str:
        """Render pages to images and OCR them.

        Raises:
            DocumentParseError: If the OCR toolchain is unavailable or fails.
        """
        try:
            import pytesseract  # type: ignore[import-not-found]  # noqa: PLC0415
            from pdf2image import (  # type: ignore[import-not-found]  # noqa: PLC0415
                convert_from_bytes,
            )
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise DocumentParseError(
                "OCR needs 'pytesseract' and 'pdf2image'; install the 'ocr' extra"
            ) from exc

        try:
            images = convert_from_bytes(content, dpi=self._dpi)
            pages = [
                pytesseract.image_to_string(img, lang=self._lang)
                for img in images
            ]
        except Exception as exc:  # noqa: BLE001 - wrap toolchain errors as domain
            raise DocumentParseError(
                f"OCR failed (is the tesseract/poppler binary installed?): {exc}"
            ) from exc
        return "\n".join(pages)


class OcrDocumentParser:
    """Parse a (scanned) PDF into text via an :class:`OcrBackend`.

    Implements the :class:`~clauseguard.ports.ingestion.DocumentParser` port.

    Args:
        backend: The OCR backend to use (defaults to Tesseract).
    """

    def __init__(self, backend: OcrBackend | None = None) -> None:
        self._backend = backend or TesseractOcrBackend()

    def parse(self, content: bytes, *, source_ref: str) -> ParsedDocument:
        """OCR ``content`` into a text-only :class:`ParsedDocument`.

        Args:
            content: Raw PDF bytes.
            source_ref: Source label for citations.

        Returns:
            A parsed document with OCR text and no recovered tables.

        Raises:
            DocumentParseError: If OCR fails.
        """
        text = self._backend.image_pdf_to_text(content)
        logger.info(
            "OCR parse complete",
            extra={"source_ref": source_ref, "text_chars": len(text)},
        )
        return ParsedDocument(
            text=text, page_count=1, source_ref=source_ref, tables=[]
        )
