# ClauseGuard

**Audit-grade AI agent for contract-to-invoice reconciliation and spend-leakage
detection — runs privacy-first on commodity hardware, no GPU required.**

Every finance team overpays vendors: a rate that drifted above the contract, a
volume discount that was never applied, a line billed in the wrong currency, an
invoice dated outside its term. ClauseGuard reads a vendor invoice, matches it to
its governing contract, and flags exactly where the money leaked — returning
every finding with a **citation** and a **monetary impact**, then writing an
**audit record**.

The design thesis: **the money math is deterministic and reproducible; a language
model is used only for genuine language ambiguity, never for arithmetic, rules,
or matching.** That is what makes the output audit-grade — an auditor can trace
every finding back to a clause — and what lets the whole thing run on a 16 GB
laptop with no accelerator, so no financial data ever has to leave the machine.

> **Status:** working end-to-end. An invoice's text flows through the entire
> pipeline — ingestion → extraction → matching → deterministic rules → cited
> findings + audit record — verified by **26 passing tests**. OCR for scanned
> documents, contract extraction, and an optional local LLM slot in behind
> interfaces that already exist, so the core never changes.

---

## See it work

`python scripts/run_demo.py` runs a real invoice's text through the whole
pipeline. On the bundled example it recovers **INR 10,500** of spend leakage
across three distinct discrepancy types, each grounded in a citation:

```
Parsed invoice text -> 2 line items
Invoice INV-900  ->  contract C-001 (match 1.00)
Status: auto_reported
Total impact: INR 10500.00

Discrepancies (3):
  • [rate_mismatch] Line 1 (WIDGET-A) billed above the contracted unit rate.
      expected=INR 100.00  actual=INR 130.00  impact=INR 4500.00  conf=0.97
      citation: Contract C-001, rate card SKU WIDGET-A
  • [missed_volume_discount] Line 1 (WIDGET-A) qualified for a 10% volume
      discount that was not applied.
      expected=INR 90.00  actual=INR 130.00  impact=INR 6000.00  conf=0.90
      citation: Contract C-001, SKU WIDGET-A volume discount tiers
  • [uncontracted_item] Line 2 bills SKU GADGET-Z, not on the rate card.
      actual=GADGET-Z  conf=0.85
      citation: Contract C-001 rate card (SKU GADGET-Z absent)
```

*(Synthetic data; real-document benchmarking is on the roadmap.)*

---

## What it detects today

Each check is a small, pure, reproducible rule; every finding carries a citation
and, where quantifiable, a monetary impact:

| Discrepancy | What it catches |
| --- | --- |
| **Rate mismatch** | Billed above the contracted unit rate. |
| **Currency mismatch** | A line billed in a currency other than the contract's (and guards the amount rules from ever comparing across currencies). |
| **Arithmetic error** | Printed line total ≠ quantity × unit rate. |
| **Missed volume discount** | An earned volume-discount tier that was not applied. |
| **Out-of-term dating** | Invoice dated outside the contract's validity window. |
| **Uncontracted item** | A billed SKU absent from the contract rate card. |

And the pipeline that feeds them is complete for structured / digital-text
invoices:

- **Ingestion** — `NativePdfParser` reads native (text-layer) PDFs via
  `pdfplumber`, and treats non-PDF input as text, decided by the PDF magic
  number so plain text is never mistakenly fed to a PDF engine.
- **Extraction** — `RuleBasedInvoiceExtractor` turns invoice text into a
  validated `Invoice`: column mapping by header name (robust to reordering),
  `Decimal` money, and fail-loud on any unparseable field.
- **Matching → rules → confidence routing → audit** — a matched invoice runs
  through every rule; low-confidence results are routed to human review.

---

## Runs on your hardware

The deterministic engine is plain, exact Python — milliseconds per invoice, a
few hundred MB of RAM. The optional LLM edge uses a **small local model** (via
Ollama / llama.cpp) only for the rare genuinely ambiguous line.

- **CPU-only, 16 GB RAM, no GPU** — the entire pipeline runs locally.
- **No data leaves the box** — built for on-prem / air-gapped finance teams.
- **Scales up, doesn't require scaling** — point the LLM adapter at a GPU for
  more throughput in production; nothing in the code changes.

