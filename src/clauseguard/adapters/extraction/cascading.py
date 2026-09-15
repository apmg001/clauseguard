"""Adapter: cascading invoice extractor (tiered fallback).

Unifies the extraction tiers (layout-aware → rule-based text → optional LLM)
behind the single :class:`~clauseguard.ports.extraction.InvoiceExtractor` port
using a Chain-of-Responsibility fallback: each extractor is tried in order and
the first success wins. A document with a real PDF table is handled by the
layout tier; a delimited-text document falls through to the text tier; a chaotic
layout can fall through to the LLM tier (when configured).

This is what lets a single caller (the API, a service) depend on one extractor
while every tier remains independently testable and swappable — and it gives the
layout/LLM extractors real callers rather than being reachable only from tests.
"""

from __future__ import annotations

from collections.abc import Sequence

from clauseguard.domain.models import Invoice
from clauseguard.exceptions import InvoiceExtractionError
from clauseguard.logging_config import get_logger
from clauseguard.ports.extraction import InvoiceExtractor
from clauseguard.ports.ingestion import ParsedDocument

logger = get_logger(__name__)


class CascadingInvoiceExtractor:
    """Try each extractor in order; return the first successful extraction.

    Implements the :class:`~clauseguard.ports.extraction.InvoiceExtractor` port.

    Args:
        extractors: The tiers to try, in priority order (best/most-specific
            first). Must be non-empty.

    Raises:
        ValueError: If ``extractors`` is empty.
    """

    def __init__(self, extractors: Sequence[InvoiceExtractor]) -> None:
        if not extractors:
            raise ValueError("CascadingInvoiceExtractor needs at least one extractor")
        self._extractors = tuple(extractors)

    def extract(self, document: ParsedDocument) -> Invoice:
        """Extract using the first tier that succeeds.

        Args:
            document: The parsed document to extract from.

        Returns:
            The first successfully extracted :class:`Invoice`.

        Raises:
            InvoiceExtractionError: If every tier fails; the message lists each
                tier's reason so failures are diagnosable.
        """
        failures: list[str] = []
        for extractor in self._extractors:
            tier = type(extractor).__name__
            try:
                invoice = extractor.extract(document)
            except InvoiceExtractionError as exc:
                logger.info(
                    "Extraction tier failed; trying next",
                    extra={"tier": tier, "source_ref": document.source_ref},
                )
                failures.append(f"{tier}: {exc}")
                continue
            logger.info(
                "Extraction tier succeeded",
                extra={"tier": tier, "source_ref": document.source_ref},
            )
            return invoice

        raise InvoiceExtractionError(
            "All extraction tiers failed for "
            f"{document.source_ref}: " + " | ".join(failures)
        )
