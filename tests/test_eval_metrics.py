"""Tests for the pure evaluation metrics.

No pipeline, no I/O — just the precision/recall/F1 arithmetic over finding sets.
"""

from __future__ import annotations

from clauseguard.evaluation.metrics import TypeMetrics, compute_metrics


def test_perfect_detection() -> None:
    detected = {("rate_mismatch", 1), ("uncontracted_item", 2)}
    seeded = {("rate_mismatch", 1), ("uncontracted_item", 2)}
    report = compute_metrics([(detected, seeded)])
    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.f1 == 1.0
    assert report.total_fp == 0 and report.total_fn == 0


def test_false_negative_lowers_recall() -> None:
    detected = {("rate_mismatch", 1)}
    seeded = {("rate_mismatch", 1), ("out_of_term", None)}
    report = compute_metrics([(detected, seeded)])
    assert report.recall == 0.5          # 1 of 2 seeded found
    assert report.precision == 1.0       # nothing spurious detected
    assert report.per_type["out_of_term"].false_negatives == 1


def test_false_positive_lowers_precision() -> None:
    detected = {("rate_mismatch", 1), ("arithmetic_error", 1)}
    seeded = {("rate_mismatch", 1)}
    report = compute_metrics([(detected, seeded)])
    assert report.precision == 0.5       # 1 of 2 detected was real
    assert report.recall == 1.0
    assert report.per_type["arithmetic_error"].false_positives == 1


def test_line_number_must_match() -> None:
    # Right type, wrong line: counts as both a FP (line 2) and FN (line 1).
    detected = {("rate_mismatch", 2)}
    seeded = {("rate_mismatch", 1)}
    report = compute_metrics([(detected, seeded)])
    m = report.per_type["rate_mismatch"]
    assert m.true_positives == 0
    assert m.false_positives == 1
    assert m.false_negatives == 1


def test_clean_case_no_findings_is_perfect() -> None:
    report = compute_metrics([(set(), set())])
    assert report.precision == 1.0 and report.recall == 1.0
    assert report.total_tp == 0


def test_type_metrics_derived_values() -> None:
    m = TypeMetrics(
        discrepancy_type="x", true_positives=3, false_positives=1, false_negatives=1
    )
    assert m.precision == 0.75
    assert m.recall == 0.75
    assert round(m.f1, 2) == 0.75