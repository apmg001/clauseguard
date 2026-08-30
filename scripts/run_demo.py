"""End-to-end demo: a document flows through the full pipeline.

Unlike a hand-built object graph, this demo starts from the *raw text of an
invoice* — exactly what a real document yields once parsed — and runs it through
every stage:

    invoice text
        -> NativePdfParser           (ingestion: bytes/text -> ParsedDocument)
        -> RuleBasedInvoiceExtractor (extraction: text -> Invoice)
        -> HeuristicMatcher          (match invoice -> governing contract)
        -> RulesEngine               (deterministic discrepancy checks)
        -> ReconciliationResult      (citations + monetary impact + audit record)

The contract is still constructed in code here for a self-contained demo; a
companion ``ContractExtractor`` (roadmap) will source it from text too. The
invoice deliberately contains planted errors so the engine has something to
catch.

Run with: ``python scripts/run_demo.py`` (from the project root).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from clauseguard.adapters.audit.in_memory import InMemoryAuditLog
from clauseguard.adapters.extraction.rule_based_invoice import (
    RuleBasedInvoiceExtractor,
)
from clauseguard.adapters.ingestion.pdf_parser import NativePdfParser
from clauseguard.adapters.matching.heuristic import HeuristicMatcher
from clauseguard.domain.models import (
    Contract,
    Money,
    RateCardEntry,
    VolumeDiscountTier,
)
from clauseguard.rules.engine import RulesEngine
from clauseguard.services.reconciliation import ReconciliationService

# The raw text of the invoice as a document parser would emit it.
INVOICE_TEXT = """\
INVOICE
Invoice-ID: INV-900
Vendor: Acme Supplies Pvt Ltd
Date: 2026-06-01
Currency: INR

Line | SKU | Description | Qty | Unit-Rate | Line-Total
1 | WIDGET-A | Standard widget | 150 | 130.00 | 19,500.00
2 | GADGET-Z | Mystery gadget | 5 | 50.00 | 250.00
"""


def inr(amount: str) -> Money:
    """Convenience constructor for an INR :class:`Money` value."""
    return Money(amount=Decimal(amount), currency="INR")


def build_contract() -> Contract:
    """Return the governing contract used for the demo."""
    return Contract(
        contract_id="C-001",
        vendor_name="Acme Supplies Pvt Ltd",
        valid_from=date(2026, 1, 1),
        valid_to=date(2026, 12, 31),
        currency="INR",
        rate_cards=(
            RateCardEntry(
                sku="WIDGET-A",
                description="Standard widget",
                unit_rate=inr("100.00"),  # contracted rate; invoice bills 130
                volume_discounts=(
                    VolumeDiscountTier(
                        min_quantity=Decimal(100), discount_pct=Decimal("0.10")
                    ),
                ),
            ),
        ),
        source_ref="contracts/C-001.pdf",
    )


def main() -> None:
    """Run the full ingestion -> extraction -> reconciliation flow."""
    # 1. Ingestion: raw bytes -> ParsedDocument (text).
    parser = NativePdfParser()
    document = parser.parse(
        INVOICE_TEXT.encode("utf-8"), source_ref="invoices/INV-900.pdf"
    )

    # 2. Extraction: document text -> validated Invoice.
    invoice = RuleBasedInvoiceExtractor().extract(document)

    # 3-5. Match -> rules -> audit, via the reconciliation use-case.
    service = ReconciliationService(
        matcher=HeuristicMatcher(),
        rules_engine=RulesEngine(),
        audit_log=InMemoryAuditLog(),
    )
    result = service.reconcile(invoice, [build_contract()])

    # Report.
    print(f"\nParsed invoice text -> {len(invoice.line_items)} line items")
    print(
        f"Invoice {result.invoice_id}  ->  contract {result.contract_id} "
        f"(match {result.match_score:.2f})"
    )
    print(f"Status: {result.review_status.value}")
    if result.total_impact:
        print(
            f"Total impact: {result.total_impact.currency} "
            f"{result.total_impact.amount}"
        )
    print(f"Audit id: {result.audit_id}\n")
    print(f"Discrepancies ({len(result.discrepancies)}):")
    for d in result.discrepancies:
        impact = (
            f"{d.monetary_impact.currency} {d.monetary_impact.amount}"
            if d.monetary_impact
            else "-"
        )
        print(f"  • [{d.type.value}] {d.description}")
        print(
            f"      expected={d.expected}  actual={d.actual}  "
            f"impact={impact}  conf={d.confidence}"
        )
        print(f"      citation: {d.citation}")


if __name__ == "__main__":
    main()