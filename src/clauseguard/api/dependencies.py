"""Dependency wiring (composition root).

FastAPI dependency providers assemble concrete adapters into the
:class:`ReconciliationService`. This is the *only* module that knows which
concrete implementations are in use; swapping an adapter (e.g. a DB-backed audit
log, or the ML matcher) is a one-line change here. The audit log is a singleton
so records persist across requests within the process.
"""

from __future__ import annotations

from functools import lru_cache

from clauseguard.adapters.audit.in_memory import InMemoryAuditLog
from clauseguard.adapters.extraction.cascading import CascadingInvoiceExtractor
from clauseguard.adapters.extraction.layout_aware_invoice import (
    LayoutAwareInvoiceExtractor,
)
from clauseguard.adapters.extraction.llm_invoice import LLMInvoiceExtractor
from clauseguard.adapters.extraction.rule_based_contract import (
    RuleBasedContractExtractor,
)
from clauseguard.adapters.extraction.rule_based_invoice import (
    RuleBasedInvoiceExtractor,
)
from clauseguard.adapters.ingestion.fallback import FallbackDocumentParser
from clauseguard.adapters.ingestion.ocr import OcrDocumentParser
from clauseguard.adapters.ingestion.pdf_parser import NativePdfParser
from clauseguard.adapters.matching.heuristic import HeuristicMatcher
from clauseguard.config import Settings, get_settings
from clauseguard.ports.audit import AuditLog
from clauseguard.ports.extraction import InvoiceExtractor
from clauseguard.ports.ingestion import DocumentParser
from clauseguard.providers.registry import build_provider
from clauseguard.rules.engine import RulesEngine
from clauseguard.services.document_reconciliation import (
    DocumentReconciliationService,
)
from clauseguard.services.reconciliation import ReconciliationService


@lru_cache(maxsize=1)
def get_audit_log() -> AuditLog:
    """Return the process-wide audit log singleton."""
    return InMemoryAuditLog()


def get_reconciliation_service() -> ReconciliationService:
    """Assemble and return a :class:`ReconciliationService`."""
    return ReconciliationService(
        matcher=HeuristicMatcher(),
        rules_engine=RulesEngine(),
        audit_log=get_audit_log(),
    )


def build_invoice_extractor(settings: Settings) -> InvoiceExtractor:
    """Build the invoice-extraction cascade for the document pipeline.

    Deterministic-first: layout-aware (digital-PDF geometry) then rule-based
    text. When ``settings.enable_llm_extraction`` is set, the LLM tier is
    appended as a last resort for layouts the deterministic tiers cannot parse
    (its provider defaults to a local Ollama server).

    Args:
        settings: Application settings controlling the LLM tier.

    Returns:
        A :class:`CascadingInvoiceExtractor` over the enabled tiers.
    """
    tiers: list[InvoiceExtractor] = [
        LayoutAwareInvoiceExtractor(),
        RuleBasedInvoiceExtractor(),
    ]
    if settings.enable_llm_extraction:
        tiers.append(LLMInvoiceExtractor(build_provider(settings)))
    return CascadingInvoiceExtractor(tiers)


def build_document_parser(settings: Settings) -> DocumentParser:
    """Build the document parser for the pipeline.

    Native text-layer parsing by default; when ``settings.enable_ocr`` is set,
    wrap it in a fallback that routes scanned/image PDFs (little recovered text)
    to the OCR parser. The OCR toolchain must be installed for this to work.

    Args:
        settings: Application settings controlling OCR fallback.

    Returns:
        A :class:`DocumentParser`.
    """
    native = NativePdfParser()
    if not settings.enable_ocr:
        return native
    return FallbackDocumentParser(primary=native, ocr=OcrDocumentParser())


def get_document_reconciliation_service() -> DocumentReconciliationService:
    """Assemble the document-in reconciliation service.

    Invoice extraction cascades layout-aware (digital-PDF geometry) -> rule-based
    text; contract extraction uses the rule-based text tier. Swapping tiers or
    adding the LLM tier is a change here only.
    """
    return DocumentReconciliationService(
        parser=build_document_parser(get_settings()),
        invoice_extractor=build_invoice_extractor(get_settings()),
        contract_extractor=RuleBasedContractExtractor(),
        reconciliation_service=get_reconciliation_service(),
    )
