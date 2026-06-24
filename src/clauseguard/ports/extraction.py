"""Port: structured extraction.

Extractors turn parsed text into validated domain objects. The split mirrors
the architecture rule: deterministic/rule-based adapters handle rigid fields,
and an LLM-backed adapter (Phase 4) handles semantically messy clauses — both
behind these same interfaces.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from clauseguard.domain.models import Contract, Invoice
from clauseguard.ports.ingestion import ParsedDocument


@runtime_checkable
class ContractExtractor(Protocol):
    """Extract a :class:`Contract` from a parsed document."""

    def extract(self, document: ParsedDocument) -> Contract:
        """Extract contract terms.

        Args:
            document: The parsed contract document.

        Returns:
            A populated :class:`Contract`.

        Raises:
            ContractExtractionError: If required terms cannot be extracted.
        """
        ...


@runtime_checkable
class InvoiceExtractor(Protocol):
    """Extract an :class:`Invoice` from a parsed document."""

    def extract(self, document: ParsedDocument) -> Invoice:
        """Extract invoice header and line items.

        Args:
            document: The parsed invoice document.

        Returns:
            A populated :class:`Invoice`.

        Raises:
            InvoiceExtractionError: If required fields cannot be extracted.
        """
        ...
