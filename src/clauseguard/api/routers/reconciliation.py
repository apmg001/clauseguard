"""Reconciliation router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from clauseguard.api.dependencies import (
    get_document_reconciliation_service,
    get_reconciliation_service,
)
from clauseguard.api.schemas import (
    ReconcileDocumentRequest,
    ReconcileRequest,
    ReconcileResponse,
)
from clauseguard.exceptions import (
    ExtractionError,
    IngestionError,
    ReconciliationError,
)
from clauseguard.logging_config import get_logger
from clauseguard.services.document_reconciliation import (
    DocumentPayload,
    DocumentReconciliationService,
)
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


@router.post("/reconcile-document", response_model=ReconcileResponse)
def reconcile_document(
    request: ReconcileDocumentRequest,
    service: DocumentReconciliationService = Depends(
        get_document_reconciliation_service
    ),
) -> ReconcileResponse:
    """Reconcile a raw invoice document against raw contract documents.

    Decodes the base64 documents, parses and extracts them, then reconciles.

    Args:
        request: Base64-encoded invoice and candidate contract documents.
        service: Injected document reconciliation service.

    Returns:
        The reconciliation result.

    Raises:
        HTTPException: 400 on invalid base64; 422 if a document cannot be
            parsed/extracted or reconciliation cannot complete.
    """
    try:
        invoice_doc = DocumentPayload(
            content=request.invoice_document.to_bytes(),
            source_ref=request.invoice_document.source_ref,
        )
        contract_docs = [
            DocumentPayload(content=c.to_bytes(), source_ref=c.source_ref)
            for c in request.contract_documents
        ]
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    try:
        result = service.reconcile_documents(invoice_doc, contract_docs)
    except (IngestionError, ExtractionError, ReconciliationError) as exc:
        logger.warning("Document reconciliation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return ReconcileResponse(result=result)
