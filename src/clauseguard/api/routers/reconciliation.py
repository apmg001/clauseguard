"""Reconciliation router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from clauseguard.api.dependencies import get_reconciliation_service
from clauseguard.api.schemas import ReconcileRequest, ReconcileResponse
from clauseguard.exceptions import ReconciliationError
from clauseguard.logging_config import get_logger
from clauseguard.services.reconciliation import ReconciliationService

logger = get_logger(__name__)
router = APIRouter(prefix="/v1", tags=["reconciliation"])


@router.post("/reconcile", response_model=ReconcileResponse)
def reconcile(
    request: ReconcileRequest,
    service: ReconciliationService = Depends(get_reconciliation_service),
) -> ReconcileResponse:
    """Reconcile one invoice against candidate contracts.

    Args:
        request: The invoice and candidate contracts.
        service: Injected reconciliation service.

    Returns:
        The reconciliation result.

    Raises:
        HTTPException: 422 if reconciliation cannot complete.
    """
    try:
        result = service.reconcile(
            request.invoice, request.candidate_contracts
        )
    except ReconciliationError as exc:
        logger.warning("Reconciliation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return ReconcileResponse(result=result)
