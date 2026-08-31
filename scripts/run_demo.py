"""End-to-end demo: two documents flow through the full pipeline.

Both the invoice *and* the contract start as raw text — exactly what parsed
documents yield — and are turned into domain objects by the rule-based
extractors before reconciliation:

    invoice text  -> NativePdfParser -> RuleBasedInvoiceExtractor  -> Invoice
    contract text -> NativePdfParser -> RuleBasedContractExtractor -> Contract
                          |
                          v
        HeuristicMatcher -> RulesEngine -> ReconciliationResult
        (match)            (deterministic  (citations + monetary
                            checks)         impact + audit record)

The invoice deliberately contains planted errors so the engine has something to
catch. Run with: ``python scripts/run_demo.py`` (from the project root).
"""

from __future__ import annotations

from clauseguard.adapters.audit.in_memory import InMemoryAuditLog
from clauseguard.adapters.extraction.rule_based_contract import (
    RuleBasedContractExtractor,
)
from clauseguard.adapters.extraction.rule_based_invoice import (
    RuleBasedInvoiceExtractor,
)
from clauseguard.adapters.ingestion.pdf_parser import NativePdfParser
from clauseguard.adapters.matching.heuristic import HeuristicMatcher
from clauseguard.rules.engine import RulesEngine
from clauseguard.services.reconciliation import ReconciliationService

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

CONTRACT_TEXT = """\
CONTRACT
Contract-ID: C-001
Vendor: Acme Supplies Pvt Ltd
Valid-From: 2026-01-01
Valid-To: 2026-12-31
Currency: INR

SKU | Description | Unit-Rate | Volume-Discounts
WIDGET-A | Standard widget | 100.00 | 100:0.10
"""


def main() -> None:
    """Run the full ingestion -> extraction -> reconciliation flow."""
    parser = NativePdfParser()

    # Ingestion + extraction for both documents.
    invoice = RuleBasedInvoiceExtractor().extract(
        parser.parse(INVOICE_TEXT.encode("utf-8"), source_ref="invoices/INV-900.pdf")
    )
    contract = RuleBasedContractExtractor().extract(
        parser.parse(CONTRACT_TEXT.encode("utf-8"), source_ref="contracts/C-001.pdf")
    )

    # Match -> rules -> audit.
    service = ReconciliationService(
        matcher=HeuristicMatcher(),
        rules_engine=RulesEngine(),
        audit_log=InMemoryAuditLog(),
    )
    result = service.reconcile(invoice, [contract])

    # Report.
    print(
        f"\nParsed invoice text  -> {len(invoice.line_items)} line items"
        f"\nParsed contract text -> {len(contract.rate_cards)} rate-card entries"
    )
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