"""Port: duplicate-invoice detection.

Duplicate detection is a *stateful* concern: deciding whether an invoice has been
seen before requires memory of previously processed invoices. That makes it a
deliberately poor fit for the pure, reproducible :mod:`clauseguard.rules` engine,
whose rules must be side-effect-free functions of a single invoice/contract pair.

It therefore lives behind its own port, invoked by the reconciliation service.
Phase 1 ships an in-memory adapter; a database- or ledger-backed store (shared
across processes, tamper-evident) slots in behind this same interface with no
change to the service.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from clauseguard.domain.models import Invoice


@runtime_checkable
class DuplicateDetector(Protocol):
    """Records seen invoices and reports resubmissions.

    Implementations MUST be safe to call once per invoice in a reconciliation
    run. The single ``check_and_register`` operation is intended to be atomic so
    that concurrent batch workers cannot both miss a duplicate through a
    check-then-register race.
    """

    def check_and_register(self, invoice: Invoice) -> str | None:
        """Atomically test whether ``invoice`` is a duplicate, then record it.

        Args:
            invoice: The invoice being reconciled.

        Returns:
            The identifier of the previously seen invoice this one duplicates,
            or ``None`` if this is the first time the invoice has been seen (in
            which case it is now registered).

        Raises:
            DeduplicationError: If the duplicate store cannot be read or written.
        """
        ...
