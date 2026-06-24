"""Rules engine.

Runs a set of :class:`~clauseguard.rules.base.DiscrepancyRule` instances over an
invoice/contract pair and aggregates the findings.

Fault isolation is deliberate: if one rule raises, the engine logs it and
continues with the remaining rules rather than failing the whole reconciliation.
A single buggy or data-tripped rule must never take down a batch.
"""

from __future__ import annotations

from collections.abc import Iterable

from clauseguard.domain.models import Contract, Discrepancy, Invoice
from clauseguard.exceptions import RuleEvaluationError
from clauseguard.logging_config import get_logger
from clauseguard.rules.base import DiscrepancyRule
from clauseguard.rules.checks import default_rules

logger = get_logger(__name__)


class RulesEngine:
    """Aggregate deterministic discrepancy rules.

    Args:
        rules: The rules to run. Defaults to :func:`default_rules`.
    """

    def __init__(self, rules: Iterable[DiscrepancyRule] | None = None) -> None:
        self._rules: list[DiscrepancyRule] = (
            list(rules) if rules is not None else default_rules()
        )
        logger.debug(
            "RulesEngine initialised", extra={"rule_count": len(self._rules)}
        )

    @property
    def rule_names(self) -> list[str]:
        """Return the names of the registered rules, in execution order."""
        return [rule.name for rule in self._rules]

    def evaluate(
        self, invoice: Invoice, contract: Contract
    ) -> list[Discrepancy]:
        """Run every rule and return the combined discrepancies.

        Args:
            invoice: The invoice under review.
            contract: The governing contract.

        Returns:
            All discrepancies found, in rule order. A rule that raises is logged
            and skipped; it does not abort the others.
        """
        findings: list[Discrepancy] = []
        for rule in self._rules:
            try:
                rule_findings = rule.evaluate(invoice, contract)
            except RuleEvaluationError:
                logger.exception(
                    "Rule raised and was skipped",
                    extra={"rule": rule.name, "invoice_id": invoice.invoice_id},
                )
                continue
            except Exception:  # noqa: BLE001 - last-resort isolation boundary
                logger.exception(
                    "Unexpected error in rule; skipping",
                    extra={"rule": rule.name, "invoice_id": invoice.invoice_id},
                )
                continue
            logger.debug(
                "Rule evaluated",
                extra={"rule": rule.name, "findings": len(rule_findings)},
            )
            findings.extend(rule_findings)
        return findings
