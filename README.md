# Crucible

**Inverse alloy design agent for steels.** Given a target property profile (strength, toughness, hardness), Crucible outputs ranked steel grade candidates with processing routes, predicted properties with uncertainty, and cost estimates.

> **Status: Phase 1 — Data Foundation.** The database and ingestion pipeline are complete. The ML pipeline and agent interface are planned (see `roadmap.md`).

---

## What it does

Crucible frames alloy selection as a retrieval + scoring problem:

1. **Retrieve** candidate steels from the database whose composition and processing space overlap the target region
2. **Score** candidates using a gradient-boosted forward model (composition + processing → properties)
3. **Check phase feasibility** via CALPHAD (planned)
4. **Rank and explain** — ranked output with predicted uncertainty and alloy surcharge cost

The output is probabilistic, not a deterministic engineering answer.

---

## Quick start

```bash
# Install dependencies
uv sync

# Visualise the current database (8 plots → data/plots/)
uv run python -m data.visualize

# Coverage report — surface gaps before modelling
python -m data.coverage

# Ingest a specific source (example: AMMRC KIC handbook)
uv run --env-file .env python -m data.parsers.ammrc_kic --ingest
```

An `ANTHROPIC_API_KEY` in `.env` is required only for the AMMRC KIC parser (VLM-based PDF extraction). All other parsers run without an API key.

---

## Data snapshot  *(as of 2026-04-25)*

| Metric | Count |
|--------|-------|
| Unique steels | 5,301 |
| Property rows | 5,523 |
| Named grades | ~2,004 |
| Sources | 11 |

| Property | Rows | Coverage |
|----------|------|----------|
| Yield strength | 3,499 | 63% |
| UTS | 4,452 | 81% |
| Fracture toughness K_IC | 389 | 7% |
| Hardness (any scale) | ~900 | ~16% |
| Fatigue limit | 437 | 8% |
| Elongation | ~1,300 | ~24% |

Sources (reliability 2–5): SteelBench (NIMS/EMK/Kaggle tiers), ASM Handbook Vol.1 & Vol.4, Mondal textbook, Cheng 2024, Figshare, Zenodo, NIMS Fatigue DB, AMMRC MS 73-6 (KIC handbook).

Full source notes and data quality rules: [`data/DATA.md`](data/DATA.md).

---

## Repository layout

```
data/
  models.py          — SQLAlchemy ORM (steels, compositions, processing, properties)
  schemas.py         — Pydantic v2 validation (SteelIngestBundle)
  ingest.py          — batch ingest with per-record error collection
  database.py        — engine + session management
  coverage.py        — property fill-rate report by source and family
  visualize.py       — 8 matplotlib plots → data/plots/
  parsers/           — one parser per source
  DATA.md            — per-source notes, quality rules, coverage gaps
literature_review/   — source PDFs and handbooks
roadmap.md           — phased plan through agent pipeline
```

---

## Planned pipeline  *(not yet implemented)*

```
User Query → LLM Orchestrator → FAISS Retrieval → GBM Forward Scorer
           → CALPHAD Phase Check → Output Ranker → Ranked Candidates
```

Stack: XGBoost/LightGBM · MatBERT · PyCalphad · BoTorch · Claude API.
