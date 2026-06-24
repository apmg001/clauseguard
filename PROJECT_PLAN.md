# Project Plan — ClauseGuard

The end-to-end roadmap as checkable milestones. Two tracks run in parallel: the
**build** (code) and the **business** (DPIIT, data, design partner, grant). Don't
finish the code before starting the business track — they go together.

---

## Track A — Build

### Phase 0 — Setup ✅ (shipped in this scaffold)
- [x] Repo structure, packaging (`pyproject.toml`), tooling (ruff, pytest)
- [x] Config, structured logging, exception hierarchy
- [x] Ports & adapters architecture in place
- [x] Runnable API + passing tests + demo script

### Phase 1 — Deterministic + classical-ML core ✅ (this scaffold)
- [x] Domain models (Decimal money, frozen value objects)
- [x] Deterministic rules engine with per-rule fault isolation
- [x] Rules: rate mismatch, arithmetic, missed volume discount, out-of-term, uncontracted item
- [x] Heuristic matcher (behind the matching port)
- [x] Confidence scoring + human-review routing
- [x] In-memory audit log
- [x] Reconciliation orchestration service
- [x] FastAPI `/health` and `/v1/reconcile`
- [ ] **Your next step:** generate a synthetic dataset + the seeded-error eval harness (BUILD_BRIEF §8)
- [ ] Add duplicate-invoice detection (MinHash/LSH) behind a new rule
- [ ] Add SLA-penalty rule once contract SLA terms are modelled

### Phase 2 — Document understanding
- [ ] OCR adapter (Tesseract/docTR) behind `ports.ingestion`
- [ ] Table-structure extraction (Table Transformer) for invoice line items
- [ ] Rule-based contract/invoice extractors behind `ports.extraction`
- [ ] Accuracy harness on messy real-world-style PDFs

### Phase 3 — Retrieval + matching + ML
- [ ] Hybrid retrieval (dense embeddings + BM25) + cross-encoder reranker
- [ ] Trained matching classifier (XGBoost/LightGBM) behind `ports.matching`
- [ ] Anomaly detection (Isolation Forest) on prices
- [ ] Confidence calibration (Platt/isotonic) in `confidence/`
- [ ] Human-in-the-loop review queue + active-learning prioritisation

### Phase 4 — Agent + self-hosted LLM (L40S)
- [ ] vLLM serving a 4-bit quantized open model
- [ ] Schema-constrained decoding for semantic clause extraction
- [ ] LangGraph-style orchestration (explicit, traceable control flow)
- [ ] Replace the LLM extractor stub; full pipeline runs with no external API

### Capstone — Proof artifact
- [ ] Seeded-error eval producing detection recall/precision + calibration
- [ ] README with metrics, architecture diagram, 2-minute demo video

---

## Track B — Business & funding (parallel)
- [ ] Incorporate; file **DPIIT recognition** (free, 2–5 days — do first)
- [ ] Source real/realistic contract+invoice documents (public tenders, network)
- [ ] Land one design partner (a company that runs it and will be a reference)
- [ ] Contact **TIDES (IIT Roorkee)** / FIED for the current SISFS intake window
- [ ] Apply for the grant once the eval demo exists

---

## Decision gates (stop and evaluate honestly)
- **After Phase 1:** core works and the domain suits you? → continue, else pivot cheaply.
- **After Phase 2:** messy-document accuracy holding? → the make-or-break gate.
- **After the eval:** numbers strong enough to show a panel? → apply + approach partner.

---

## Working with Claude Code
On each session: "Read `CLAUDE.md` and `BUILD_BRIEF.md`, then continue from the
next unchecked item in `PROJECT_PLAN.md`." Keep `scripts/run_demo.py` and the
eval harness runnable at all times — they are the proof.
