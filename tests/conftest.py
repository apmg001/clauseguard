"""Shared pytest fixtures.

Provides small, hand-built domain objects so the deterministic core can be
tested without any document parsing or external services.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from clauseguard.domain.models import (
    Contract,
    Invoice,
    InvoiceLineItem,
    Money,
    RateCardEntry,
    VolumeDiscountTier,
)


def inr(amount: str) -> Money:
    """Build an INR Money value from a string amount."""
    return Money(amount=Decimal(amount), currency="INR")


@pytest.fixture
def contract() -> Contract:
    """A simple contract with one discounted SKU."""
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


@pytest.fixture
def clean_invoice() -> Invoice:
    """An invoice that matches the contract with no discrepancies."""
    return Invoice(
        invoice_id="INV-100",
        vendor_name="Acme Supplies Pvt Ltd",
        invoice_date=date(2026, 3, 1),
        currency="INR",
        line_items=(
            InvoiceLineItem(
                line_no=1,
                sku="WIDGET-A",
                description="Standard widget",
                quantity=Decimal(10),
                unit_rate=inr("100.00"),
                line_total=inr("1000.00"),
            ),
        ),
        source_ref="invoices/INV-100.pdf",
    )
