"""Tests for domain model validation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from clauseguard.domain.models import Contract, Money


def test_money_uppercases_currency() -> None:
    assert Money(amount=Decimal("1"), currency="inr").currency == "INR"


def test_contract_rejects_inverted_validity_window() -> None:
    with pytest.raises(ValidationError):
        Contract(
            contract_id="C",
            vendor_name="V",
            valid_from=date(2026, 12, 31),
            valid_to=date(2026, 1, 1),
            currency="INR",
        )