Reconciliation is a **batch** workload, not a chatbot, so per-token model speed
is irrelevant: only the rare ambiguous line touches a model, in the background.

---

## Architecture: ports & adapters (hexagonal)

Each stage sits behind an interface, so it is independently swappable:

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
   (PDF / text)    (rule-based)        (heuristic →ML)                       (in-memory →DB)
```

The orchestration depends only on the `ports/` interfaces. Swapping the
heuristic matcher for a trained classifier, the in-memory audit log for a
database, or adding an OCR ingestion adapter, is a one-line change in
`api/dependencies.py` — no caller is touched.

### Core rules (enforced)
- **Deterministic by default; the LLM is used only for genuine language ambiguity.**
- **Never an LLM for arithmetic, rules, or matching.**
- **Money is `Decimal`, never `float`.**
- **Every discrepancy carries a citation and a confidence score.**
- **Rules are pure and reproducible; the engine isolates per-rule failures.**

---

## Design decisions (the *why*)

- **`Decimal` money with an explicit currency, never `float`.** Binary floats
  silently lose precision — unacceptable in an audit-grade financial tool.
  Mixed-currency arithmetic on a line *raises* rather than computing nonsense,
  and a dedicated rule flags currency mismatches so amount checks never compare
  across currencies.
- **Deterministic core, LLM only at the edges.** Correctness lives in pure,
  reproducible rules — not a model that can hallucinate. The LLM's job is narrow
  (ambiguous line-to-SKU language), so a small local model suffices; no GPU.
- **Fail loud, never silently wrong.** Extraction raises on any unparseable
  field rather than producing a wrong `Invoice`. In finance, a silent wrong
  number is far more dangerous than a loud failure.
- **Mandatory citations.** A `Discrepancy` cannot be constructed without a
  citation — "audit-grade" is enforced at the type level, not by convention.
- **Confidence + human-review routing.** Low-confidence results go to review, not
  auto-report; a tool that is confidently wrong is worse than one that asks.
- **Ports & adapters.** Start simple (rule-based extraction, heuristic matching,
  in-memory audit) and grow into OCR, trained models, and a database without
  rewriting the orchestration.

---

## Quickstart

Tested on Ubuntu 24.04 (Python 3.12). On a fresh machine you may first need the
venv tooling: `sudo apt install python3-venv python3-full -y`.

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev,ingestion,matching]"

pytest -q                            # run the test suite (26 passing)
python scripts/run_demo.py           # watch a document flow end-to-end
uvicorn clauseguard.api.app:app --reload   # API at http://localhost:8000/docs
```

A `Makefile` wraps these (`make dev`, `make test`, `make run`, `make demo`).

---

## Pipeline flow (the demo)

`scripts/run_demo.py` starts from the **raw text of an invoice** — what a parsed
document yields — and runs the whole chain:

```
invoice text
  -> NativePdfParser            (ingestion:  bytes/text -> ParsedDocument)
  -> RuleBasedInvoiceExtractor  (extraction: text -> Invoice)
  -> HeuristicMatcher           (match invoice -> governing contract)
  -> RulesEngine                (deterministic discrepancy checks)
  -> ReconciliationResult       (citations + monetary impact + audit record)
```

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
  rules/               deterministic discrepancy engine (the heart)
  confidence/          scoring + human-review routing
  services/            ReconciliationService — the use-case orchestrator
  api/                 FastAPI app, routers, schemas, DI composition root
tests/                 pytest suite (rules, extraction, ingestion, service, domain)
scripts/run_demo.py    end-to-end document-flow demo
```

---

## Roadmap

- **Contract extraction** — a rule-based `ContractExtractor` so contracts, like
  invoices, are sourced from text.
- **OCR ingestion** — a scanned-document adapter behind the existing
  `DocumentParser` port (Tesseract / OpenVINO), for image-only PDFs.
- **Hardened extraction** — robustness to the messier text real PDF extraction
  emits (wrapped lines, collapsed columns).
- **Smarter matching** — escalate only genuinely ambiguous invoice→contract
  matches to a small local LLM; a trained classifier with calibrated confidence.
- **Evaluation harness** — measure detection precision / recall against the
  seeded-error manifests.

Each item slots in behind an interface that already exists in this codebase.

---

## License

MIT © Prasun Mani Gupta