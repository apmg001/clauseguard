"""Confidence scoring and review routing.

Phase 1 ships a transparent, deterministic scorer: the result-level confidence
is the minimum discrepancy confidence (the weakest link), combined with the
match score. Routing compares that against the configured review threshold.

This is deliberately simple and interpretable. Phase 3 replaces the internals
with a calibrated model (Platt/isotonic) behind the same function signatures, so
callers and the API contract do not change.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from clauseguard.config import get_settings
from clauseguard.domain.enums import ReviewStatus
from clauseguard.domain.models import Discrepancy, Money


def aggregate_impact(discrepancies: Sequence[Discrepancy]) -> Money | None:
    """Sum the monetary impact across discrepancies sharing a currency.

    Args:
        discrepancies: The discrepancies to total.

    Returns:
        The summed :class:`Money`, or None if there are no monetary impacts.
        Mixed currencies are not summed here (Phase 1 keeps this simple); only
        impacts matching the first seen currency are aggregated.
    """
    impacts = [d.monetary_impact for d in discrepancies if d.monetary_impact]
    if not impacts:
        return None
    currency = impacts[0].currency
    total = sum(
        (m.amount for m in impacts if m.currency == currency), start=Decimal(0)
    )
    return Money(amount=total, currency=currency)


def result_confidence(
    match_score: float, discrepancies: Sequence[Discrepancy]
) -> float:
    """Compute an overall confidence for a reconciliation result.

    Args:
        match_score: Confidence that the right contract was selected.
        discrepancies: The discrepancies detected.

    Returns:
        A confidence in ``[0, 1]``: the match score when no discrepancies were
        found, otherwise the product of the match score and the weakest
        discrepancy confidence.
    """
    if not discrepancies:
        return match_score
    weakest = min(d.confidence for d in discrepancies)
    return round(match_score * weakest, 4)


def route(
    match_score: float, discrepancies: Sequence[Discrepancy]
) -> ReviewStatus:
    """Decide how a reconciliation result should be routed.

    Args:
        match_score: Confidence in the contract match.
        discrepancies: The detected discrepancies.

    Returns:
        ``AUTO_CLEARED`` if nothing was found at acceptable confidence,
        ``NEEDS_REVIEW`` if confidence is below the configured threshold,
        otherwise ``AUTO_REPORTED``.
    """
    threshold = get_settings().review_confidence_threshold
    confidence = result_confidence(match_score, discrepancies)
    if confidence < threshold:
        return ReviewStatus.NEEDS_REVIEW
    if not discrepancies:
        return ReviewStatus.AUTO_CLEARED
    return ReviewStatus.AUTO_REPORTED
