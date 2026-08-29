"""Tests for CurrencyMismatchRule and the currency guards on amount rules."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from clauseguard.domain.enums import DiscrepancyType
from clauseguard.domain.models import (
    Contract,
    Invoice,
    InvoiceLineItem,
    Money,
    RateCardEntry,
    VolumeDiscountTier,
)
from clauseguard.rules.checks import (
    CurrencyMismatchRule,
    MissedVolumeDiscountRule,
    RateMismatchRule,
)


def _contract(currency: str = "INR") -> Contract:
    return Contract(
        contract_id="C-1",
        vendor_name="Acme",
        valid_from=date(2026, 1, 1),
        valid_to=date(2026, 12, 31),
        currency=currency,
        rate_cards=(
            RateCardEntry(
                sku="WIDGET-A",
                description="Standard widget",
                unit_rate=Money(amount=Decimal("100.00"), currency=currency),
                volume_discounts=(
                    VolumeDiscountTier(
                        min_quantity=Decimal(100), discount_pct=Decimal("0.10")
                    ),
                ),
            ),
        ),
    )


def _invoice(line_currency: str) -> Invoice:
    return Invoice(
        invoice_id="INV-1",
        vendor_name="Acme",
        invoice_date=date(2026, 6, 1),
        currency=line_currency,
        line_items=(
            InvoiceLineItem(
                line_no=1,
                sku="WIDGET-A",
                description="Standard widget",
                quantity=Decimal(150),
                unit_rate=Money(amount=Decimal("130.00"), currency=line_currency),
                line_total=Money(amount=Decimal("19500.00"), currency=line_currency),
            ),
        ),
    )


def test_flags_currency_mismatch() -> None:
    findings = CurrencyMismatchRule().evaluate(_invoice("USD"), _contract("INR"))
    assert len(findings) == 1
    assert findings[0].type is DiscrepancyType.CURRENCY_MISMATCH
    assert findings[0].expected == "INR"
    assert findings[0].actual == "USD"
    assert findings[0].invoice_line_no == 1
    assert findings[0].monetary_impact is None


def test_no_finding_when_currency_matches() -> None:
    findings = CurrencyMismatchRule().evaluate(_invoice("INR"), _contract("INR"))
    assert findings == []


def test_rate_rule_skips_currency_mismatched_line() -> None:
    findings = RateMismatchRule().evaluate(_invoice("USD"), _contract("INR"))
    assert findings == []


def test_discount_rule_skips_currency_mismatched_line() -> None:
    findings = MissedVolumeDiscountRule().evaluate(_invoice("USD"), _contract("INR"))
    assert findings == []


def test_rate_rule_still_fires_when_currency_matches() -> None:
    findings = RateMismatchRule().evaluate(_invoice("INR"), _contract("INR"))
    assert len(findings) == 1
    assert findings[0].type is DiscrepancyType.RATE_MISMATCH
