# CLAUDE.md — ClauseGuard

Standing instructions for Claude Code. Read this on every session. The full
design lives in `BUILD_BRIEF.md`; this file governs *how* the code is written.

---

## What this project is

Audit-grade AI agent for **contract-to-invoice reconciliation and spend-leakage
detection**, deployed **privacy-first on a self-hosted GPU (NVIDIA L40S, 48GB)**.
It checks each invoice against its governing contract, flags discrepancies with
**clause-cited proof and calibrated confidence**, routes low-confidence cases to
a human, and writes an **immutable audit log**. See `BUILD_BRIEF.md` for the
full architecture, algorithm-per-stage table, module layout, and build order.

---

## Non-negotiable architecture rules

1. **Deterministic by default; LLM only for genuine language ambiguity.**
2. **Never use an LLM for arithmetic, rule evaluation, or duplicate detection.**
   These must be deterministic and reproducible — audit output cannot depend on
   a stochastic model.
3. **Matching is classical record-linkage** (trained classifier over engineered
   features), not an LLM call.
4. **Anomaly detection and confidence calibration are classical ML** (Isolation
   Forest/LOF; Platt/isotonic) — interpretable and cheap.
5. **The LLM is used only for** semantic clause extraction (with
   schema-constrained decoding) and tool-selection reasoning on hard cases.
6. **Every discrepancy must carry a source citation** (document + clause/line)
   and a calibrated confidence score. No uncited flags.
7. **Prefer the simplest method that solves each sub-problem.** Interpretable and
   reproducible beats clever.
8. **Use clean interfaces** so heuristic stubs can be replaced by trained ML
   models later without changing callers.

---

## Engineering standards (apply to ALL code)

These are mandatory on every file:

- **Module docstrings** describing the module's responsibility.
- **Class and method/function docstrings** with `Args:`, `Returns:`, and
  `Raises:` sections (Google style).
- **Type hints on every function signature** (params and return), Python 3.11+.
- **Specific exceptions, never bare `except`.** Define and raise custom
  exceptions from `exceptions.py`; catch the narrowest type that applies.
- **Logging, never `print`.** Use the configured structured logger from
  `logging_config.py`. Log at appropriate levels (DEBUG/INFO/WARNING/ERROR).
- **Separation of concerns.** One responsibility per module; no business logic in
  the API layer; no I/O buried in pure-logic functions.
- **Clear section headers** within longer modules.
- **Validate at boundaries** with Pydantic models; don't pass raw dicts between
  layers.
- **Fault tolerance:** external calls (LLM/vLLM, OCR, DB, embeddings) wrapped with
  timeouts, retries with backoff, and graceful degradation. A single document
  failing must not crash a batch — isolate, log, continue, and record the failure.
- **Scalability:** process documents independently so work can be parallelized;
  no global mutable state; make batch operations streamable.
- **Determinism where required:** the rules engine and arithmetic paths must be
  pure and reproducible. Seed any stochastic step that affects output.

---

## Code conventions

- Formatting: `black` + `ruff` (or `ruff format`); imports sorted.
- Config via `pydantic-settings`, loaded from env; never hardcode secrets,
  paths, model names, or thresholds — put them in `config.py`.
- Async for I/O-bound API/DB/LLM calls where it pays off; keep CPU-bound
  classical-ML code synchronous.
- Tests with `pytest`; deterministic fixtures for the rules engine; one test
  module per package. Write tests alongside each module, not after.
- Docstring example for the expected style:

```python
def match_invoice_to_contract(
    invoice: Invoice,
    candidates: list[Contract],
    threshold: float,
) -> MatchResult:
    """Resolve which contract governs an invoice via record linkage.

    Uses blocking to limit comparisons, then scores each candidate with a
    trained classifier over fuzzy-string and embedding features.

    Args:
        invoice: The parsed invoice to match.
        candidates: Contracts in scope after blocking.
        threshold: Minimum classifier score to accept a match.

    Returns:
        A MatchResult with the chosen contract (or None) and the score.

    Raises:
        NoCandidateContractsError: If `candidates` is empty.
        MatchingModelError: If the scoring model fails to load or predict.
    """
```

---

## Build order (do not jump ahead)

1. **Phase 1 — deterministic + classical-ML core:** config, logging, exceptions,
   domain models, native-PDF ingestion, rules-based discrepancy engine, audit
   log, minimal FastAPI, seeded-error eval on clean data. Stub the LLM/trained
   models behind interfaces.
2. **Phase 2 — document understanding:** OCR + table-structure for scanned/messy docs.
3. **Phase 3 — retrieval + matching:** hybrid search + reranker, matching
   classifier, anomaly detection, calibration, HITL routing.
4. **Phase 4 — agent + self-hosted LLM:** LangGraph-style orchestration; vLLM
   quantized model on the L40S with constrained decoding.

Always keep the seeded-error evaluation harness (`eval/`) runnable — it is the
project's proof and pitch.

---

## What NOT to do

- Don't put arithmetic or rule logic inside an LLM prompt.
- Don't reach for the LLM (or a large neural net) when a classical method solves
  it — that's the most common 2026 anti-pattern and a weakness in review.
- Don't emit a discrepancy without a source citation and confidence score.
- Don't use `print`, bare `except`, untyped functions, or pass raw dicts
  across layer boundaries.
- Don't send documents to any external/public API — inference is self-hosted.
- Don't expand MVP scope (multi-tenant SaaS, payments, ERP integrations,
  LLM fine-tuning) until the core pipeline + eval are solid.
```
