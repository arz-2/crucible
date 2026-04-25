# GEMINI.md - Crucible Project Context

Crucible is an **inverse alloy design agent for steels**. It predicts steel grade candidates, processing routes, and properties based on target profiles.

## Core Mandates
- **Data Integrity:** Missing composition values must be `NULL`, not `0`.
- **Validation:** Every record must pass through `SteelIngestBundle` (Pydantic) before DB entry.
- **Reliability:** Weight training data by `Source.reliability` (1–5 scale).
- **Hardness:** Do not mix hardness scales without conversion.
- **Security:** Never log or commit secrets or API keys.

## Tech Stack
- **Language:** Python 3.12+
- **Package Manager:** `uv`
- **Data Validation:** Pydantic v2
- **ORM:** SQLAlchemy (SQLite backend)
- **Data Processing:** Pandas, OpenPyXL, xlrd

## Key Commands
```bash
# Environment & Dependencies
uv sync

# Ingestion & Testing
python -m data.parsers.test_nims_parser
python -m data.parsers.ingest_all

# Analysis & Coverage
python -m data.coverage
python -m data.coverage --source NIMS
python -m data.coverage --family low-alloy
```

## Architecture

### Data Layer (`data/`)
- `models.py`: SQLAlchemy ORM with 6 core tables: `sources`, `steels`, `compositions`, `processing`, `properties`, `microstructure`.
- `schemas.py`: Pydantic validation layer. Ensures physical limits (e.g., carbon < 2.14 wt%).
- `ingest.py`: Centralized batch ingestion point.
- `parsers/`: Source-specific logic (NIMS, ASM, SteelBench, etc.).

## Data Quality Rules
- `Composition` is 1:1 with `steel_id`.
- `Processing` and `Properties` are 1:many with `steel_id`.
- `Source.reliability`: NIMS/ASM (5), literature (3–4), MatWeb (2–3).
- Schema S limit: 0.4 wt% for free-cutting steels.
- EMK hardness in SteelBench: Specification limits, not measurements (exclude from training).
- Kaggle hardness: Brinell (HB).

## Roadmap Highlights
- Phase 1 (Current): Data Foundation.
- Phase 2: Forward Scorer (XGBoost/LightGBM).
- Phase 3: Generative Design Agent (Bayesian Optimization + LLM Orchestration).
- Phase 4: Physics-based Validation (CALPHAD).
