# ClauseGuard

**Audit-grade AI agent for contract-to-invoice reconciliation and spend-leakage
detection** — runs privacy-first on commodity hardware, no GPU required.

ClauseGuard reads a vendor invoice, matches it to its governing contract, and
flags where you were overbilled — wrong rates, arithmetic errors, missed volume
discounts, out-of-term dates, uncontracted items — returning every finding with
a **citation** and a **monetary impact**, then writing an **audit record**.

The design thesis: **the money math is deterministic and reproducible; a language
model is used only for genuine language ambiguity, never for arithmetic, rules,
or duplicate detection.** That is what makes the output audit-grade — and what
lets the whole thing run on a 16 GB laptop with no accelerator, so no financial
data ever has to leave the machine.

> **Status:** Phase 1 scaffold — the deterministic + classical-ML core. Fully
> runnable and tested. Document understanding (OCR/tables), retrieval, the
> trained matcher, and the self-hosted LLM slot in during later phases *behind
> interfaces that already exist here*, so the core never changes.

See `BUILD_BRIEF.md` for the full design and `PROJECT_PLAN.md` for the roadmap.

---

## Runs on your hardware

The deterministic engine is plain, exact Python — it evaluates in milliseconds
and needs a few hundred MB of RAM. The optional LLM edge uses a **small local
model** (via Ollama / llama.cpp) for the handful of genuinely ambiguous lines the
deterministic layer can't resolve on its own.

- **CPU-only, 16 GB RAM, no GPU** — the entire pipeline runs locally.
- **No data leaves the box** — built for on-prem / air-gapped finance teams.
- **Scales up, doesn't require scaling** — point the LLM adapter at a dedicated
  GPU for higher throughput in production; nothing in the code changes.

Reconciliation is a **batch** workload, not a chatbot, so per-token model speed
is irrelevant: only the rare ambiguous line touches the model, and results are
produced per-invoice in the background.

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
log for a database, or the LLM stub for a real local model, is a one-line change
in `api/dependencies.py` — no caller is touched. That is what keeps the project
improvable as phases are added.

### Core design rules (enforced)
- **Deterministic by default; the LLM is used only for genuine language ambiguity.**
- **Never an LLM for arithmetic, rules, or duplicate detection.**
- **Money is `Decimal`, never `float`.**
- **Every discrepancy carries a citation and a confidence score.**
- **Rules are pure and reproducible; the engine isolates per-rule failures.**

---

## Design decisions (the *why*)

- **`Decimal` money with an explicit currency, never `float`.** Binary floats
  silently lose precision; for an audit-grade financial tool that is
  unacceptable. Mixed-currency arithmetic on a single line *raises* rather than
  computing a meaningless number.
- **Deterministic core, LLM only at the edges.** Correctness guarantees live in
  pure, reproducible rules — not in a model that can hallucinate. The LLM's job
  is narrow (resolving ambiguous line-to-SKU language), so a small local model
  is sufficient and a GPU is not required.
- **Ports & adapters (hexagonal).** Every stage sits behind an interface, so the
  system can start simple (heuristic matching, in-memory audit) and grow into
  trained models and a database without rewriting the orchestration.
- **Mandatory citations.** A `Discrepancy` cannot even be constructed without a
  citation grounding it in a contract clause or invoice line — "audit-grade" is
  enforced at the type level, not by convention.
- **Confidence + human-review routing.** Low-confidence results are routed to
  review rather than auto-reported, because a spend-recovery tool that is
  confidently wrong is worse than one that asks.

---

## Quickstart

Tested on Ubuntu 24.04 (Python 3.12). On a fresh machine you may first need the
venv tooling: `sudo apt install python3-venv python3-full -y`.

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1

# 2. Install with dev + optional extras (tests, pdf, fuzzy matching)
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

The bundled demo reconciles a seeded invoice and recovers **INR 10,500** of
planted spend leakage across three distinct discrepancy types, each citation-
backed. (Synthetic data; real-document benchmarking is on the roadmap below.)

---

## Roadmap

- **Phase 2** — OCR + table extraction, and the routing layer that resolves lines
  deterministically wherever possible and escalates *only* genuinely ambiguous
  lines to a small local LLM.
- **Phase 3** — hybrid retrieval, a trained matching classifier, anomaly
  detection, and confidence calibration against labelled data.
- **Phase 4** — LangGraph orchestration and a self-hosted quantized LLM. The LLM
  runs on CPU / integrated graphics with a small model and scales to a dedicated
  GPU for throughput; the deterministic core needs no accelerator.

Each phase slots in behind an interface that already exists in this scaffold.

---

## License

MIT.