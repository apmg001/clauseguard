"""Adapter: heuristic invoice-to-contract matcher (Phase 1).

Matches on vendor name using exact comparison first, then fuzzy similarity
(``rapidfuzz`` when available, with a stdlib fallback). Phase 3 replaces this
with a trained classical-ML classifier over engineered features, behind the
same :class:`InvoiceContractMatcher` port.
"""

from __future__ import annotations

from collections.abc import Sequence

from clauseguard.config import get_settings
from clauseguard.domain.enums import MatchMethod
from clauseguard.domain.models import Contract, Invoice, MatchResult
from clauseguard.exceptions import NoCandidateContractsError
from clauseguard.logging_config import get_logger

logger = get_logger(__name__)


def _similarity(a: str, b: str) -> float:
    """Return a name similarity score in [0, 1]."""
    a_norm, b_norm = a.strip().lower(), b.strip().lower()
    if a_norm == b_norm:
        return 1.0
    try:
        from rapidfuzz import fuzz  # type: ignore

        return fuzz.token_sort_ratio(a_norm, b_norm) / 100.0
    except ImportError:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, a_norm, b_norm).ratio()


class HeuristicMatcher:
    """Match invoices to contracts by vendor-name similarity."""

    def match(
        self, invoice: Invoice, candidates: Sequence[Contract]
    ) -> MatchResult:
        """Select the best contract for ``invoice`` by vendor similarity.

        Args:
            invoice: The invoice to match.
            candidates: Contracts in scope.

        Returns:
            A :class:`MatchResult`; unmatched if no candidate clears the
            configured acceptance threshold.

        Raises:
            NoCandidateContractsError: If ``candidates`` is empty.
        """
        if not candidates:
            raise NoCandidateContractsError(
                f"No candidate contracts for invoice {invoice.invoice_id}"
            )

        threshold = get_settings().match_accept_threshold
        best: Contract | None = None
        best_score = 0.0
        for contract in candidates:
            score = _similarity(invoice.vendor_name, contract.vendor_name)
            if score > best_score:
                best, best_score = contract, score

        if best is None or best_score < threshold:
            logger.info(
                "No contract cleared match threshold",
                extra={
                    "invoice_id": invoice.invoice_id,
                    "best_score": round(best_score, 3),
                    "threshold": threshold,
                },
            )
            return MatchResult(
                invoice_id=invoice.invoice_id,
                contract_id=None,
                score=best_score,
                method=MatchMethod.UNMATCHED,
            )

        method = (
            MatchMethod.EXACT_VENDOR if best_score == 1.0 else MatchMethod.FUZZY_VENDOR
        )
        return MatchResult(
            invoice_id=invoice.invoice_id,
            contract_id=best.contract_id,
            score=best_score,
            method=method,
        )
