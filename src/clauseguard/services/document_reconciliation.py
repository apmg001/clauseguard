"""Document reconciliation use-case.

Composes the ingestion and extraction layers with the core
:class:`~clauseguard.services.reconciliation.ReconciliationService`, so a caller
can hand in *raw documents* (an invoice and its candidate contracts) rather than
pre-structured domain objects, and get back a full reconciliation result.

This is the application service that finally connects the extraction pipeline to
the reconciliation pipeline end to end. It depends only on ports
(:class:`DocumentParser`, :class:`InvoiceExtractor`, :class:`ContractExtractor`)
plus the reconciliation service, so any tier is swappable at the composition root.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from clauseguard.domain.models import ReconciliationResult
from clauseguard.logging_config import get_logger
from clauseguard.ports.extraction import ContractExtractor, InvoiceExtractor
from clauseguard.ports.ingestion import DocumentParser
from clauseguard.services.reconciliation import ReconciliationService

logger = get_logger(__name__)


@dataclass(frozen=True)
class DocumentPayload:
    """Raw bytes of a document plus a source label for citations.

    Attributes:
        content: The raw document bytes (a PDF, or UTF-8 text).
        source_ref: A filename/URI used for citations downstream.
    """

    content: bytes
    source_ref: str


class DocumentReconciliationService:
    """Reconcile an invoice document against candidate contract documents.

    Args:
        parser: Turns raw bytes into a :class:`ParsedDocument`.
        invoice_extractor: Turns a parsed document into an :class:`Invoice`.
        contract_extractor: Turns a parsed document into a :class:`Contract`.
        reconciliation_service: Runs matching, rules, scoring and audit.
    """

    def __init__(
        self,
        *,
        parser: DocumentParser,
        invoice_extractor: InvoiceExtractor,
        contract_extractor: ContractExtractor,
        reconciliation_service: ReconciliationService,
    ) -> None:
        self._parser = parser
        self._invoice_extractor = invoice_extractor
        self._contract_extractor = contract_extractor
        self._reconciliation = reconciliation_service

    def reconcile_documents(
        self,
        invoice_document: DocumentPayload,
        contract_documents: Sequence[DocumentPayload],
    ) -> ReconciliationResult:
        """Parse, extract, and reconcile raw documents.

        Args:
            invoice_document: The invoice to reconcile.
            contract_documents: Candidate contracts in scope.

        Returns:
            The :class:`ReconciliationResult`.

        Raises:
            DocumentParseError: If a document cannot be parsed.
            InvoiceExtractionError / ContractExtractionError: If extraction fails.
            ReconciliationError: If reconciliation cannot complete.
        """
        logger.info(
            "Document reconciliation started",
            extra={"invoice_ref": invoice_document.source_ref,
                   "contracts": len(contract_documents)},
        )
        invoice = self._invoice_extractor.extract(
            self._parser.parse(
                invoice_document.content, source_ref=invoice_document.source_ref
            )
        )
        contracts = [
            self._contract_extractor.extract(
                self._parser.parse(doc.content, source_ref=doc.source_ref)
            )
            for doc in contract_documents
        ]
        return self._reconciliation.reconcile(invoice, contracts)
