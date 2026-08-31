"""Evaluation harness.

Measures how well the reconciliation engine recovers *known* planted errors.
Each :class:`~clauseguard.evaluation.manifest.EvalCase` pairs invoice + contract
text with a manifest of seeded discrepancies (ground truth); the harness runs
the full pipeline, compares what it detected against what was planted, and
reports precision / recall / F1 — overall and per discrepancy type.

The metric logic is pure and domain-free; the harness wires the real pipeline;
the built-in cases make it runnable with zero setup. The same harness will
measure future, harder cases (hardened extraction, OCR output, real documents)
without changing.
"""