# Steel Processing Recommendation Agent — Project Roadmap

**Project:** Inverse alloy design agent for steels
**Goal:** Given a target property profile and constraints, output ranked steel grade candidates with detailed processing routes, predicted properties with uncertainty, and cost estimates.
**Author:** Alex (arz2@andrew.cmu.edu), Carnegie Mellon University
**Last Updated:** 2026-04-20

---

## Problem Statement

This agent solves an inverse materials design problem: given a target property profile (strength, toughness, hardness, corrosion resistance, etc.) and constraints (budget, geometry, available equipment), output a steel grade and processing route that plausibly achieves it.

The output is a ranked set of candidates with associated uncertainty — not a deterministic engineering answer. That distinction matters and should be communicated to users throughout.

---

## Novelty and Contributions

A literature review (see `literature_review/literature_review.md`) confirms the following positioning:

**Forward property prediction for steels is a solved problem.** Random forests, GBMs, TabPFN, and domain-specific LLMs (SteelBERT) all perform this task well. This is not a contribution of this project — it is infrastructure.

**The contributions are:**

1. **Quantitative processing route recommendation from a property target.** No published work produces a specific, parameterized heat treatment schedule (austenitizing temperature, quench medium, temper temperature/time) from a user-specified property target. The closest paper (SteelBERT, Acta Materialia 2024) suggests one qualitative route ("cold rolling + tempering") for a single steel family with no quantitative parameters. This project does it systematically across multiple route families.

2. **Multi-route coverage.** The only inverse design paper with processing parameters (Nature Sci. Rep. 2021) is scoped exclusively to TMCP. This project covers QT, NT, TMCP, austempering, and case hardening within a unified pipeline.

3. **Agentic pipeline for wrought steels.** MCP-based multi-agent alloy evaluation exists for additive manufacturing alloys (Additive Manufacturing Letters, 2026) but not for wrought/heat-treated steels. This project applies that architecture to the heat treatment design problem.

4. **CCT-informed processing windows integrated into a design loop.** A high-quality ML CCT model exists (arXiv:2512.03050, KTH, 2025) but is not connected to any design or recommendation system. This project integrates it as the phase-feasibility check in the agent pipeline.

5. **Cost estimation.** Not present in any steel design paper in the literature.

**What to avoid claiming as novel:** composition → property prediction, the use of LLMs for materials queries, or retrieval-based candidate ranking. These are all established. The contribution is the integrated pipeline that connects them to actionable, quantitative processing recommendations.

---

## Architecture Overview

The agent is a pipeline, not a monolithic model:

```
User Query → LLM Orchestrator → Retrieval Tool → Forward Scorer → CALPHAD Phase Check → Output Ranker → Ranked Candidates + Processing Routes
```

Each stage is a discrete, testable component. This keeps the system auditable and allows individual components to be swapped or improved independently.

---

## Phase 1 — Data Foundation

**Status:** Not started
**Estimated effort:** 4–8 weeks
**Risk level:** High — this is the most likely point of failure for the project

The data layer is the bottleneck. Most projects in this space fail here, not at the modeling stage. Know your coverage before writing agent code.

### Steel Composition + Property Data

| Source | Coverage | Quality | Access |
|--------|----------|---------|--------|
| NIMS MatNavi | Carbon/alloy steels (JIS grades) | High — includes tensile, yield, hardness, impact data linked to composition | Open |
| AISI grade tables | Standard grades only | High for standard grades, no novel compositions | Open |
| MatWeb | Broad coverage | Inconsistent — use as supplementary only | Free tier available |
| ASM Handbooks | Authoritative, broad | High | Paywalled (CMU institutional license) |

### Processing Parameter Data

This is the critical weak link. Open data on heat treatment schedules (austenitizing temperature, quench media, temper temperature/time) and thermomechanical processing (rolling reductions, finishing temperature, coiling temperature) linked to properties is sparse.

Realistic options:
- **NIMS MatNavi** — some heat treatment data for JIS steels
- **Published literature** — parsed via Semantic Scholar or S2ORC; requires NLP extraction pipeline
- **CALPHAD-computed data** — via PyCalphad + open TDB files (TPIS or community repos). Gives phase boundaries and valid processing windows, not mechanical properties directly. Use to constrain rather than predict.

### Deliverable

A structured database (SQLite or Postgres) of 500–2000 steel data points with schema:

```
composition (wt%) → target properties → processing route (where available)
```

Document coverage gaps explicitly before moving to Phase 2. Do not understate what is missing.

