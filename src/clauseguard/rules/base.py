"""Rules engine: rule contract.

Each discrepancy check is an independent, deterministic :class:`DiscrepancyRule`.
Rules are pure functions of their inputs (no I/O, no randomness) so the engine
is fully reproducible — a hard requirement for audit-grade output. New checks
are added by implementing this protocol and registering them with the engine;
nothing else changes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from clauseguard.domain.models import Contract, Discrepancy, Invoice


@runtime_checkable
class DiscrepancyRule(Protocol):
    """A single deterministic discrepancy check."""

    name: str

    def evaluate(
        self, invoice: Invoice, contract: Contract
    ) -> list[Discrepancy]:
        """Evaluate the rule against one invoice/contract pair.

        Args:
            invoice: The invoice under review.
            contract: The governing contract.

        Returns:
            Zero or more discrepancies found by this rule.

        Raises:
            RuleEvaluationError: If the rule cannot evaluate the inputs.
        """
        ...
