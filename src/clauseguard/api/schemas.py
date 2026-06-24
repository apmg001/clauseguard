"""API request/response schemas.

These are the transport contract (HTTP boundary). They are intentionally
separate from the domain models so the wire format can evolve independently of
the internal model. The reconcile endpoint accepts already-structured invoice
and contract data in Phase 1; document upload + extraction is wired in later
phases behind the same endpoint.
"""

from __future__ import annotations

from pydantic import BaseModel

from clauseguard.domain.models import Contract, Invoice, ReconciliationResult


class ReconcileRequest(BaseModel):
    """Request body for the reconcile endpoint."""

    invoice: Invoice
    candidate_contracts: list[Contract]


class ReconcileResponse(BaseModel):
    """Response body for the reconcile endpoint."""

    result: ReconciliationResult
