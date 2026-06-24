"""Custom exception hierarchy for ClauseGuard.

All exceptions raised intentionally by the application inherit from
:class:`ClauseGuardError`. This lets callers catch a single base type at
process boundaries (e.g. the API layer) while still allowing narrow,
specific handling deeper in the stack.

Never raise bare ``Exception`` and never ``except Exception`` to swallow
errors silently — use the most specific type that fits.
"""

from __future__ import annotations


class ClauseGuardError(Exception):
    """Base class for every error raised by the application."""


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #
class IngestionError(ClauseGuardError):
    """Base class for document ingestion failures."""


class UnsupportedDocumentError(IngestionError):
    """Raised when a document's format/type cannot be parsed."""


class DocumentParseError(IngestionError):
    """Raised when a document is recognised but cannot be read."""


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
class ExtractionError(ClauseGuardError):
    """Base class for term/field extraction failures."""


class ContractExtractionError(ExtractionError):
    """Raised when contract terms cannot be extracted."""


class InvoiceExtractionError(ExtractionError):
    """Raised when invoice fields/line items cannot be extracted."""


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #
class MatchingError(ClauseGuardError):
    """Base class for invoice-to-contract matching failures."""


class NoCandidateContractsError(MatchingError):
    """Raised when matching is attempted with no candidate contracts."""


# --------------------------------------------------------------------------- #
# Rules / reconciliation
# --------------------------------------------------------------------------- #
class RuleEvaluationError(ClauseGuardError):
    """Raised when a discrepancy rule fails to evaluate."""


class ReconciliationError(ClauseGuardError):
    """Raised when the reconciliation use-case cannot complete."""


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
class AuditError(ClauseGuardError):
    """Raised when an audit record cannot be written or read."""


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
class ConfigurationError(ClauseGuardError):
    """Raised when application configuration is invalid."""
