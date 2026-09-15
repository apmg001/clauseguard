"""Inspect a real document through the ingestion + extraction pipeline.

A diagnostic tool for running *real* invoices (and optionally a contract) through
ClauseGuard and seeing exactly what happened at each stage — what the parser
recovered, whether extraction succeeded and via which tier, and (if a contract is
supplied) the reconciliation findings. Its purpose is to make failures legible:
on a messy real-world PDF, this shows *why* a tier failed, not just that it did.

Usage:
    python scripts/inspect_document.py INVOICE.pdf [CONTRACT.pdf|CONTRACT.txt]

Both arguments may be PDFs or plain-text files; the parser detects which.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

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
from clauseguard.exceptions import (
    ContractExtractionError,
    DocumentParseError,
    InvoiceExtractionError,
)
from clauseguard.ports.ingestion import ParsedDocument
from clauseguard.rules.engine import RulesEngine
from clauseguard.services.reconciliation import ReconciliationService

RULE = "-" * 72


def _banner(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")


def _inspect_parse(path: Path) -> ParsedDocument:
    """Parse a file and print what the ingestion layer recovered."""
    document = NativePdfParser().parse(path.read_bytes(), source_ref=path.name)
    _banner(f"INGESTION — {path.name}")
    print(f"pages:          {document.page_count}")
    print(f"text chars:     {len(document.text)}")
    print(f"tables found:   {len(document.tables)}")
    if document.tables:
        first = document.tables[0]
        print(f"first table:    {len(first)} rows x "
              f"{len(first[0]) if first else 0} cols")
        for row in first[:4]:
            print(f"   | {' | '.join(row)}")
        if len(first) > 4:
            print(f"   ... (+{len(first) - 4} more rows)")
    print("\ntext preview (first 500 chars):")
    print(document.text[:500])
    return document


def _invoice_extractor() -> CascadingInvoiceExtractor:
    return CascadingInvoiceExtractor(
        [LayoutAwareInvoiceExtractor(), RuleBasedInvoiceExtractor()]
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Returns:
        Process exit code (0 on success, 1 if extraction of the invoice failed).
    """
    parser = argparse.ArgumentParser(description="Inspect a document end-to-end.")
    parser.add_argument("invoice", type=Path, help="Invoice PDF or text file.")
    parser.add_argument(
        "contract", type=Path, nargs="?", help="Optional contract PDF or text file."
    )
    args = parser.parse_args(argv)

    logging.getLogger().setLevel(logging.WARNING)  # keep output readable

    try:
        invoice_doc = _inspect_parse(args.invoice)
    except (FileNotFoundError, DocumentParseError) as exc:
        print(f"\nFAILED to read/parse invoice: {exc}")
        return 1

    _banner("EXTRACTION — invoice")
    try:
        invoice = _invoice_extractor().extract(invoice_doc)
    except InvoiceExtractionError as exc:
        print("Invoice extraction FAILED (all tiers). This is the useful signal —")
        print("it shows which tiers failed and why on a real document:\n")
        print(exc)
        return 1
    print("Invoice extracted successfully:")
    print(f"  invoice_id: {invoice.invoice_id}")
    print(f"  vendor:     {invoice.vendor_name}")
    print(f"  date:       {invoice.invoice_date}")
    print(f"  currency:   {invoice.currency}")
    print(f"  line items: {len(invoice.line_items)}")
    for li in invoice.line_items:
        print(f"    {li.line_no}: {li.sku} x{li.quantity} @ "
              f"{li.unit_rate.currency} {li.unit_rate.amount} = "
              f"{li.line_total.currency} {li.line_total.amount}")

    if args.contract is None:
        print("\n(no contract supplied — skipping reconciliation)")
        return 0

    try:
        contract_doc = _inspect_parse(args.contract)
        contract = RuleBasedContractExtractor().extract(contract_doc)
    except (FileNotFoundError, DocumentParseError, ContractExtractionError) as exc:
        print(f"\nContract parse/extract FAILED: {exc}")
        return 1

    service = ReconciliationService(
        matcher=HeuristicMatcher(),
        rules_engine=RulesEngine(),
        audit_log=InMemoryAuditLog(),
    )
    result = service.reconcile(invoice, [contract])

    _banner("RECONCILIATION")
    print(f"matched contract: {result.contract_id} (score {result.match_score:.2f})")
    print(f"status:           {result.review_status.value}")
    if result.total_impact:
        print(f"total impact:     {result.total_impact.currency} "
              f"{result.total_impact.amount}")
    print(f"discrepancies:    {len(result.discrepancies)}")
    for d in result.discrepancies:
        print(f"  • [{d.type.value}] {d.description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
