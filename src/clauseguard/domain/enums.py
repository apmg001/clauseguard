"""Domain enumerations.

Closed value sets used across the domain. Keeping these as enums (rather than
free strings) makes invalid states unrepresentable and gives the rules engine
and API a stable contract.
"""

from __future__ import annotations

from enum import Enum


class DiscrepancyType(str, Enum):
    """Categories of discrepancy the reconciliation engine can detect."""

    RATE_MISMATCH = "rate_mismatch"
    ARITHMETIC_ERROR = "arithmetic_error"
    OUT_OF_TERM = "out_of_term"
    MISSED_VOLUME_DISCOUNT = "missed_volume_discount"
    DUPLICATE_INVOICE = "duplicate_invoice"
    UNCLAIMED_SLA_PENALTY = "unclaimed_sla_penalty"
    UNCONTRACTED_ITEM = "uncontracted_item"


class Severity(str, Enum):
    """Business severity of a discrepancy, independent of detector confidence."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewStatus(str, Enum):
    """Routing outcome for a reconciliation result."""

    AUTO_CLEARED = "auto_cleared"          # no discrepancies found
    AUTO_REPORTED = "auto_reported"        # discrepancies found, high confidence
    NEEDS_REVIEW = "needs_review"          # low-confidence, route to a human


class MatchMethod(str, Enum):
    """How an invoice was matched to a contract (for auditability)."""

    EXACT_VENDOR = "exact_vendor"
    FUZZY_VENDOR = "fuzzy_vendor"
    UNMATCHED = "unmatched"
