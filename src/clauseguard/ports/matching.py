"""Port: invoice-to-contract matching.

Matching is a record-linkage problem. Phase 1 ships a heuristic adapter; Phase 3
swaps in a trained classical-ML classifier behind this identical interface — no
caller changes required.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from clauseguard.domain.models import Contract, Invoice, MatchResult


@runtime_checkable
class InvoiceContractMatcher(Protocol):
    """Resolve which contract governs an invoice."""

    def match(
        self, invoice: Invoice, candidates: Sequence[Contract]
    ) -> MatchResult:
        """Select the governing contract for ``invoice``.

        Args:
            invoice: The invoice to match.
            candidates: Contracts in scope.

        Returns:
            A :class:`MatchResult`; ``contract_id`` is None when no candidate
            clears the acceptance threshold.

        Raises:
            NoCandidateContractsError: If ``candidates`` is empty.
        """
        ...
