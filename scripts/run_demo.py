"""End-to-end demo of the Phase 1 reconciliation core.

Builds an in-memory contract and a deliberately faulty invoice, runs the full
service, and prints the discrepancies with their citations. This is the seed of
the seeded-error evaluation harness described in BUILD_BRIEF.md §8.

Run with: ``python scripts/run_demo.py`` (from the project root).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from clauseguard.adapters.audit.in_memory import InMemoryAuditLog
from clauseguard.adapters.matching.heuristic import HeuristicMatcher
from clauseguard.domain.models import (
    Contract,
    Invoice,
    InvoiceLineItem,
    Money,
    RateCardEntry,
    VolumeDiscountTier,
)
from clauseguard.rules.engine import RulesEngine
from clauseguard.services.reconciliation import ReconciliationService


def inr(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency="INR")


def main() -> None:
    contract = Contract(
        contract_id="C-001",
        vendor_name="Acme Supplies Pvt Ltd",
        valid_from=date(2026, 1, 1),
        valid_to=date(2026, 12, 31),
        currency="INR",
        rate_cards=(
            RateCardEntry(
                sku="WIDGET-A",
                description="Standard widget",
                unit_rate=inr("100.00"),
                volume_discounts=(
                    VolumeDiscountTier(
                        min_quantity=Decimal(100), discount_pct=Decimal("0.10")
                    ),
                ),
            ),
        ),
        source_ref="contracts/C-001.pdf",
    )

    invoice = Invoice(
        invoice_id="INV-900",
        vendor_name="Acme Supplies Pvt Ltd",
        invoice_date=date(2026, 6, 1),
        currency="INR",
        line_items=(
            # Overcharged: contracted 100, billed 130.
            InvoiceLineItem(
                line_no=1, sku="WIDGET-A", description="Standard widget",
                quantity=Decimal(150), unit_rate=inr("130.00"),
                line_total=inr("19500.00"),
            ),
            # Uncontracted SKU.
            InvoiceLineItem(
                line_no=2, sku="GADGET-Z", description="Mystery gadget",
                quantity=Decimal(5), unit_rate=inr("50.00"),
                line_total=inr("250.00"),
            ),
        ),
    )

    service = ReconciliationService(
        matcher=HeuristicMatcher(),
        rules_engine=RulesEngine(),
        audit_log=InMemoryAuditLog(),
    )
    result = service.reconcile(invoice, [contract])

    print(f"\nInvoice {result.invoice_id}  ->  contract {result.contract_id} "
          f"(match {result.match_score:.2f})")
    print(f"Status: {result.review_status.value}")
    if result.total_impact:
        print(f"Total impact: {result.total_impact.currency} "
              f"{result.total_impact.amount}")
    print(f"Audit id: {result.audit_id}\n")
    print(f"Discrepancies ({len(result.discrepancies)}):")
    for d in result.discrepancies:
        impact = (f"{d.monetary_impact.currency} {d.monetary_impact.amount}"
                  if d.monetary_impact else "-")
        print(f"  • [{d.type.value}] {d.description}")
        print(f"      expected={d.expected}  actual={d.actual}  "
              f"impact={impact}  conf={d.confidence}")
        print(f"      citation: {d.citation}")


if __name__ == "__main__":
    main()
