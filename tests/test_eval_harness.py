"""End-to-end tests for the evaluation harness on the built-in cases."""

from __future__ import annotations

from clauseguard.evaluation.cases import BUILTIN_CASES
from clauseguard.evaluation.harness import EvaluationHarness
from clauseguard.evaluation.manifest import EvalCase, SeededError
from clauseguard.domain.enums import DiscrepancyType


def test_builtin_cases_score_perfectly() -> None:
    suite = EvaluationHarness().run_suite(BUILTIN_CASES)
    assert suite.report.precision == 1.0
    assert suite.report.recall == 1.0
    assert suite.report.total_fp == 0
    assert suite.report.total_fn == 0


def test_clean_case_yields_no_findings() -> None:
    clean = next(c for c in BUILTIN_CASES if c.case_id == "clean")
    result = EvaluationHarness().run_case(clean)
    assert result.detected == set()


def test_harness_reports_a_missed_error() -> None:
    case = EvalCase(
        case_id="unimplemented",
        invoice_text=(
            "Invoice-ID: INV-1\nVendor: Acme\nDate: 2026-05-01\nCurrency: INR\n\n"
            "Line | SKU | Description | Qty | Unit-Rate | Line-Total\n"
            "1 | A-1 | Thing | 1 | 10.00 | 10.00\n"
        ),
        contract_text=(
            "Contract-ID: C-1\nVendor: Acme\nValid-From: 2026-01-01\n"
            "Valid-To: 2026-12-31\nCurrency: INR\n\n"
            "SKU | Description | Unit-Rate | Volume-Discounts\nA-1 | Thing | 10.00 |\n"
        ),
        seeded_errors=(
            SeededError(type=DiscrepancyType.DUPLICATE_INVOICE, line_no=None),
        ),
    )
    result = EvaluationHarness().run_case(case)
    assert ("duplicate_invoice", None) in result.false_negatives
    assert result.detected == set()
