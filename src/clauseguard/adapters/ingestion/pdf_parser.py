"""Adapter: native-PDF / plain-text document parser (Phase 1).

Extracts text from native (non-scanned) PDFs using ``pdfplumber`` when it is
installed, and falls back to treating the bytes as UTF-8 text otherwise so the
pipeline is runnable in minimal environments. Phase 2 adds OCR and
table-structure adapters behind the same :class:`DocumentParser` port.
"""

from __future__ import annotations

from clauseguard.exceptions import DocumentParseError
from clauseguard.logging_config import get_logger
from clauseguard.ports.ingestion import ParsedDocument

logger = get_logger(__name__)


class NativePdfParser:
    """Parse native PDFs (or plain-text bytes) into text."""

    def parse(self, content: bytes, *, source_ref: str) -> ParsedDocument:
        """Parse ``content`` into a :class:`ParsedDocument`.

        Args:
            content: Raw document bytes.
            source_ref: Source label for citations.

        Returns:
            The parsed document.

        Raises:
            DocumentParseError: If the bytes cannot be decoded or parsed.
        """
        try:
            import pdfplumber  # type: ignore
        except ImportError:
            logger.warning(
                "pdfplumber not installed; treating input as UTF-8 text",
                extra={"source_ref": source_ref},
            )
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise DocumentParseError(
                    f"Cannot decode {source_ref} as text without pdfplumber"
                ) from exc
            return ParsedDocument(text=text, page_count=1, source_ref=source_ref)

        try:
            import io

            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
            return ParsedDocument(
                text="\n".join(pages),
                page_count=len(pages),
                source_ref=source_ref,
            )
        except Exception as exc:  # noqa: BLE001 - wrap as domain error
            raise DocumentParseError(
                f"Failed to parse PDF {source_ref}: {exc}"
            ) from exc
