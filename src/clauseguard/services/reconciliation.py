"""Reconciliation use-case.

The application service that orchestrates one full reconciliation:

    match → run rules → score confidence → route → write audit record

It depends only on the **ports** (interfaces), never on concrete adapters, so
any stage can be replaced without touching this orchestration. This is the
single place the pipeline is composed; everything else is a swappable part.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from clauseguard.confidence.scorer import aggregate_impact, result_confidence, route
from clauseguard.domain.enums import DiscrepancyType, Severity
from clauseguard.domain.models import (
    Contract,
    Discrepancy,
    Invoice,
    Money,
    ReconciliationResult,
)
from clauseguard.exceptions import DeduplicationError, ReconciliationError
from clauseguard.logging_config import get_logger
from clauseguard.ports.audit import AuditLog
from clauseguard.ports.deduplication import DuplicateDetector
from clauseguard.ports.matching import InvoiceContractMatcher
from clauseguard.rules.engine import RulesEngine

logger = get_logger(__name__)


def _invoice_total(invoice: Invoice) -> Money | None:
    """Return the summed line total of ``invoice`` in the invoice currency.

    Only line totals matching the invoice's declared currency are summed;
    mixed-currency lines are excluded rather than combined into a meaningless
    figure (the currency-mismatch rule surfaces those separately).

    Args:
        invoice: The invoice to total.

    Returns:
        The summed :class:`Money`, or ``None`` if no line matches the currency.
    """
    amounts = [
        li.line_total.amount
        for li in invoice.line_items
        if li.line_total.currency == invoice.currency
    ]
    if not amounts:
        return None
    return Money(amount=sum(amounts, start=Decimal(0)), currency=invoice.currency)


class ReconciliationService:
    """Coordinate matching, rule evaluation, scoring, routing and audit.

    Args:
        matcher: Resolves the governing contract for an invoice.
        rules_engine: Runs deterministic discrepancy checks.
        audit_log: Append-only record of decisions.
        duplicate_detector: Optional stateful detector for resubmitted invoices.
            When omitted, duplicate detection is skipped (the deterministic
            rules and audit trail are unaffected).
    """

    def __init__(
        self,
        matcher: InvoiceContractMatcher,
        rules_engine: RulesEngine,
        audit_log: AuditLog,
        duplicate_detector: DuplicateDetector | None = None,
    ) -> None:
        self._matcher = matcher
        self._rules_engine = rules_engine
        self._audit_log = audit_log
        self._duplicate_detector = duplicate_detector

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

        # Duplicate detection is stateful and runs regardless of matching: a
        # resubmitted invoice is a finding even when no contract governs it.
        dedup_findings = self._detect_duplicate(invoice, log_ctx)

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
                discrepancies=dedup_findings,
                review_status=route(match.score, dedup_findings),
                total_impact=aggregate_impact(dedup_findings),
            )
            return self._finalise(result, log_ctx)

        contract = next(
            c for c in candidate_contracts if c.contract_id == match.contract_id
        )
        discrepancies = dedup_findings + tuple(
            self._rules_engine.evaluate(invoice, contract)
        )

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

    def _detect_duplicate(
        self, invoice: Invoice, log_ctx: dict
    ) -> tuple[Discrepancy, ...]:
        """Check the invoice against the duplicate store, if one is configured.

        Fault-isolated by design: a failure of the duplicate store must never
        abort an otherwise-valid reconciliation, so a :class:`DeduplicationError`
        is logged and treated as "not a duplicate" rather than propagated.

        Args:
            invoice: The invoice being reconciled.
            log_ctx: Logging context.

        Returns:
            A one-tuple containing a ``DUPLICATE_INVOICE`` discrepancy if the
            invoice was seen before, otherwise an empty tuple.
        """
        if self._duplicate_detector is None:
            return ()
        try:
            original_id = self._duplicate_detector.check_and_register(invoice)
        except DeduplicationError:
            logger.exception("Duplicate check failed; treating as new", extra=log_ctx)
            return ()
        if original_id is None:
            return ()

        return (
            Discrepancy(
                type=DiscrepancyType.DUPLICATE_INVOICE,
                severity=Severity.HIGH,
                description=(
                    f"Invoice {invoice.invoice_id} duplicates previously seen "
                    f"invoice {original_id} from the same vendor; paying it "
                    "would double-pay the original."
                ),
                citation=f"Previously recorded invoice: {original_id}",
                expected=f"no prior invoice {invoice.invoice_id}",
                actual=f"already recorded as {original_id}",
                monetary_impact=_invoice_total(invoice),
                confidence=1.0,
            ),
        )

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
