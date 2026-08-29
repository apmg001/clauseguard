"""Tests for the rule-based invoice extractor.

Covers happy-path parsing, robustness (column reordering, thousands commas,
case-insensitive keys), the specific failure modes (missing header, missing
column, unparseable cell, empty text), and — the milestone — an end-to-end run
proving a *document's text* flows all the way to reconciliation findings.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from clauseguard.adapters.audit.in_memory import InMemoryAuditLog
from clauseguard.adapters.extraction.rule_based_invoice import (
    RuleBasedInvoiceExtractor,
)
from clauseguard.adapters.matching.heuristic import HeuristicMatcher
from clauseguard.domain.enums import DiscrepancyType
from clauseguard.domain.models import (
    Contract,
    Money,
    RateCardEntry,
    VolumeDiscountTier,
)
from clauseguard.exceptions import InvoiceExtractionError
from clauseguard.ports.ingestion import ParsedDocument
from clauseguard.rules.engine import RulesEngine
from clauseguard.services.reconciliation import ReconciliationService

GOOD_INVOICE_TEXT = """\
INVOICE
Invoice-ID: INV-900
Vendor: Acme Supplies Pvt Ltd
Date: 2026-06-01
Currency: INR

Line | SKU | Description | Qty | Unit-Rate | Line-Total
1 | WIDGET-A | Standard widget | 150 | 130.00 | 19,500.00
2 | GADGET-Z | Mystery gadget | 5 | 50.00 | 250.00
"""


def _doc(text: str, source_ref: str = "invoices/INV-900.pdf") -> ParsedDocument:
    return ParsedDocument(text=text, page_count=1, source_ref=source_ref)


def test_extracts_header_and_line_items() -> None:
    invoice = RuleBasedInvoiceExtractor().extract(_doc(GOOD_INVOICE_TEXT))
    assert invoice.invoice_id == "INV-900"
    assert invoice.vendor_name == "Acme Supplies Pvt Ltd"
    assert invoice.invoice_date == date(2026, 6, 1)
    assert invoice.currency == "INR"
    assert len(invoice.line_items) == 2


def test_money_and_quantity_are_decimal_with_currency() -> None:
    invoice = RuleBasedInvoiceExtractor().extract(_doc(GOOD_INVOICE_TEXT))
    line1 = invoice.line_items[0]
    assert line1.quantity == Decimal(150)
    assert line1.unit_rate.amount == Decimal("130.00")
    assert line1.unit_rate.currency == "INR"
    # Thousands comma stripped correctly.
    assert line1.line_total.amount == Decimal("19500.00")


def test_column_order_is_flexible() -> None:
    # Same data, columns reordered: header-name mapping must still work.
    text = """\
Invoice-ID: INV-1
Vendor: Acme
Date: 2026-02-02
Currency: USD

SKU | Qty | Unit-Rate | Line-Total | Line | Description
X-1 | 2 | 10.00 | 20.00 | 1 | Thing
"""
    invoice = RuleBasedInvoiceExtractor().extract(_doc(text))
    assert invoice.line_items[0].sku == "X-1"
    assert invoice.line_items[0].line_no == 1
    assert invoice.line_items[0].unit_rate.amount == Decimal("10.00")


def test_header_keys_are_case_insensitive() -> None:
    text = GOOD_INVOICE_TEXT.replace("Invoice-ID:", "invoice-id:").replace(
        "Currency:", "CURRENCY:"
    )
    invoice = RuleBasedInvoiceExtractor().extract(_doc(text))
    assert invoice.invoice_id == "INV-900"
    assert invoice.currency == "INR"


def test_missing_header_field_raises() -> None:
    text = GOOD_INVOICE_TEXT.replace("Vendor: Acme Supplies Pvt Ltd\n", "")
    with pytest.raises(InvoiceExtractionError):
        RuleBasedInvoiceExtractor().extract(_doc(text))


def test_missing_column_raises() -> None:
    text = """\
Invoice-ID: INV-1
Vendor: Acme
Date: 2026-02-02
Currency: USD

Line | SKU | Description | Qty | Unit-Rate
1 | X-1 | Thing | 2 | 10.00
"""
    with pytest.raises(InvoiceExtractionError):
        RuleBasedInvoiceExtractor().extract(_doc(text))


def test_unparseable_amount_raises() -> None:
    text = GOOD_INVOICE_TEXT.replace("130.00", "1O0.00")  # letter O, not zero
    with pytest.raises(InvoiceExtractionError):
        RuleBasedInvoiceExtractor().extract(_doc(text))


def test_empty_document_raises() -> None:
    with pytest.raises(InvoiceExtractionError):
        RuleBasedInvoiceExtractor().extract(_doc("   \n  \n"))


def test_end_to_end_text_to_findings() -> None:
    """The milestone: invoice *text* -> extractor -> rules -> findings."""
    invoice = RuleBasedInvoiceExtractor().extract(_doc(GOOD_INVOICE_TEXT))

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
                unit_rate=Money(amount=Decimal("100.00"), currency="INR"),
                volume_discounts=(
                    VolumeDiscountTier(
                        min_quantity=Decimal(100), discount_pct=Decimal("0.10")
                    ),
                ),
            ),
        ),
    )

    service = ReconciliationService(
        matcher=HeuristicMatcher(),
        rules_engine=RulesEngine(),
        audit_log=InMemoryAuditLog(),
    )
    result = service.reconcile(invoice, [contract])

    detected = {d.type for d in result.discrepancies}
    # A real (text-sourced) invoice now reaches the rules and is caught.
    assert DiscrepancyType.RATE_MISMATCH in detected
    assert DiscrepancyType.UNCONTRACTED_ITEM in detected