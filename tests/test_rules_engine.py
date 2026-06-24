"""Tests for the deterministic rules engine."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from clauseguard.domain.enums import DiscrepancyType
from clauseguard.domain.models import Invoice, InvoiceLineItem
from clauseguard.rules.engine import RulesEngine
from tests.conftest import inr


def _line(**kw) -> InvoiceLineItem:
    base = dict(
        line_no=1,
        sku="WIDGET-A",
        description="Standard widget",
        quantity=Decimal(10),
        unit_rate=inr("100.00"),
        line_total=inr("1000.00"),
    )
    base.update(kw)
    return InvoiceLineItem(**base)


def test_clean_invoice_has_no_discrepancies(contract, clean_invoice) -> None:
    findings = RulesEngine().evaluate(clean_invoice, contract)
    assert findings == []


def test_detects_rate_overcharge(contract) -> None:
    invoice = Invoice(
        invoice_id="INV-1",
        vendor_name="Acme Supplies Pvt Ltd",
        invoice_date=date(2026, 3, 1),
        currency="INR",
        line_items=(_line(unit_rate=inr("120.00"), line_total=inr("1200.00")),),
    )
    findings = RulesEngine().evaluate(invoice, contract)
    types = {f.type for f in findings}
    assert DiscrepancyType.RATE_MISMATCH in types
    rate = next(f for f in findings if f.type == DiscrepancyType.RATE_MISMATCH)
    # Overcharge of 20 per unit * 10 units = 200.
    assert rate.monetary_impact is not None
    assert rate.monetary_impact.amount == Decimal("200.00")


def test_detects_arithmetic_error(contract) -> None:
    invoice = Invoice(
        invoice_id="INV-2",
        vendor_name="Acme Supplies Pvt Ltd",
        invoice_date=date(2026, 3, 1),
        currency="INR",
        line_items=(_line(line_total=inr("9999.00")),),
    )
    findings = RulesEngine().evaluate(invoice, contract)
    assert DiscrepancyType.ARITHMETIC_ERROR in {f.type for f in findings}


def test_detects_missed_volume_discount(contract) -> None:
    # 150 units qualifies for the 10% tier; billed at full 100 instead of 90.
    invoice = Invoice(
        invoice_id="INV-3",
        vendor_name="Acme Supplies Pvt Ltd",
        invoice_date=date(2026, 3, 1),
        currency="INR",
        line_items=(
            _line(quantity=Decimal(150), line_total=inr("15000.00")),
        ),
    )
    findings = RulesEngine().evaluate(invoice, contract)
    assert DiscrepancyType.MISSED_VOLUME_DISCOUNT in {f.type for f in findings}


def test_detects_out_of_term(contract) -> None:
    invoice = Invoice(
        invoice_id="INV-4",
        vendor_name="Acme Supplies Pvt Ltd",
        invoice_date=date(2027, 1, 1),
        currency="INR",
        line_items=(_line(),),
    )
    findings = RulesEngine().evaluate(invoice, contract)
    assert DiscrepancyType.OUT_OF_TERM in {f.type for f in findings}
