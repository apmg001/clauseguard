"""Adapter: native-PDF / plain-text document parser.

Extracts both flattened text *and* recovered table structure from native
(text-layer) PDFs using ``pdfplumber``; treats non-PDF input as UTF-8 text. The
input type is decided by the PDF magic number (``%PDF-``), so the parser behaves
identically in every environment and never feeds plain text to a PDF engine.

The recovered ``tables`` are what make layout-aware extraction possible: they
are reconstructed from the page's ruling lines / word alignment, not from
guessing at whitespace in the flattened text.

Scanned/image PDFs (no embedded text layer) are out of scope here; an OCR
adapter behind the same :class:`DocumentParser` port handles those later.
"""

from __future__ import annotations

import io

from clauseguard.exceptions import DocumentParseError
from clauseguard.logging_config import get_logger
from clauseguard.ports.ingestion import ParsedDocument

logger = get_logger(__name__)

_PDF_MAGIC = b"%PDF-"


class NativePdfParser:
    """Parse native PDFs (or plain-text bytes) into text and tables."""

    def parse(self, content: bytes, *, source_ref: str) -> ParsedDocument:
        """Parse ``content`` into a :class:`ParsedDocument`.

        Args:
            content: Raw document bytes.
            source_ref: Source label for citations.

        Returns:
            The parsed document (text + recovered tables).

        Raises:
            DocumentParseError: If a PDF cannot be read, ``pdfplumber`` is
                required but unavailable, or non-PDF bytes are not valid UTF-8.
        """
        if content.startswith(_PDF_MAGIC):
            return self._parse_pdf(content, source_ref=source_ref)
        return self._parse_text(content, source_ref=source_ref)

    @staticmethod
    def _parse_pdf(content: bytes, *, source_ref: str) -> ParsedDocument:
        """Extract text and tables from a native PDF using ``pdfplumber``."""
        try:
            import pdfplumber  # type: ignore
        except ImportError as exc:
            raise DocumentParseError(
                f"{source_ref} looks like a PDF but 'pdfplumber' is not "
                f"installed; install the 'ingestion' extra to parse PDFs"
            ) from exc

        try:
            text_parts: list[str] = []
            tables: list[list[list[str]]] = []
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages:
                    text_parts.append(page.extract_text() or "")
                    for raw in page.extract_tables():
                        tables.append(
                            [[(cell or "").strip() for cell in row] for row in raw]
                        )
                page_count = len(pdf.pages)
            return ParsedDocument(
                text="\n".join(text_parts),
                page_count=page_count,
                source_ref=source_ref,
                tables=tables,
            )
        except Exception as exc:  # noqa: BLE001 - wrap library errors as domain
            raise DocumentParseError(
                f"Failed to parse PDF {source_ref}: {exc}"
            ) from exc

    @staticmethod
    def _parse_text(content: bytes, *, source_ref: str) -> ParsedDocument:
        """Decode non-PDF bytes as UTF-8 text (no tables)."""
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentParseError(
                f"{source_ref} is neither a PDF nor valid UTF-8 text"
            ) from exc
        logger.debug("Parsed as plain text", extra={"source_ref": source_ref})
        return ParsedDocument(
            text=text, page_count=1, source_ref=source_ref, tables=[]
        )
