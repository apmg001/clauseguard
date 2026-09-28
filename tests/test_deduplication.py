"""Tests for duplicate-invoice detection (adapter + service integration)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from clauseguard.adapters.audit.in_memory import InMemoryAuditLog
from clauseguard.adapters.dedup.in_memory import InMemoryDuplicateDetector
from clauseguard.adapters.matching.heuristic import HeuristicMatcher
from clauseguard.domain.enums import DiscrepancyType, Severity
from clauseguard.domain.models import Invoice, InvoiceLineItem
from clauseguard.exceptions import DeduplicationError
from clauseguard.ports.deduplication import DuplicateDetector
from clauseguard.rules.engine import RulesEngine
from clauseguard.services.reconciliation import ReconciliationService
from tests.conftest import inr


class _ExplodingDetector:
    """A detector whose store is unavailable, to prove fault isolation."""

    def check_and_register(self, invoice: Invoice) -> str | None:
        raise DeduplicationError("store unavailable")


def _service(detector: DuplicateDetector | None) -> ReconciliationService:
    return ReconciliationService(
        matcher=HeuristicMatcher(),
        rules_engine=RulesEngine(),
        audit_log=InMemoryAuditLog(),
        duplicate_detector=detector,
    )


# --------------------------------------------------------------------------- #
# Adapter unit behaviour
# --------------------------------------------------------------------------- #
def test_detector_registers_then_flags(clean_invoice) -> None:
    detector = InMemoryDuplicateDetector()
    assert detector.check_and_register(clean_invoice) is None
    assert detector.check_and_register(clean_invoice) == clean_invoice.invoice_id


def test_detector_is_conformant_to_port() -> None:
    assert isinstance(InMemoryDuplicateDetector(), DuplicateDetector)


def test_detector_normalises_vendor_and_id(clean_invoice) -> None:
    detector = InMemoryDuplicateDetector()
    detector.check_and_register(clean_invoice)
    noisy = clean_invoice.model_copy(
        update={
            "vendor_name": f"  {clean_invoice.vendor_name.upper()}  ",
            "invoice_id": clean_invoice.invoice_id.lower(),
        }
    )
    assert detector.check_and_register(noisy) == clean_invoice.invoice_id


def test_distinct_invoices_not_flagged(clean_invoice) -> None:
    detector = InMemoryDuplicateDetector()
    detector.check_and_register(clean_invoice)
    other = clean_invoice.model_copy(update={"invoice_id": "INV-999"})
    assert detector.check_and_register(other) is None


# --------------------------------------------------------------------------- #
# Service integration
# --------------------------------------------------------------------------- #
def test_resubmitted_invoice_flagged_with_full_impact(contract, clean_invoice) -> None:
    service = _service(InMemoryDuplicateDetector())
    first = service.reconcile(clean_invoice, [contract])
    assert not any(
        d.type == DiscrepancyType.DUPLICATE_INVOICE for d in first.discrepancies
    )

    second = service.reconcile(clean_invoice, [contract])
    dups = [
        d for d in second.discrepancies if d.type == DiscrepancyType.DUPLICATE_INVOICE
    ]
    assert len(dups) == 1
    dup = dups[0]
    assert dup.severity == Severity.HIGH
    assert dup.confidence == 1.0
    assert dup.citation  # mandatory, non-empty
    assert dup.monetary_impact is not None
    assert dup.monetary_impact.amount == Decimal("1000.00")
    assert second.total_impact is not None
    assert second.total_impact.amount == Decimal("1000.00")


def test_duplicate_flagged_even_when_unmatched() -> None:
    invoice = Invoice(
        invoice_id="INV-Z",
        vendor_name="Nowhere Vendor LLC",
        invoice_date=date(2026, 3, 1),
        currency="INR",
        line_items=(
            InvoiceLineItem(
                line_no=1,
                sku="X",
                description="thing",
                quantity=Decimal(1),
                unit_rate=inr("50.00"),
                line_total=inr("50.00"),
            ),
        ),
    )
    # A candidate exists so matching runs, but the vendor will not clear threshold.
    from clauseguard.domain.models import Contract

    unrelated = Contract(
        contract_id="C-OTHER",
        vendor_name="Acme Supplies Pvt Ltd",
        valid_from=date(2026, 1, 1),
        valid_to=date(2026, 12, 31),
        currency="INR",
    )
    service = _service(InMemoryDuplicateDetector())
    service.reconcile(invoice, [unrelated])
    second = service.reconcile(invoice, [unrelated])
    assert second.contract_id is None
    assert any(
        d.type == DiscrepancyType.DUPLICATE_INVOICE for d in second.discrepancies
    )


def test_no_detector_means_no_duplicate_findings(contract, clean_invoice) -> None:
    service = _service(None)
    service.reconcile(clean_invoice, [contract])
    second = service.reconcile(clean_invoice, [contract])
    assert not any(
        d.type == DiscrepancyType.DUPLICATE_INVOICE for d in second.discrepancies
    )


def test_detector_failure_does_not_abort_reconciliation(
    contract, clean_invoice
) -> None:
    service = _service(_ExplodingDetector())
    result = service.reconcile(clean_invoice, [contract])
    # Reconciliation still completes and is audited despite the dedup failure.
    assert result.audit_id is not None
    assert not any(
        d.type == DiscrepancyType.DUPLICATE_INVOICE for d in result.discrepancies
    )


@pytest.mark.parametrize("runs", [3, 5])
def test_only_first_occurrence_is_clean(contract, clean_invoice, runs) -> None:
    service = _service(InMemoryDuplicateDetector())
    results = [service.reconcile(clean_invoice, [contract]) for _ in range(runs)]
    flagged = [
        any(d.type == DiscrepancyType.DUPLICATE_INVOICE for d in r.discrepancies)
        for r in results
    ]
    assert flagged[0] is False
    assert all(flagged[1:])
