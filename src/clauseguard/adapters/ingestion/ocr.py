"""Adapter: OCR document parser (for scanned / image-only PDFs).

Native (text-layer) PDFs are handled by
:class:`~clauseguard.adapters.ingestion.pdf_parser.NativePdfParser`. Scanned
invoices are just images with no text layer, so they need Optical Character
Recognition. This module renders each PDF page to an image, applies light
preprocessing, and runs Tesseract over it, producing a :class:`ParsedDocument`
whose ``text`` is the OCR output.

OCR yields text but **no reliable table geometry**, so ``tables`` is empty — the
downstream extraction cascade will skip the geometry tier and rely on the text
tier and (for the messy output typical of OCR) the LLM tier.

On OCR quality
--------------
OCR is a *lossy* front-end: on real scans it can misread glyphs (a well-known
example is the ₹ symbol reading as ``2``/``7``/``%``). Two safe levers help and
are exposed here — higher rasterisation **DPI** and greyscale + autocontrast
**preprocessing** — plus a configurable page-segmentation mode. What is
deliberately *not* done is any numeric "cleanup" of the OCR output: you cannot
reliably distinguish a misread ``21000`` from a genuine ``21000``, so correcting
digits blind would corrupt good data. OCR accuracy is an ingestion-side concern;
the extractor's job is to faithfully structure whatever text it receives.

Decoupling & testability
------------------------
The image-to-text step is injected behind :class:`OcrBackend`, so the parser
logic is unit-testable with a trivial fake, and the heavy env-specific
dependencies (``pytesseract`` + ``pdf2image`` + the system ``tesseract`` /
``poppler`` binaries) are imported lazily by the default backend only. The
preprocessing step is a pure function, testable on its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from clauseguard.exceptions import DocumentParseError
from clauseguard.logging_config import get_logger
from clauseguard.ports.ingestion import ParsedDocument

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

logger = get_logger(__name__)


def preprocess_for_ocr(image: Image) -> Image:
    """Greyscale + autocontrast an image to improve OCR legibility.

    Conservative on purpose: greyscale and contrast normalisation reliably help
    Tesseract without the risk of aggressive binarisation erasing thin glyphs.

    Args:
        image: The rendered page image.

    Returns:
        A preprocessed image.
    """
    from PIL import ImageOps  # noqa: PLC0415 - Pillow only needed for OCR

    return ImageOps.autocontrast(image.convert("L"))


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
        psm: Tesseract page-segmentation mode (6 = a uniform block of text,
            a good default for invoice bodies).
        preprocess: Whether to greyscale + autocontrast pages before OCR.
    """

    def __init__(
        self,
        *,
        dpi: int = 400,
        lang: str = "eng",
        psm: int = 6,
        preprocess: bool = True,
    ) -> None:
        self._dpi = dpi
        self._lang = lang
        self._psm = psm
        self._preprocess = preprocess

    def image_pdf_to_text(self, content: bytes) -> str:
        """Render pages to images, preprocess, and OCR them.

        Raises:
            DocumentParseError: If the OCR toolchain is unavailable or fails.
        """
        try:
            import pytesseract  # type: ignore[import-not-found,import-untyped]  # noqa: PLC0415
            from pdf2image import (  # type: ignore[import-not-found,import-untyped]  # noqa: PLC0415
                convert_from_bytes,
            )
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise DocumentParseError(
                "OCR needs 'pytesseract' and 'pdf2image'; install the 'ocr' extra"
            ) from exc

        config = f"--psm {self._psm}"
        try:
            images = convert_from_bytes(content, dpi=self._dpi)
            pages = []
            for img in images:
                prepared = preprocess_for_ocr(img) if self._preprocess else img
                pages.append(
                    pytesseract.image_to_string(
                        prepared, lang=self._lang, config=config
                    )
                )
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
