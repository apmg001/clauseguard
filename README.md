# ClauseGuard

**Audit-grade AI agent for contract-to-invoice reconciliation and spend-leakage
detection** — deployed privacy-first on your own GPU.

This repository is the **Phase 1 scaffold**: the deterministic + classical-ML
core. It is fully runnable and tested. Document understanding (OCR/tables),
retrieval, the ML matcher, and the self-hosted LLM are wired in during later
phases — behind interfaces that already exist here, so the core never changes.

See `BUILD_BRIEF.md` for the full design and `PROJECT_PLAN.md` for the roadmap.
`CLAUDE.md` holds the engineering standards Claude Code follows on every session.

---

## Architecture: ports & adapters (hexagonal)

The pipeline is decoupled so each stage is independently swappable:

```
            ┌──────────────────────── API (FastAPI) ────────────────────────┐
            │                  routers → schemas → DI wiring                  │
            └───────────────────────────────┬───────────────────────────────┘
                                            │
                          services/ReconciliationService   ← orchestration only
                                            │ depends on PORTS, not adapters
        ┌───────────────┬───────────────────┼───────────────────┬───────────────┐
        ▼               ▼                   ▼                   ▼               ▼
   ports.ingestion  ports.extraction   ports.matching      rules.engine    ports.audit
        │               │                   │             (deterministic)       │
   adapters.       adapters.           adapters.          rules.checks      adapters.
   ingestion       extraction          matching           (pure, reproducible) audit
   (native PDF)    (rule / LLM stub)   (heuristic →ML)                       (in-memory →DB)
```

**Why this shape:** the orchestration depends only on the `ports/` interfaces.
Swapping the heuristic matcher for a trained classifier, or the in-memory audit
log for a database, is a one-line change in `api/dependencies.py` — no caller is
touched. That is what keeps the project "improvable" as you add phases.

### Core design rules (enforced — see `CLAUDE.md`)
- **Deterministic by default; LLM only for genuine language ambiguity.**
- **Never an LLM for arithmetic, rules, or duplicate detection.**
- **Money is `Decimal`, never `float`.**
- **Every discrepancy carries a citation and a confidence score.**
- **Rules are pure and reproducible; the engine isolates per-rule failures.**

---

## Quickstart

```bash
# 1. Create an environment and install (core only)
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. Or install with dev + optional extras (tests, pdf, fuzzy matching)
pip install -e ".[dev,ingestion,matching]"

# 3. Run the test suite
pytest -q

# 4. See the engine catch planted errors end-to-end
python scripts/run_demo.py

# 5. Run the API (then open http://localhost:8000/docs)
uvicorn clauseguard.api.app:app --reload
```

A `Makefile` wraps these (`make dev`, `make test`, `make run`, `make demo`).

---

## Project structure

```
src/clauseguard/
  config.py            typed settings (env-driven; no magic numbers in code)
  logging_config.py    structured logging (never print)
  exceptions.py        custom exception hierarchy
  domain/              Pydantic models + enums (Decimal money, frozen value objects)
  ports/               interfaces: ingestion, extraction, matching, audit
  adapters/            concrete implementations behind the ports
  rules/               deterministic discrepancy engine (the Phase 1 heart)
  confidence/          scoring + human-review routing
  services/            ReconciliationService — the use-case orchestrator
  api/                 FastAPI app, routers, schemas, DI composition root
tests/                 pytest suite (rules, service, domain)
scripts/run_demo.py    end-to-end seeded-error demo
```

---

## What Phase 1 does today

Given an invoice and candidate contracts it: matches the invoice to its
governing contract, runs deterministic checks (rate mismatch, arithmetic
consistency, missed volume discounts, out-of-term dating, uncontracted items),
scores confidence, routes low-confidence results to review, totals the monetary
impact, and writes an audit record — returning every finding with a citation.

## What comes next

Phase 2 OCR + table extraction · Phase 3 hybrid retrieval, the trained matching
classifier, anomaly detection, calibration · Phase 4 LangGraph orchestration and
the self-hosted quantized LLM on the L40S. Each slots in behind an existing port.
