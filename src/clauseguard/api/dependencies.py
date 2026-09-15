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
from clauseguard.adapters.extraction.rule_based_contract import (
    RuleBasedContractExtractor,
)
from clauseguard.adapters.extraction.rule_based_invoice import (
    RuleBasedInvoiceExtractor,
)
from clauseguard.adapters.ingestion.pdf_parser import NativePdfParser
from clauseguard.adapters.matching.heuristic import HeuristicMatcher
from clauseguard.ports.audit import AuditLog
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


def get_document_reconciliation_service() -> DocumentReconciliationService:
    """Assemble the document-in reconciliation service.

    Invoice extraction cascades layout-aware (digital-PDF geometry) -> rule-based
    text; contract extraction uses the rule-based text tier. Swapping tiers or
    adding the LLM tier is a change here only.
    """
    return DocumentReconciliationService(
        parser=NativePdfParser(),
        invoice_extractor=CascadingInvoiceExtractor(
            [LayoutAwareInvoiceExtractor(), RuleBasedInvoiceExtractor()]
        ),
        contract_extractor=RuleBasedContractExtractor(),
        reconciliation_service=get_reconciliation_service(),
    )
