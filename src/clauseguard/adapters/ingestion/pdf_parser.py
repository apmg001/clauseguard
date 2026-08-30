"""Adapter: native-PDF / plain-text document parser.

Extracts text from native (non-scanned) PDFs using ``pdfplumber``, and treats
non-PDF input as UTF-8 text. The input type is decided by the PDF magic number
(``%PDF-``) rather than by whether a library happens to be installed, so the
parser behaves the same in every environment and never tries to parse plain
text as a PDF.

Scanned/image PDFs (no embedded text layer) are out of scope here; an OCR
adapter behind the same :class:`DocumentParser` port handles those in a later
phase.
"""

from __future__ import annotations

import io

from clauseguard.exceptions import DocumentParseError
from clauseguard.logging_config import get_logger
from clauseguard.ports.ingestion import ParsedDocument

logger = get_logger(__name__)

_PDF_MAGIC = b"%PDF-"


class NativePdfParser:
    """Parse native PDFs (or plain-text bytes) into text."""

    def parse(self, content: bytes, *, source_ref: str) -> ParsedDocument:
        """Parse ``content`` into a :class:`ParsedDocument`.

        The parser inspects the leading bytes: input beginning with the PDF
        magic number is parsed with ``pdfplumber``; anything else is decoded as
        UTF-8 text. This makes ``.txt`` and PDF inputs both first-class and
        avoids feeding plain text to a PDF engine.

        Args:
            content: Raw document bytes.
            source_ref: Source label for citations.

        Returns:
            The parsed document.

        Raises:
            DocumentParseError: If a PDF cannot be read, ``pdfplumber`` is
                required but unavailable, or non-PDF bytes are not valid UTF-8.
        """
        if content.startswith(_PDF_MAGIC):
            return self._parse_pdf(content, source_ref=source_ref)
        return self._parse_text(content, source_ref=source_ref)

    @staticmethod
    def _parse_pdf(content: bytes, *, source_ref: str) -> ParsedDocument:
        """Extract text from a native PDF using ``pdfplumber``."""
        try:
            import pdfplumber  # type: ignore
        except ImportError as exc:
            raise DocumentParseError(
                f"{source_ref} looks like a PDF but 'pdfplumber' is not "
                f"installed; install the 'ingestion' extra to parse PDFs"
            ) from exc

        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
            return ParsedDocument(
                text="\n".join(pages),
                page_count=len(pages),
                source_ref=source_ref,
            )
        except Exception as exc:  # noqa: BLE001 - wrap library errors as domain
            raise DocumentParseError(
                f"Failed to parse PDF {source_ref}: {exc}"
            ) from exc

    @staticmethod
    def _parse_text(content: bytes, *, source_ref: str) -> ParsedDocument:
        """Decode non-PDF bytes as UTF-8 text."""
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentParseError(
                f"{source_ref} is neither a PDF nor valid UTF-8 text"
            ) from exc
        logger.debug("Parsed as plain text", extra={"source_ref": source_ref})
        return ParsedDocument(text=text, page_count=1, source_ref=source_ref)