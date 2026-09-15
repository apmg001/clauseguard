"""API request/response schemas.

These are the transport contract (HTTP boundary). They are intentionally
separate from the domain models so the wire format can evolve independently of
the internal model. The reconcile endpoint accepts already-structured invoice
and contract data in Phase 1; document upload + extraction is wired in later
phases behind the same endpoint.
"""

from __future__ import annotations

import base64
import binascii

from pydantic import BaseModel, Field

from clauseguard.domain.models import Contract, Invoice, ReconciliationResult


class ReconcileRequest(BaseModel):
    """Request body for the reconcile endpoint."""

    invoice: Invoice
    candidate_contracts: list[Contract]


class ReconcileResponse(BaseModel):
    """Response body for the reconcile endpoint."""

    result: ReconciliationResult


class DocumentInput(BaseModel):
    """A single uploaded document as base64-encoded bytes.

    Attributes:
        content_base64: The document's bytes, base64-encoded (a PDF or UTF-8
            text). Base64 keeps the API a clean JSON contract while still
            carrying binary PDFs.
        source_ref: A filename/URI used for citations downstream.
    """

    content_base64: str
    source_ref: str = Field(default="uploaded-document")

    def to_bytes(self) -> bytes:
        """Decode the base64 content to raw bytes.

        Returns:
            The decoded document bytes.

        Raises:
            ValueError: If the content is not valid base64.
        """
        try:
            return base64.b64decode(self.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"invalid base64 for {self.source_ref}: {exc}") from exc


class ReconcileDocumentRequest(BaseModel):
    """Request body for the document reconcile endpoint."""

    invoice_document: DocumentInput
    contract_documents: list[DocumentInput]