---

## Phase 2 — Forward Model

**Status:** Not started
**Estimated effort:** 3–5 weeks
**Dependencies:** Phase 1 complete

A reliable forward scorer is the foundation of the inverse design loop. It evaluates candidate solutions. Build this before attempting inverse design.

### Components

**Primary scorer — Gradient Boosted Model (GBM)**
Train an XGBoost or LightGBM model on the Phase 1 dataset. Simpler, interpretable, faster to iterate on, and often competitive with transformers at this data scale. This is the first deliverable — do not defer to a transformer scorer until the GBM baseline is established and evaluated.

**Processing parameter integration**
Feed processing parameters as numeric features alongside composition where data permits. If processing data coverage is insufficient, scope the forward model to composition → property only first, and treat processing as a secondary refinement layer added later.

### Deliverable

A forward scorer that accepts `(composition vector + optional processing params)` and returns `(predicted properties + confidence intervals)`. Must be evaluated on a proper held-out test set — training loss alone is not sufficient validation.

---

## Phase 3 — Inverse Design Loop

**Status:** Not started
**Estimated effort:** 4–6 weeks
**Dependencies:** Phase 2 complete

The core agent capability. Given target properties, search for compositions and processing routes.

### Approaches (ranked by tractability)

**1. Retrieval-based (start here)**
Embed the query (target properties) and retrieve nearest neighbors from the Phase 1 dataset. Fast, interpretable, grounded in real data. This should be the first working version of the agent.

**2. Constrained optimization**
Use the forward model as an objective function and optimize over composition space using Bayesian optimization (BoTorch) or differential evolution. More powerful but expensive, prone to extrapolation outside the training distribution, and harder to validate.

**3. LLM-guided search**
Use an LLM to propose candidate grades based on domain knowledge (e.g., "for high-toughness low-temperature service, consider 4340 or 300M"), then score each candidate with the forward model. Particularly effective for standard grades where the LLM has absorbed the published literature.

**Transformer ensemble scorer — AlloyBERT (fine-tuned)**
AlloyBERT (github.com/cakshat/AlloyBERT) is a RoBERTa-base model with a regression head originally trained on multi-principal element alloys (MPEAs) and refractory alloys — zero steel training data. It cannot be used off-the-shelf.

Fine-tuning plan:
- **Preferred base**: MatBERT (LBNL, github.com/lbnlp/MatBERT) is a stronger starting point than vanilla RoBERTa because it was pre-trained on materials science literature and has better tokenization for chemical formulas and processing terminology.
- **Text format**: Encode each SteelBench record as a structured sentence, e.g. `"Steel composition: C 0.42 wt%, Mn 0.75 wt%, Cr 0.95 wt%, Mo 0.20 wt%. Heat treatment: austenitized at 860 °C, oil quenched, tempered at 580 °C."` followed by the target property as a regression label.
- **Target property**: Train on UTS first — it has the best coverage in SteelBench (NIMS + EMK + Kaggle all have it). Add yield strength second.
- **Training set constraint**: Exclude NIMS rows from UTS training if those rows are already used as a test partition (they are UTS-only — good for testing forward UTS prediction in isolation).
- **Role in the pipeline**: AlloyBERT is an ensemble member alongside GBM, not the primary scorer. Its value is as a cross-check with a different inductive bias (text-based vs. tabular). Use it to flag cases where GBM and transformer disagree sharply — those are the high-uncertainty predictions.

Do not start AlloyBERT fine-tuning until the GBM baseline is complete and evaluated. The GBM answer is needed to know whether a transformer adds any value at this data scale.

### Agent Pipeline

```
1. Parse user query → target property vector + constraints
2. LLM proposes candidate steel grades (LLM-guided search)
3. Retrieve similar historical data points (FAISS retrieval)
4. Score candidates with forward model (GBM primary + AlloyBERT ensemble)
5. Filter by CALPHAD/Andrews phase feasibility
6. Rank and return top-3 candidates
```

### Deliverable

Given a property target, return the top-3 candidate grades with predicted properties, associated confidence, and a preliminary processing route sketch.

---

## Phase 4 — Processing Detail Expansion

**Status:** Not started
**Estimated effort:** 4–6 weeks
**Dependencies:** Phase 3 complete; CALPHAD integration optional but strongly recommended

This phase transforms a candidate steel grade into a detailed, actionable processing route.

### The Core Challenge

