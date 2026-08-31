"""CLI: run the evaluation harness over the built-in cases and print metrics.

Run with: ``python scripts/run_eval.py`` (from the project root).
"""

from __future__ import annotations

from clauseguard.evaluation.cases import BUILTIN_CASES
from clauseguard.evaluation.harness import EvaluationHarness


def main() -> None:
    """Evaluate the built-in cases and print a metrics table."""
    suite = EvaluationHarness().run_suite(BUILTIN_CASES)
    report = suite.report

    print(f"\nEvaluated {report.total_cases} cases\n")
    header = f"{'discrepancy type':<24}{'prec':>7}{'recall':>8}{'f1':>7}"
    print(header)
    print("-" * len(header))
    for name, m in report.per_type.items():
        print(f"{name:<24}{m.precision:>7.2f}{m.recall:>8.2f}{m.f1:>7.2f}")
    print("-" * len(header))
    print(
        f"{'OVERALL (micro)':<24}"
        f"{report.precision:>7.2f}{report.recall:>8.2f}{report.f1:>7.2f}"
    )
    print(
        f"\nTP={report.total_tp}  FP={report.total_fp}  FN={report.total_fn}\n"
    )

    # Surface any per-case misses/false-positives for quick debugging.
    for cr in suite.cases:
        if cr.false_positives or cr.false_negatives:
            print(f"[{cr.case_id}] FP={sorted(cr.false_positives)} "
                  f"FN={sorted(cr.false_negatives)}")


if __name__ == "__main__":
    main()