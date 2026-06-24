"""Concrete deterministic discrepancy rules.

Each rule is small, pure, and reproducible. They never call an LLM and never do
floating-point money math — all arithmetic is on ``Decimal``. Every emitted
:class:`Discrepancy` carries a citation grounding it in the contract/invoice.

Confidence here is deterministic and rule-specific (these are exact checks, so
confidence is high). A later calibration layer can refine these scores once
labelled data exists; the interface does not change.
"""

from __future__ import annotations

from decimal import Decimal

from clauseguard.config import get_settings
from clauseguard.domain.enums import DiscrepancyType, Severity
from clauseguard.domain.models import Contract, Discrepancy, Invoice, Money
from clauseguard.exceptions import RuleEvaluationError
from clauseguard.logging_config import get_logger

logger = get_logger(__name__)


def _money_str(value: Money) -> str:
    """Render a Money value for citation/expected/actual text."""
    return f"{value.currency} {value.amount}"


class ArithmeticRule:
    """Check that quantity × unit_rate equals the printed line total."""

    name = "arithmetic_consistency"

    def evaluate(
        self, invoice: Invoice, contract: Contract
    ) -> list[Discrepancy]:
        """Flag lines whose printed total ≠ quantity × unit_rate."""
        tolerance = Decimal(str(get_settings().arithmetic_tolerance))
        findings: list[Discrepancy] = []
        for line in invoice.line_items:
            if not line.unit_rate.same_currency_as(line.line_total):
                raise RuleEvaluationError(
                    f"Line {line.line_no}: mixed currencies on a single line"
                )
            expected_total = (line.quantity * line.unit_rate.amount).quantize(
                Decimal("0.01")
            )
            difference = (line.line_total.amount - expected_total).copy_abs()
            if difference > tolerance:
                findings.append(
                    Discrepancy(
                        type=DiscrepancyType.ARITHMETIC_ERROR,
                        severity=Severity.HIGH,
                        description=(
                            f"Line {line.line_no} total does not equal "
                            f"quantity × unit rate."
                        ),
                        citation=(
                            f"Invoice {invoice.invoice_id}, line {line.line_no}"
                        ),
                        invoice_line_no=line.line_no,
                        expected=_money_str(
                            Money(
                                amount=expected_total,
                                currency=line.line_total.currency,
                            )
                        ),
                        actual=_money_str(line.line_total),
                        monetary_impact=Money(
                            amount=line.line_total.amount - expected_total,
                            currency=line.line_total.currency,
                        ),
                        confidence=0.99,
                    )
                )
        return findings


class RateMismatchRule:
    """Check billed unit rates against the contracted rate card."""

    name = "rate_mismatch"

    def evaluate(
        self, invoice: Invoice, contract: Contract
    ) -> list[Discrepancy]:
        """Flag lines billed above the contracted unit rate."""
        findings: list[Discrepancy] = []
        for line in invoice.line_items:
            entry = contract.rate_for(line.sku)
            if entry is None:
                continue  # handled by UncontractedItemRule
            contracted = entry.unit_rate
            if line.unit_rate.amount > contracted.amount:
                overcharge_per_unit = line.unit_rate.amount - contracted.amount
                findings.append(
                    Discrepancy(
                        type=DiscrepancyType.RATE_MISMATCH,
                        severity=Severity.HIGH,
                        description=(
                            f"Line {line.line_no} ({line.sku}) billed above "
                            f"the contracted unit rate."
                        ),
                        citation=(
                            f"Contract {contract.contract_id}, rate card SKU "
                            f"{entry.sku}"
                        ),
                        invoice_line_no=line.line_no,
                        expected=_money_str(contracted),
                        actual=_money_str(line.unit_rate),
                        monetary_impact=Money(
                            amount=overcharge_per_unit * line.quantity,
                            currency=line.unit_rate.currency,
                        ),
                        confidence=0.97,
                    )
                )
        return findings


class OutOfTermRule:
    """Check that the invoice date falls within the contract validity window."""

    name = "out_of_term"

    def evaluate(
        self, invoice: Invoice, contract: Contract
    ) -> list[Discrepancy]:
        """Flag invoices dated outside the contract's active window."""
        if contract.is_active_on(invoice.invoice_date):
            return []
        return [
            Discrepancy(
                type=DiscrepancyType.OUT_OF_TERM,
                severity=Severity.MEDIUM,
                description=(
                    "Invoice date falls outside the contract validity window."
                ),
                citation=(
                    f"Contract {contract.contract_id} valid "
                    f"{contract.valid_from}..{contract.valid_to}"
                ),
                expected=f"{contract.valid_from}..{contract.valid_to}",
                actual=str(invoice.invoice_date),
                confidence=0.95,
            )
        ]


class MissedVolumeDiscountRule:
    """Check that earned volume discounts were actually applied."""

    name = "missed_volume_discount"

    def evaluate(
        self, invoice: Invoice, contract: Contract
    ) -> list[Discrepancy]:
        """Flag lines where a volume discount was earned but not applied."""
        findings: list[Discrepancy] = []
        for line in invoice.line_items:
            entry = contract.rate_for(line.sku)
            if entry is None:
                continue
            discount = entry.applicable_discount(line.quantity)
            if discount <= 0:
                continue
            expected_unit = (
                entry.unit_rate.amount * (Decimal(1) - discount)
            ).quantize(Decimal("0.01"))
            if line.unit_rate.amount > expected_unit:
                impact = (line.unit_rate.amount - expected_unit) * line.quantity
                findings.append(
                    Discrepancy(
                        type=DiscrepancyType.MISSED_VOLUME_DISCOUNT,
                        severity=Severity.MEDIUM,
                        description=(
                            f"Line {line.line_no} ({line.sku}) qualified for a "
                            f"{discount:%} volume discount that was not applied."
                        ),
                        citation=(
                            f"Contract {contract.contract_id}, SKU {entry.sku} "
                            f"volume discount tiers"
                        ),
                        invoice_line_no=line.line_no,
                        expected=_money_str(
                            Money(
                                amount=expected_unit,
                                currency=entry.unit_rate.currency,
                            )
                        ),
                        actual=_money_str(line.unit_rate),
                        monetary_impact=Money(
                            amount=impact, currency=line.unit_rate.currency
                        ),
                        confidence=0.90,
                    )
                )
        return findings


class UncontractedItemRule:
    """Flag billed items that have no matching contract rate card."""

    name = "uncontracted_item"

    def evaluate(
        self, invoice: Invoice, contract: Contract
    ) -> list[Discrepancy]:
        """Flag invoice lines whose SKU is absent from the rate card."""
        findings: list[Discrepancy] = []
        for line in invoice.line_items:
            if contract.rate_for(line.sku) is None:
                findings.append(
                    Discrepancy(
                        type=DiscrepancyType.UNCONTRACTED_ITEM,
                        severity=Severity.LOW,
                        description=(
                            f"Line {line.line_no} bills SKU {line.sku}, which "
                            f"is not on the contract rate card."
                        ),
                        citation=(
                            f"Contract {contract.contract_id} rate card "
                            f"(SKU {line.sku} absent)"
                        ),
                        invoice_line_no=line.line_no,
                        actual=line.sku,
                        confidence=0.85,
                    )
                )
        return findings


def default_rules() -> list:
    """Return the default ordered set of rules for the engine.

    Returns:
        A list of rule instances. Order is stable for reproducible output.
    """
    return [
        ArithmeticRule(),
        RateMismatchRule(),
        MissedVolumeDiscountRule(),
        OutOfTermRule(),
        UncontractedItemRule(),
    ]
