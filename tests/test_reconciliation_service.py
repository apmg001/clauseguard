"""Tests for the reconciliation orchestration service."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from clauseguard.adapters.audit.in_memory import InMemoryAuditLog
from clauseguard.adapters.matching.heuristic import HeuristicMatcher
from clauseguard.domain.enums import ReviewStatus
from clauseguard.domain.models import Invoice, InvoiceLineItem
from clauseguard.rules.engine import RulesEngine
from clauseguard.services.reconciliation import ReconciliationService
from tests.conftest import inr


def _service() -> ReconciliationService:
    return ReconciliationService(
        matcher=HeuristicMatcher(),
        rules_engine=RulesEngine(),
        audit_log=InMemoryAuditLog(),
    )


def test_clean_invoice_auto_cleared(contract, clean_invoice) -> None:
    result = _service().reconcile(clean_invoice, [contract])
    assert result.review_status == ReviewStatus.AUTO_CLEARED
    assert result.audit_id is not None


def test_unmatched_invoice_routes_without_inventing_contract(contract) -> None:
    invoice = Invoice(
        invoice_id="INV-X",
        vendor_name="Totally Different Vendor LLC",
        invoice_date=date(2026, 3, 1),
        currency="INR",
        line_items=(
            InvoiceLineItem(
                line_no=1,
                sku="WIDGET-A",
                description="Standard widget",
                quantity=Decimal(1),
                unit_rate=inr("100.00"),
                line_total=inr("100.00"),
            ),
        ),
    )
    result = _service().reconcile(invoice, [contract])
    assert result.contract_id is None
    assert result.audit_id is not None
