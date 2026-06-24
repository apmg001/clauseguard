"""Core domain models.

Immutable, validated value objects and entities for the reconciliation domain.
Built on Pydantic v2 so every object is validated at construction — invalid
data cannot flow between layers.

Design notes:
* **Money uses ``Decimal``, never ``float``.** Financial arithmetic with binary
  floats silently loses precision; for an audit-grade product that is
  unacceptable. All monetary values carry an explicit currency.
* Models are frozen (immutable) where they represent facts extracted from a
  document, so downstream stages cannot mutate source data.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clauseguard.domain.enums import (
    DiscrepancyType,
    MatchMethod,
    ReviewStatus,
    Severity,
)


class Money(BaseModel):
    """A monetary amount with an explicit currency.

    Attributes:
        amount: The value, stored as ``Decimal`` for exact arithmetic.
        currency: ISO-4217-style currency code (e.g. ``"INR"``, ``"USD"``).
    """

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper()

    def same_currency_as(self, other: Money) -> bool:
        """Return True if ``other`` shares this amount's currency."""
        return self.currency == other.currency


class VolumeDiscountTier(BaseModel):
    """A volume-based discount threshold within a rate card.

    Attributes:
        min_quantity: Minimum quantity (inclusive) at which the discount applies.
        discount_pct: Discount as a fraction in ``[0, 1]`` (e.g. ``0.10`` = 10%).
    """

    model_config = ConfigDict(frozen=True)

    min_quantity: Decimal = Field(gt=0)
    discount_pct: Decimal = Field(ge=0, le=1)


class RateCardEntry(BaseModel):
    """A contracted rate for a single SKU/service.

    Attributes:
        sku: Stable identifier for the item/service.
        description: Human-readable description (used for fuzzy line matching).
        unit_rate: Contracted price per unit.
        volume_discounts: Optional volume-discount tiers, evaluated best-first.
    """

    model_config = ConfigDict(frozen=True)

    sku: str
    description: str
    unit_rate: Money
    volume_discounts: tuple[VolumeDiscountTier, ...] = ()

    def applicable_discount(self, quantity: Decimal) -> Decimal:
        """Return the best discount fraction available for ``quantity``.

        Args:
            quantity: The invoiced quantity.

        Returns:
            The highest applicable discount fraction, or ``Decimal(0)``.
        """
        applicable = [
            tier.discount_pct
            for tier in self.volume_discounts
            if quantity >= tier.min_quantity
        ]
        return max(applicable, default=Decimal(0))


class Contract(BaseModel):
    """A vendor contract governing pricing and terms.

    Attributes:
        contract_id: Unique contract identifier.
        vendor_name: Counterparty name.
        valid_from: First date the contract is in force (inclusive).
        valid_to: Last date the contract is in force (inclusive).
        currency: Contract's base currency.
        rate_cards: Contracted rates, keyed by SKU at lookup time.
        source_ref: Free-text pointer to the source document/clause for citation.
    """

    model_config = ConfigDict(frozen=True)

    contract_id: str
    vendor_name: str
    valid_from: date
    valid_to: date
    currency: str = Field(min_length=3, max_length=3)
    rate_cards: tuple[RateCardEntry, ...] = ()
    source_ref: str | None = None

    @model_validator(mode="after")
    def _check_validity_window(self) -> Contract:
        if self.valid_to < self.valid_from:
            raise ValueError("valid_to must be on or after valid_from")
        return self

    def rate_for(self, sku: str) -> RateCardEntry | None:
        """Return the rate-card entry for ``sku`` if present, else None."""
        for entry in self.rate_cards:
            if entry.sku == sku:
                return entry
        return None

    def is_active_on(self, when: date) -> bool:
        """Return True if the contract is in force on ``when``."""
        return self.valid_from <= when <= self.valid_to


class InvoiceLineItem(BaseModel):
    """A single billed line on an invoice.

    Attributes:
        line_no: 1-based position of the line on the invoice.
        sku: Item identifier as printed on the invoice.
        description: Line description.
        quantity: Billed quantity.
        unit_rate: Billed price per unit.
        line_total: Billed total for the line as printed (checked against
            quantity × unit_rate by the rules engine).
    """

    model_config = ConfigDict(frozen=True)

    line_no: int = Field(ge=1)
    sku: str
    description: str
    quantity: Decimal = Field(gt=0)
    unit_rate: Money
    line_total: Money


class Invoice(BaseModel):
    """A vendor invoice to be reconciled against a contract.

    Attributes:
        invoice_id: Unique invoice identifier.
        vendor_name: Billing party name.
        invoice_date: Date the invoice was issued.
        currency: Invoice currency.
        line_items: The billed lines.
        source_ref: Pointer to the source document for citation.
    """

    model_config = ConfigDict(frozen=True)

    invoice_id: str
    vendor_name: str
    invoice_date: date
    currency: str = Field(min_length=3, max_length=3)
    line_items: tuple[InvoiceLineItem, ...]
    source_ref: str | None = None


class MatchResult(BaseModel):
    """The outcome of matching an invoice to a governing contract.

    Attributes:
        invoice_id: The invoice that was matched.
        contract_id: The chosen contract, or None if unmatched.
        score: Match confidence in ``[0, 1]``.
        method: How the match was made, for audit.
    """

    model_config = ConfigDict(frozen=True)

    invoice_id: str
    contract_id: str | None
    score: float = Field(ge=0.0, le=1.0)
    method: MatchMethod

    @property
    def is_matched(self) -> bool:
        """Return True if a contract was selected."""
        return self.contract_id is not None


class Discrepancy(BaseModel):
    """A single detected discrepancy, always carrying a source citation.

    Attributes:
        type: The category of discrepancy.
        severity: Business severity.
        description: Human-readable explanation.
        invoice_line_no: The offending invoice line, if line-specific.
        citation: Pointer to the contract clause / invoice line that grounds
            this finding. Required — no uncited flags are permitted.
        expected: The expected value (e.g. contracted rate), as text.
        actual: The actual value (e.g. billed rate), as text.
        monetary_impact: Estimated currency impact of the discrepancy.
        confidence: Detector confidence in ``[0, 1]``.
    """

    model_config = ConfigDict(frozen=True)

    type: DiscrepancyType
    severity: Severity
    description: str
    citation: str = Field(min_length=1)
    invoice_line_no: int | None = None
    expected: str | None = None
    actual: str | None = None
    monetary_impact: Money | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ReconciliationResult(BaseModel):
    """The full outcome of reconciling one invoice against one contract.

    Attributes:
        invoice_id: The reconciled invoice.
        contract_id: The contract used, or None if unmatched.
        match_score: The match confidence that produced ``contract_id``.
        discrepancies: All detected discrepancies (possibly empty).
        review_status: Routing decision for this result.
        total_impact: Summed monetary impact across discrepancies, if any.
        audit_id: Identifier of the audit record written for this result.
    """

    model_config = ConfigDict(frozen=True)

    invoice_id: str
    contract_id: str | None
    match_score: float
    discrepancies: tuple[Discrepancy, ...]
    review_status: ReviewStatus
    total_impact: Money | None = None
    audit_id: str | None = None
