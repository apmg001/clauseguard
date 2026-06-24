"""Dependency wiring (composition root).

FastAPI dependency providers assemble concrete adapters into the
:class:`ReconciliationService`. This is the *only* module that knows which
concrete implementations are in use; swapping an adapter (e.g. a DB-backed audit
log, or the ML matcher) is a one-line change here. The audit log is a singleton
so records persist across requests within the process.
"""

from __future__ import annotations

from functools import lru_cache

from clauseguard.adapters.audit.in_memory import InMemoryAuditLog
from clauseguard.adapters.matching.heuristic import HeuristicMatcher
from clauseguard.ports.audit import AuditLog
from clauseguard.rules.engine import RulesEngine
from clauseguard.services.reconciliation import ReconciliationService


@lru_cache(maxsize=1)
def get_audit_log() -> AuditLog:
    """Return the process-wide audit log singleton."""
    return InMemoryAuditLog()


def get_reconciliation_service() -> ReconciliationService:
    """Assemble and return a :class:`ReconciliationService`."""
    return ReconciliationService(
        matcher=HeuristicMatcher(),
        rules_engine=RulesEngine(),
        audit_log=get_audit_log(),
    )
