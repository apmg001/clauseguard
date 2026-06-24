# Build Brief — ClauseGuard

**Audit-grade AI agent for contract-to-invoice reconciliation and spend-leakage detection.**

> This document is the single source of truth for the project. It captures the
> problem, the architecture, the algorithm choices per stage, the module layout,
> and the build order. Hand it to Claude Code alongside `CLAUDE.md` and build
> the modules in the order specified.

---

## 1. One-line summary

A company uploads its vendor **contracts** and incoming **invoices**. The system
checks every invoice against the contract that governs it, flags overbilling,
duplicate charges, missed discounts, out-of-term pricing, and unclaimed SLA
penalties — and for **each flag** it cites the exact source clause, scores its
confidence, routes ambiguous cases to a human, and writes an immutable audit log.

The product sold is **money recovered, with proof** — priced as a share of
recovered spend. It is deployed **privacy-first on the operator's own GPU**, so a
client's financial documents never leave their infrastructure.

---

## 2. Problem and value

Companies lose money to billing errors and unenforced contract terms. The value
here is **measurable in currency recovered**, not a vague productivity gain. The
output is legible to a CFO: "we found X% of spend leaking, here is the
clause-cited proof for each instance."

The moat is not the LLM. It is three things stacked:
1. **Privacy-first on-prem deployment** (clients won't send contracts to a public API).
2. **Robust handling of messy real documents** (the hard part — see §9).
3. **Accumulated edge-case data and labels** from human review, compounding over time.

---

## 3. Core architectural principle (read this first)

**Be deterministic wherever possible. Use an LLM only where language is genuinely ambiguous.**

This is the most important rule in the system and the main thing a sophisticated
reviewer (grant panel, MNC interviewer) will probe.

- **Arithmetic, rule checks, and duplicate detection are NEVER done by an LLM.**
  They must be deterministic and reproducible — audit-grade output cannot depend
  on a stochastic model, and LLMs are unreliable at arithmetic.
- **Matching is a classical record-linkage problem**, solved with a trained
  classifier over engineered features — not "ask the LLM."
- The LLM's only jobs are (a) extracting semantic terms from messily-worded
  clauses and (b) tool-selection reasoning on genuinely hard cases.
- Prefer the simplest method that solves each sub-problem. Interpretable +
  reproducible beats clever every time in an audit context.

---

## 4. System pipeline

```
ingest → extract (contract terms + invoice line items)
       → match invoice ↔ governing contract
       → detect discrepancies (rules) + anomalies (ML)
       → score & calibrate confidence
       → route low-confidence cases to human review
       → write immutable audit log
       → expose via API
```

Retrieval (hybrid search + reranker) sits underneath extraction and matching so
the system works on long contracts without feeding whole documents to the model.

---

## 5. Algorithm choice per stage

| Stage | Method category | Specific techniques |
|---|---|---|
| PDF/text ingestion | Deterministic / DL | pdfplumber, PyMuPDF; OCR via Tesseract or docTR/LayoutLMv3 for scans |
| Table extraction | DL | Camelot/Tabula for ruled tables; Table Transformer (TATR) for messy ones |
| Document classification (invoice vs contract vs addendum) | Classical ML | TF-IDF + SVM / logistic regression; escalate to transformer only if needed |
| Contract clause/term extraction | Deterministic + LLM | regex/rules for currency, dates, %, validity windows; LLM with **schema-constrained decoding** (Outlines/XGrammar) for semantic fields |
| Invoice parsing | Deterministic + DL | key-value + line-item table extraction; deterministic numeric validators |
| Invoice ↔ contract matching | **Classical ML** | record linkage: rapidfuzz (Jaro-Winkler/Levenshtein) + embedding similarity as features into a trained classifier (LogReg / RandomForest / XGBoost/LightGBM); **blocking** to limit comparisons |
| Line-item ↔ SKU/rate matching | Embeddings + fuzzy | dense cosine similarity with threshold; fuzzy string fallback |
| Retrieval | DL embeddings + classical IR | **hybrid** dense (L40S embeddings, pgvector/FAISS) + sparse BM25; **cross-encoder reranker**; clause-aware chunking |
| Discrepancy detection | **Deterministic rules engine** | rate mismatch, qty×rate=total, out-of-validity dates, missed volume discounts, unclaimed SLA penalties |
| Duplicate detection | Classical algorithmic | keying + MinHash/LSH for near-duplicates |
| Anomaly detection | **Classical ML** | Isolation Forest / LOF / one-class SVM; per-SKU/vendor z-score / IQR outliers |
| Confidence calibration | **Classical ML** | Platt scaling (logistic) / isotonic regression on a labeled set |
| LLM uncertainty signal | LLM | self-consistency sampling and/or token log-probs |
| Human-in-the-loop routing | Threshold + active learning | uncertainty-based prioritization; corrections feed back as labels |
| Agent orchestration | Deterministic state machine / DAG | LangGraph-style explicit, traceable control flow; function-calling for tools; open-ended ReAct only on genuinely ambiguous cases |
| Self-hosted inference | Quantized LLM serving | 4-bit (AWQ/GPTQ/bitsandbytes), served via vLLM, constrained decoding for structured calls |

**Note on classical-ML models needing labels:** the trained classifiers
(matching, calibration, anomaly thresholds) need labeled data, which doesn't
exist on day one. Start rule-based/heuristic, then swap in trained models as
human review generates labels. This is also how the data moat compounds.

---

## 6. Proposed module layout

```
clauseguard/
├── CLAUDE.md                      # standing instructions for Claude Code
├── BUILD_BRIEF.md                 # this file
├── README.md
├── pyproject.toml
├── .env.example
├── docker-compose.yml             # API + postgres/pgvector + (optional) vLLM
├── src/clauseguard/
│   ├── config.py                  # typed settings, env loading (pydantic-settings)
│   ├── logging_config.py          # structured logging setup (no print, ever)
│   ├── exceptions.py              # custom exception hierarchy
│   ├── domain/                    # Pydantic models: Contract, Invoice, LineItem,
│   │                              #   Discrepancy, MatchResult, ConfidenceScore...
│   ├── ingestion/                 # PDF/OCR/table extraction
│   ├── extraction/                # clause & invoice term extraction (rules + LLM)
│   ├── matching/                  # entity resolution / record linkage (classical ML)
│   ├── retrieval/                 # hybrid search, embeddings, reranker
│   ├── rules/                     # deterministic discrepancy rules engine
│   ├── anomaly/                   # classical ML anomaly detection
│   ├── confidence/                # calibration & scoring
│   ├── review/                    # human-in-the-loop routing & active learning
│   ├── agent/                     # orchestration (state machine / DAG)
│   ├── llm/                       # self-hosted model client (vLLM), constrained decoding
│   ├── audit/                     # immutable audit log
│   └── api/                       # FastAPI app, routers, request/response schemas
├── tests/                         # pytest, one test module per package
├── data/
│   ├── synthetic/                 # generated contract/invoice pairs
│   └── seeded_eval/               # documents with planted, known errors
├── eval/                          # evaluation harness (the demo that proves it works)
└── scripts/                       # data generation, model training, one-off tooling
```

Each package has a single responsibility and a clean interface so trained ML
models drop in behind the same interface as the initial heuristics.

---

## 7. Tech stack

- **Language/runtime:** Python 3.11+
- **API:** FastAPI + uvicorn; async where it pays off
- **Data models:** Pydantic v2 (validation at every boundary)
- **Settings:** pydantic-settings (typed, env-driven)
- **Classical ML:** scikit-learn, XGBoost/LightGBM, rapidfuzz
- **Document/DL:** pdfplumber/PyMuPDF, Tesseract/docTR, Camelot, Table Transformer
- **Retrieval:** sentence-transformers (embeddings on L40S), pgvector or FAISS, rank-bm25, cross-encoder reranker
- **LLM serving:** vLLM with a 4-bit quantized open model; Outlines/XGrammar for constrained decoding
- **Agent:** LangGraph (or an explicit hand-rolled state machine)
- **Storage:** PostgreSQL (+ pgvector); append-only audit table
- **Infra:** Docker / docker-compose; the L40S host serves embeddings + LLM
- **Testing:** pytest, with deterministic fixtures for the rules engine

---

## 8. Evaluation harness (this IS the pitch — do not skip)

Build a **seeded-error evaluation set**: take synthetic/public contract+invoice
pairs and plant a known set of errors (overbilling, duplicates, missed discounts,
out-of-term charges). Run the full pipeline and report:

- detection recall / precision per error type,
- false-positive rate,
- calibration quality (does "0.9 confidence" mean ~90% correct?),
- per-flag clause citation correctness,
- latency.

Target demo statement: *"Seeded 40 errors across 50 invoices; caught 37, missed 3,
flagged 5 borderline for review — here is the cited clause for each."* That single
result is both the hireable portfolio artifact and the fundable pitch.

---

## 9. Known hard part / primary risk

**Messy real documents** (scanned PDFs, addenda, side letters, inconsistent
formats) are where the project lives or dies. Clean synthetic data will work
quickly and feel great; the gap to "works on a real company's ugly contracts" is
the whole game. Budget the majority of iteration time here. This difficulty is
also *why* the project is defensible.

Secondary risk: getting a real design partner's documents — a non-code hustle
that nonetheless decides the funding outcome.

---

## 10. Build order (phased — follow this sequence)

**Phase 1 — Deterministic + classical-ML core (the trustworthy backbone)**
config, logging, exceptions, domain models → ingestion (native PDFs first) →
deterministic + LLM-stub extraction → rules-based discrepancy engine → audit log
→ minimal FastAPI surface. Use heuristic/rule stubs where trained models will
later go. Ship the seeded-error eval against clean data.

**Phase 2 — Document understanding**
OCR + table-structure extraction for scanned/messy documents. This is where
accuracy work concentrates.

**Phase 3 — Retrieval + matching**
Hybrid search + reranker; the classical-ML matching classifier (heuristic first,
trained once labels exist); anomaly detection; confidence calibration; HITL
routing with active learning.

**Phase 4 — Agent + self-hosted LLM**
LangGraph-style orchestration; vLLM-served quantized model on the L40S with
constrained decoding; wire the LLM in only for the ambiguous extraction and
tool-selection paths.

---

## 11. MVP scope boundaries (non-goals)

For the MVP, explicitly **out of scope**: multi-tenant SaaS, billing/payments,
fancy frontend, ERP integrations (SAP/NetSuite/Coupa) beyond a stub, and
fine-tuning the LLM. The MVP is a defensible, demo-ready pipeline with a
seeded-error eval — not a commercial product.
