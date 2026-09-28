"""Adapter: in-memory duplicate-invoice detector (Phase 1).

Fingerprints each invoice and remembers the fingerprints it has seen so a
resubmission of the same invoice can be flagged. Held in memory for development
and single-process deployments; a shared, durable store (Redis, a database, or a
tamper-evident ledger) slots in behind the :class:`DuplicateDetector` port with
no change to the reconciliation service.

The fingerprint is deliberately conservative — vendor plus invoice id — so that
a genuinely re-sent invoice is caught while two distinct invoices that merely
share a total are not. Content-level fingerprinting (line signature, total) is a
documented roadmap extension; the port already accommodates it.
"""

from __future__ import annotations

import hashlib
import threading

from clauseguard.domain.models import Invoice
from clauseguard.logging_config import get_logger

logger = get_logger(__name__)


def _fingerprint(invoice: Invoice) -> str:
    """Return a stable fingerprint for ``invoice``.

    Vendor name is normalised (trimmed, case-folded) so trivial formatting
    differences do not defeat detection; the invoice id is likewise trimmed and
    case-folded. The pair is hashed to a fixed-width, opaque token.

    Args:
        invoice: The invoice to fingerprint.

    Returns:
        A hex SHA-256 digest identifying the invoice's identity.
    """
    vendor = invoice.vendor_name.strip().casefold()
    invoice_id = invoice.invoice_id.strip().casefold()
    raw = f"{vendor}\x1f{invoice_id}".encode()
    return hashlib.sha256(raw).hexdigest()


class InMemoryDuplicateDetector:
    """Thread-safe, in-memory duplicate-invoice detector.

    Maps each seen fingerprint to the ``invoice_id`` first recorded under it, so
    a flagged duplicate can cite the original occurrence. A lock makes
    ``check_and_register`` atomic, so concurrent batch workers cannot both treat
    the same invoice as new.
    """

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}
        self._lock = threading.Lock()

    def check_and_register(self, invoice: Invoice) -> str | None:
        """Atomically test whether ``invoice`` is a duplicate, then record it.

        Args:
            invoice: The invoice being reconciled.

        Returns:
            The ``invoice_id`` of the previously seen invoice this one
            duplicates, or ``None`` if it is new (and now registered).
        """
        fingerprint = _fingerprint(invoice)
        with self._lock:
            original = self._seen.get(fingerprint)
            if original is not None:
                logger.info(
                    "Duplicate invoice detected",
                    extra={
                        "invoice_id": invoice.invoice_id,
                        "original_invoice_id": original,
                    },
                )
                return original
            self._seen[fingerprint] = invoice.invoice_id
            return None
