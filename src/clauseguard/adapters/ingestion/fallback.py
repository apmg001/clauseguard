"""Adapter: fallback document parser (native → OCR).

Real inboxes mix digital and scanned PDFs. This parser tries the fast, exact
primary parser (native text-layer extraction) first; if it recovers too little
text — the signature of a scanned/image-only PDF — it falls back to the OCR
parser. This keeps the common (digital) case cheap while still handling scans,
and it means callers depend on one :class:`DocumentParser`, unaware of which
path answered.
"""

from __future__ import annotations

from clauseguard.exceptions import DocumentParseError
from clauseguard.logging_config import get_logger
from clauseguard.ports.ingestion import DocumentParser, ParsedDocument

logger = get_logger(__name__)

_DEFAULT_MIN_TEXT_CHARS = 20


class FallbackDocumentParser:
    """Parse with a primary parser; fall back to OCR when little text is found.

    Implements the :class:`~clauseguard.ports.ingestion.DocumentParser` port.

    Args:
        primary: The fast primary parser (native text-layer extraction).
        ocr: The OCR parser used when the primary recovers too little text.
        min_text_chars: Below this many non-whitespace characters, the document
            is treated as scanned and routed to OCR.
    """

    def __init__(
        self,
        *,
        primary: DocumentParser,
        ocr: DocumentParser,
        min_text_chars: int = _DEFAULT_MIN_TEXT_CHARS,
    ) -> None:
        self._primary = primary
        self._ocr = ocr
        self._min_text_chars = min_text_chars

    def parse(self, content: bytes, *, source_ref: str) -> ParsedDocument:
        """Parse via the primary parser, escalating to OCR for scanned PDFs.

        Args:
            content: Raw document bytes.
            source_ref: Source label for citations.

        Returns:
            The primary result when it has enough text; otherwise the OCR result.

        Raises:
            DocumentParseError: If the primary fails for a non-recoverable reason
                and OCR cannot rescue it.
        """
        try:
            primary = self._primary.parse(content, source_ref=source_ref)
        except DocumentParseError:
            logger.info(
                "Primary parse errored; trying OCR",
                extra={"source_ref": source_ref},
            )
            return self._ocr.parse(content, source_ref=source_ref)

        if len(primary.text.strip()) >= self._min_text_chars:
            return primary

        logger.info(
            "Primary recovered little text; escalating to OCR",
            extra={
                "source_ref": source_ref,
                "primary_chars": len(primary.text.strip()),
            },
        )
        ocr_result = self._ocr.parse(content, source_ref=source_ref)
        # Keep OCR only if it actually did better; otherwise return the primary.
        if len(ocr_result.text.strip()) > len(primary.text.strip()):
            return ocr_result
        return primary
