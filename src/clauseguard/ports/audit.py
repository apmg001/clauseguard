"""Port: audit log.

Auditability is the product. Every reconciliation writes an append-only record.
Phase 1 ships an in-memory adapter; later phases swap in a database-backed,
immutable store behind this interface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from clauseguard.domain.models import ReconciliationResult


@runtime_checkable
class AuditLog(Protocol):
    """Append-only record of reconciliation decisions."""

    def record(self, result: ReconciliationResult) -> str:
        """Persist a reconciliation result and return its audit id.

        Args:
            result: The result to record.

        Returns:
            The identifier of the written audit record.

        Raises:
            AuditError: If the record cannot be written.
        """
        ...

    def get(self, audit_id: str) -> ReconciliationResult | None:
        """Return a recorded result by id, or None if absent."""
        ...