Precise process recommendations — exact austenitizing temperatures, quench severity, temper time — require either a CALPHAD model calibrated to the specific composition or a retrieval system over well-annotated literature. Generic LLM output in this space sounds confident but is unreliable for anything outside standard grades. The agent should be explicit about this distinction.

### Approach

**Processing template library**
Build parameterized recipe templates for major steel processing families:

| Route | Key Parameters |
|-------|---------------|
| Quench and temper (Q&T) | Austenitizing temp/time, quench medium, temper temp/time |
| Normalize and temper | Normalizing temp, air cool, temper temp/time |
| TMCP (thermomechanical controlled processing) | Reheat temp, rolling schedule, finishing temp, coiling temp |
| Case hardening (carburize/nitride) | Atmosphere, case depth target, temp/time |
| Austempering | Austenitize, quench to bainite temp, hold time |

**Parameter filling**
Use CALPHAD (PyCalphad) to compute Ac1/Ac3 transformation temperatures for a given composition. These directly set the austenitizing window and are more reliable than generic lookup tables for non-standard compositions.

For AISI standard grades, use curated lookup tables — they are more reliable than any model.

**Output grounding**
Each parameter in the output should be tagged as either model-derived or literature-grounded. Do not mix them without flagging which is which.

### Deliverable

Given a steel grade + geometry + target hardness/property profile, output a processing route specifying key temperatures, times, and sequences. Each parameter is tagged by its source and confidence level.

---

## Phase 5 — Cost and Manufacturability

**Status:** Not started
**Estimated effort:** 1–2 weeks
**Dependencies:** Phase 3 complete

### Scope (what is realistic)

- **Alloy surcharge cost:** Compute $/ton based on composition and current LME spot prices for alloying elements plus scrap base. This is tractable and useful.
- **Processing cost multiplier:** Apply a rough cost multiplier per route type (e.g., Q&T adds ~$X/ton vs. normalized). Rough order-of-magnitude, not a quote.

### What is out of scope

Raw material cost and manufacturing cost can differ by 3–10×. Actual manufacturing cost depends on furnace type, batch size, geography, and equipment availability. The agent should not attempt to compute this and should communicate the uncertainty explicitly.

---

## Deprioritized Items

These are explicitly out of scope for v1:

| Item | Reason |
|------|--------|
| Real-time supplier lookup | Low value, high maintenance; no stable open API |
| Novel composition generation (outside known steel families) | Insufficient data to validate outputs safely |
| Welding/joining recommendations | Separate domain with its own data requirements |
| Uncertainty quantification beyond confidence intervals | Research-level problem; out of scope for this stage |

---

## Technical Stack (Proposed)

| Component | Tool |
|-----------|------|
| Orchestration | Python + MCP server architecture |
| Database | SQLite (prototype) → Postgres (production) |
| Forward model (primary) | XGBoost/LightGBM (GBM) — built first in Phase 2 |
| Forward model (ensemble) | AlloyBERT fine-tuned on SteelBench; MatBERT recommended as base over RoBERTa — Phase 3 only |
| CALPHAD | PyCalphad + open TDB files |
| Inverse search | BoTorch (Bayesian opt) + FAISS (retrieval) |
| Cost data | LME API or scraped spot prices |
| LLM backbone | Claude (via Anthropic API) |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Phase 1 data insufficient for processing params | High | High | Scope forward model to composition → property only; add processing layer later |
| AlloyBERT performance insufficient on target steel subset | Medium | Medium | Fall back to GBM; treat AlloyBERT as one ensemble member |
| CALPHAD TDB files unavailable for target compositions | Medium | Medium | Use empirical transformation temp correlations (e.g., Andrews equations) as fallback |
| Forward model extrapolates outside training distribution | High | High | Hard-constrain composition search to known steel families; flag out-of-distribution predictions |
| LLM outputs unreliable processing parameters | High | High | LLM only proposes candidates; all parameters must be validated by forward model or lookup |

---

## Success Criteria

**Phase 1:** Structured database with documented coverage; processing-parameter gaps explicitly quantified.

**Phase 2:** Forward scorer achieves R² > 0.85 on held-out test set for yield strength and hardness prediction on standard AISI grades.

**Phase 3:** Agent returns a valid top-3 candidate list for at least 80% of well-posed queries; retrieval baseline evaluated before optimization methods.

**Phase 4:** Processing routes for standard grades match published heat treatment guidelines within ±15°C on critical temperatures.

**Phase 5:** Alloy surcharge cost estimates within ±10% of independently-computed values.
