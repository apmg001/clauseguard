"""Tests for the rule-based contract extractor.

Covers happy-path parsing (including volume-discount tiers), robustness (column
reordering, no-discount cell), the specific failure modes (missing header,
missing column, bad discount tier, invalid currency, inverted validity window),
and an end-to-end check that a text-sourced contract drives reconciliation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from clauseguard.adapters.audit.in_memory import InMemoryAuditLog
from clauseguard.adapters.extraction.rule_based_contract import (
    RuleBasedContractExtractor,
)
from clauseguard.adapters.extraction.rule_based_invoice import (
    RuleBasedInvoiceExtractor,
)
from clauseguard.adapters.matching.heuristic import HeuristicMatcher
from clauseguard.domain.enums import DiscrepancyType
from clauseguard.exceptions import ContractExtractionError
from clauseguard.ports.ingestion import ParsedDocument
from clauseguard.rules.engine import RulesEngine
from clauseguard.services.reconciliation import ReconciliationService

GOOD_CONTRACT_TEXT = """\
CONTRACT
Contract-ID: C-001
Vendor: Acme Supplies Pvt Ltd
Valid-From: 2026-01-01
Valid-To: 2026-12-31
Currency: INR

SKU | Description | Unit-Rate | Volume-Discounts
WIDGET-A | Standard widget | 100.00 | 100:0.10; 500:0.15
GADGET-Y | Fancy gadget | 50.00 |
"""


def _doc(text: str, source_ref: str = "contracts/C-001.pdf") -> ParsedDocument:
    return ParsedDocument(text=text, page_count=1, source_ref=source_ref)


def test_extracts_header_and_rate_cards() -> None:
    contract = RuleBasedContractExtractor().extract(_doc(GOOD_CONTRACT_TEXT))
    assert contract.contract_id == "C-001"
    assert contract.vendor_name == "Acme Supplies Pvt Ltd"
    assert contract.valid_from == date(2026, 1, 1)
    assert contract.valid_to == date(2026, 12, 31)
    assert contract.currency == "INR"
    assert len(contract.rate_cards) == 2


def test_parses_unit_rate_and_discount_tiers() -> None:
    contract = RuleBasedContractExtractor().extract(_doc(GOOD_CONTRACT_TEXT))
    widget = contract.rate_for("WIDGET-A")
    assert widget is not None
    assert widget.unit_rate.amount == Decimal("100.00")
    assert widget.unit_rate.currency == "INR"
    assert len(widget.volume_discounts) == 2
    # best-discount lookup works on the parsed tiers
    assert widget.applicable_discount(Decimal(150)) == Decimal("0.10")
    assert widget.applicable_discount(Decimal(600)) == Decimal("0.15")


def test_empty_discount_cell_means_no_tiers() -> None:
    contract = RuleBasedContractExtractor().extract(_doc(GOOD_CONTRACT_TEXT))
    gadget = contract.rate_for("GADGET-Y")
    assert gadget is not None
    assert gadget.volume_discounts == ()


def test_column_order_is_flexible() -> None:
    text = """\
Contract-ID: C-9
Vendor: Acme
Valid-From: 2026-01-01
Valid-To: 2026-12-31
Currency: USD

Unit-Rate | SKU | Volume-Discounts | Description
10.00 | X-1 | 50:0.05 | Thing
"""
    contract = RuleBasedContractExtractor().extract(_doc(text))
    entry = contract.rate_for("X-1")
    assert entry is not None
    assert entry.unit_rate.amount == Decimal("10.00")
    assert entry.applicable_discount(Decimal(50)) == Decimal("0.05")


def test_missing_header_field_raises() -> None:
    text = GOOD_CONTRACT_TEXT.replace("Valid-To: 2026-12-31\n", "")
    with pytest.raises(ContractExtractionError):
        RuleBasedContractExtractor().extract(_doc(text))


def test_missing_required_column_raises() -> None:
    text = """\
Contract-ID: C-9
Vendor: Acme
Valid-From: 2026-01-01
Valid-To: 2026-12-31
Currency: USD

SKU | Unit-Rate | Volume-Discounts
X-1 | 10.00 |
"""
    with pytest.raises(ContractExtractionError):
        RuleBasedContractExtractor().extract(_doc(text))


def test_malformed_discount_tier_raises() -> None:
    text = GOOD_CONTRACT_TEXT.replace("100:0.10; 500:0.15", "100-0.10")  # no colon
    with pytest.raises(ContractExtractionError):
        RuleBasedContractExtractor().extract(_doc(text))


def test_out_of_range_discount_raises() -> None:
    # discount_pct must be in [0, 1]; 1.5 must be rejected.
    text = GOOD_CONTRACT_TEXT.replace("100:0.10; 500:0.15", "100:1.5")
    with pytest.raises(ContractExtractionError):
        RuleBasedContractExtractor().extract(_doc(text))


def test_invalid_currency_length_raises() -> None:
    text = GOOD_CONTRACT_TEXT.replace("Currency: INR", "Currency: RUPEES")
    with pytest.raises(ContractExtractionError):
        RuleBasedContractExtractor().extract(_doc(text))


def test_inverted_validity_window_raises() -> None:
    text = GOOD_CONTRACT_TEXT.replace("Valid-To: 2026-12-31", "Valid-To: 2025-12-31")
    with pytest.raises(ContractExtractionError):
        RuleBasedContractExtractor().extract(_doc(text))


def test_end_to_end_both_documents_from_text() -> None:
    """Invoice text + contract text -> reconciliation findings."""
    invoice_text = """\
INVOICE
Invoice-ID: INV-900
Vendor: Acme Supplies Pvt Ltd
Date: 2026-06-01
Currency: INR

Line | SKU | Description | Qty | Unit-Rate | Line-Total
1 | WIDGET-A | Standard widget | 150 | 130.00 | 19500.00
"""
    invoice = RuleBasedInvoiceExtractor().extract(
        ParsedDocument(text=invoice_text, page_count=1, source_ref="i.pdf")
    )
    contract = RuleBasedContractExtractor().extract(_doc(GOOD_CONTRACT_TEXT))

    service = ReconciliationService(
        matcher=HeuristicMatcher(),
        rules_engine=RulesEngine(),
        audit_log=InMemoryAuditLog(),
    )
    result = service.reconcile(invoice, [contract])
    detected = {d.type for d in result.discrepancies}
    assert DiscrepancyType.RATE_MISMATCH in detected
    assert DiscrepancyType.MISSED_VOLUME_DISCOUNT in detected