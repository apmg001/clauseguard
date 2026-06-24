"""Adapter: in-memory append-only audit log (Phase 1).

A process-local, append-only store keyed by a generated audit id. Suitable for
development and tests. Later phases swap in a database-backed, tamper-evident
store behind the same :class:`AuditLog` port.
"""

from __future__ import annotations

import uuid

from clauseguard.domain.models import ReconciliationResult
from clauseguard.exceptions import AuditError
from clauseguard.logging_config import get_logger

logger = get_logger(__name__)


class InMemoryAuditLog:
    """Append-only audit log held in memory."""

    def __init__(self) -> None:
        self._store: dict[str, ReconciliationResult] = {}

    def record(self, result: ReconciliationResult) -> str:
        """Persist ``result`` and return a new audit id.

        Raises:
            AuditError: If the generated id unexpectedly collides.
        """
        audit_id = uuid.uuid4().hex
        if audit_id in self._store:  # practically impossible; defensive
            raise AuditError("Audit id collision")
        self._store[audit_id] = result
        logger.info(
            "Audit record written",
            extra={"audit_id": audit_id, "invoice_id": result.invoice_id},
        )
        return audit_id

    def get(self, audit_id: str) -> ReconciliationResult | None:
        """Return the recorded result for ``audit_id`` or None."""
        return self._store.get(audit_id)
