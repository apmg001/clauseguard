"""Reconciliation use-case.

The application service that orchestrates one full reconciliation:

    match → run rules → score confidence → route → write audit record

It depends only on the **ports** (interfaces), never on concrete adapters, so
any stage can be replaced without touching this orchestration. This is the
single place the pipeline is composed; everything else is a swappable part.
"""

from __future__ import annotations

from collections.abc import Sequence

from clauseguard.confidence.scorer import aggregate_impact, result_confidence, route
from clauseguard.domain.models import Contract, Invoice, ReconciliationResult
from clauseguard.exceptions import ReconciliationError
from clauseguard.logging_config import get_logger
from clauseguard.ports.audit import AuditLog
from clauseguard.ports.matching import InvoiceContractMatcher
from clauseguard.rules.engine import RulesEngine

logger = get_logger(__name__)


class ReconciliationService:
    """Coordinate matching, rule evaluation, scoring, routing and audit.

    Args:
        matcher: Resolves the governing contract for an invoice.
        rules_engine: Runs deterministic discrepancy checks.
        audit_log: Append-only record of decisions.
    """

    def __init__(
        self,
        matcher: InvoiceContractMatcher,
        rules_engine: RulesEngine,
        audit_log: AuditLog,
    ) -> None:
        self._matcher = matcher
        self._rules_engine = rules_engine
        self._audit_log = audit_log

    def reconcile(
        self, invoice: Invoice, candidate_contracts: Sequence[Contract]
    ) -> ReconciliationResult:
        """Reconcile one invoice against its candidate contracts.

        Args:
            invoice: The invoice to reconcile.
            candidate_contracts: Contracts in scope for matching.

        Returns:
            The :class:`ReconciliationResult`, including an audit id.

        Raises:
            ReconciliationError: If reconciliation cannot complete (e.g. no
                candidate contracts, or the audit record cannot be written).
        """
        log_ctx = {"invoice_id": invoice.invoice_id}
        logger.info("Reconciliation started", extra=log_ctx)

        try:
            match = self._matcher.match(invoice, candidate_contracts)
        except Exception as exc:
            raise ReconciliationError(
                f"Matching failed for invoice {invoice.invoice_id}: {exc}"
            ) from exc

        if not match.is_matched:
            # No governing contract — record and route to review, do not invent one.
            result = ReconciliationResult(
                invoice_id=invoice.invoice_id,
                contract_id=None,
                match_score=match.score,
                discrepancies=(),
                review_status=route(match.score, ()),
            )
            return self._finalise(result, log_ctx)

        contract = next(
            c for c in candidate_contracts if c.contract_id == match.contract_id
        )
        discrepancies = tuple(self._rules_engine.evaluate(invoice, contract))

        result = ReconciliationResult(
            invoice_id=invoice.invoice_id,
            contract_id=contract.contract_id,
            match_score=match.score,
            discrepancies=discrepancies,
            review_status=route(match.score, discrepancies),
            total_impact=aggregate_impact(discrepancies),
        )
        logger.info(
            "Reconciliation evaluated",
            extra={
                **log_ctx,
                "discrepancies": len(discrepancies),
                "confidence": result_confidence(match.score, discrepancies),
                "status": result.review_status.value,
            },
        )
        return self._finalise(result, log_ctx)

    def _finalise(
        self, result: ReconciliationResult, log_ctx: dict
    ) -> ReconciliationResult:
        """Write the audit record and return the result with its audit id.

        Args:
            result: The result to persist.
            log_ctx: Logging context.

        Returns:
            A copy of ``result`` carrying the written ``audit_id``.

        Raises:
            ReconciliationError: If the audit record cannot be written.
        """
        try:
            audit_id = self._audit_log.record(result)
        except Exception as exc:
            raise ReconciliationError(
                f"Audit write failed for invoice {result.invoice_id}: {exc}"
            ) from exc
        return result.model_copy(update={"audit_id": audit_id})
