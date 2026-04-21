# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Crucible is an **inverse alloy design agent for steels**. Given a target property profile (strength, toughness, hardness), it outputs ranked steel grade candidates with processing routes, predicted properties with uncertainty, and cost estimates. The output is probabilistic — not a deterministic engineering answer.

The project is currently in **Phase 1 (Data Foundation)**. The agent pipeline does not yet exist; only the database layer and data ingestion infrastructure are built.

## Commands

This project uses `uv` for package management.

```bash
# Install dependencies
uv sync

# Run the smoke test for the NIMS parser + ingest pipeline
python -m data.parsers.test_nims_parser

# Run the coverage report (after ingesting data)
python -m data.coverage
python -m data.coverage --source NIMS
python -m data.coverage --family low-alloy
```

## Architecture

### Data Layer (`data/`)

The database layer is the only implemented component. Everything enters the DB through a single validated pipeline:

```
Source-specific parser → SteelIngestBundle (Pydantic) → ingest_bundles() → SQLite
```

**`models.py`** — SQLAlchemy ORM. Five tables: `sources`, `steels`, `compositions`, `processing`, `properties`, `microstructure`. Key design decisions:
- `Composition` is one row per `steel_id` (1:1). `Processing` and `Properties` are 1:many — the same composition can have multiple processing routes and associated property measurements.
- `processing_id` is nullable in `Properties` — many real data sources (MatWeb, grade tables) provide composition + properties with no processing history.
- `Source.reliability` is 1–5: NIMS/ASM = 5, literature = 3–4, MatWeb = 2–3. Weight training data by this field.

**`schemas.py`** — Pydantic v2 validation layer. Every record must pass through `SteelIngestBundle` before touching the DB. Validators catch: unit errors (ppm vs wt%, kgf/mm² vs MPa), physically impossible values (UTS < yield strength, temper > austenitize temp, carbon > 2.14 wt%), and schema mismatches.

**`ingest.py`** — Entry point for all writes. `ingest_bundles()` runs batch ingestion with per-record error collection. `ensure_source()` is idempotent and must be called before ingesting from any new data source.

**`database.py`** — SQLAlchemy engine + session management. Database URL is set via `DATABASE_URL` env var (defaults to `sqlite:///./steels.db`). SQLite-only note: foreign keys are disabled in SQLite by default; the engine enables them via PRAGMA.

**`parsers/nims.py`** — Parser for NIMS MatNavi MSDB exports (.xlsx/.csv). Column names vary across NIMS export versions — always run `NIMSParser.inspect(path)` on a new download before parsing to verify header names match `COLUMN_MAP`.

**`parsers/steelbench.py`** — Parser for SteelBench v1.0 (Zenodo, CC-BY 4.0, 1,360 records). Downloads directly from Zenodo if no local path is given. Three data tiers with different reliability: `nims_measured` (5), `emk_spec_verified` (4), `kaggle_measured` (2). Critical data quality notes:
- NIMS rows in SteelBench are UTS-only (yield, elongation, hardness, Charpy, and all processing params are null by design — not a parser bug).
- EMK hardness values are specification limits, not measurements — exclude from hardness training.
- Kaggle hardness is confirmed HB (Brinell).

**`coverage.py`** — Coverage report tool. Run after every major ingest batch to surface gaps before modeling. Processing-parameter coverage is the key weak point.

**`AISI_steel_code_tables/`** — The AISI Steel Code ordering and communication protocol (EDI tables used between steelmakers and buyers). These are **not** composition databases. Only `STLCDPID_10-30-19.xlsx` is relevant — it contains grade type codes and heat treatment type codes useful as lookup/validation references. The COMPORD, Outside-Processing, and Shipping files have no use in this project. See `data/DATA.md` for the full breakdown.

For a complete description of all data sources (ingested, reference, and planned), see **`data/DATA.md`**.

### Planned Pipeline (not yet implemented)

Per `roadmap.md`, the eventual agent pipeline is:

```
User Query → LLM Orchestrator → Retrieval Tool (FAISS) → Forward Scorer (GBM primary, AlloyBERT ensemble) → CALPHAD Phase Check → Output Ranker → Ranked Candidates + Processing Routes
```

Planned stack: XGBoost/LightGBM (primary scorer), MatBERT fine-tuned on SteelBench (ensemble), PyCalphad + open TDB (phase feasibility), BoTorch (Bayesian optimization), Claude API (LLM orchestration).

## Data Quality Rules

- **Missing composition values are `NULL`, not `0`.** Imputing zero changes the metallurgy.
- **Do not mix hardness scales** in a single training feature without conversion.
- **Processing coverage is sparse.** The `processing_id` FK in `Properties` being null is normal and expected for many sources.
- **NIMS rows in SteelBench** should be partitioned separately — use only for UTS-from-composition models.
- **Reliability weighting** must be applied when training. Higher-reliability sources should dominate loss.
