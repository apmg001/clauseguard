"""Precision / recall / F1 metrics for discrepancy detection.

Pure and domain-free: it operates on ``(type, line_no)`` finding keys, not on
domain objects, so it is trivially unit-testable and reusable for any labelled
set. A detected finding matches a seeded one only when *both* the discrepancy
type and the line number agree — line-level scoring, which is stricter and more
honest than matching on type alone.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

# A finding is identified by its discrepancy type and (optional) invoice line.
FindingKey = tuple[str, int | None]


def _f1(precision: float, recall: float) -> float:
    """Harmonic mean of precision and recall (0.0 when both are 0)."""
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


@dataclass(frozen=True)
class TypeMetrics:
    """Counts and derived metrics for a single discrepancy type.

    Attributes:
        discrepancy_type: The type these counts describe.
        true_positives: Seeded findings correctly detected.
        false_positives: Detected findings that were not seeded.
        false_negatives: Seeded findings that were missed.
    """

    discrepancy_type: str
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float:
        """TP / (TP + FP); 1.0 when nothing was detected for this type."""
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 1.0

    @property
    def recall(self) -> float:
        """TP / (TP + FN); 1.0 when nothing was seeded for this type."""
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 1.0

    @property
    def f1(self) -> float:
        """Harmonic mean of precision and recall."""
        return _f1(self.precision, self.recall)


@dataclass(frozen=True)
class EvalReport:
    """Aggregated evaluation result.

    Attributes:
        per_type: Metrics keyed by discrepancy type.
        total_cases: Number of cases evaluated.
    """

    per_type: dict[str, TypeMetrics] = field(default_factory=dict)
    total_cases: int = 0

    @property
    def total_tp(self) -> int:
        return sum(m.true_positives for m in self.per_type.values())

    @property
    def total_fp(self) -> int:
        return sum(m.false_positives for m in self.per_type.values())

    @property
    def total_fn(self) -> int:
        return sum(m.false_negatives for m in self.per_type.values())

    @property
    def precision(self) -> float:
        """Micro-averaged precision across all types."""
        denom = self.total_tp + self.total_fp
        return self.total_tp / denom if denom else 1.0

    @property
    def recall(self) -> float:
        """Micro-averaged recall across all types."""
        denom = self.total_tp + self.total_fn
        return self.total_tp / denom if denom else 1.0

    @property
    def f1(self) -> float:
        """Micro-averaged F1 across all types."""
        return _f1(self.precision, self.recall)


def compute_metrics(
    results: Iterable[tuple[set[FindingKey], set[FindingKey]]],
    *,
    total_cases: int | None = None,
) -> EvalReport:
    """Aggregate per-case (detected, seeded) finding sets into an EvalReport.

    Args:
        results: One ``(detected, seeded)`` pair per case, each a set of
            ``(type, line_no)`` keys.
        total_cases: Optional explicit case count; inferred from ``results`` when
            omitted (note: passing a generator makes inference impossible, so
            supply this if ``results`` is not a sized collection).

    Returns:
        The aggregated :class:`EvalReport`.
    """
    tp: dict[str, int] = {}
    fp: dict[str, int] = {}
    fn: dict[str, int] = {}
    case_count = 0

    for detected, seeded in results:
        case_count += 1
        for key in detected & seeded:
            tp[key[0]] = tp.get(key[0], 0) + 1
        for key in detected - seeded:
            fp[key[0]] = fp.get(key[0], 0) + 1
        for key in seeded - detected:
            fn[key[0]] = fn.get(key[0], 0) + 1

    all_types = set(tp) | set(fp) | set(fn)
    per_type = {
        t: TypeMetrics(
            discrepancy_type=t,
            true_positives=tp.get(t, 0),
            false_positives=fp.get(t, 0),
            false_negatives=fn.get(t, 0),
        )
        for t in sorted(all_types)
    }
    return EvalReport(
        per_type=per_type,
        total_cases=total_cases if total_cases is not None else case_count,
    )