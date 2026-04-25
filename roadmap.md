# Steel Processing Recommendation Agent — Project Roadmap

**Project:** Inverse alloy design agent for steels
**Goal:** Given a target property profile and constraints, output ranked steel grade candidates with detailed processing routes, predicted properties with uncertainty, and cost estimates.
**Author:** Alex (arz2@andrew.cmu.edu), Carnegie Mellon University
**Last Updated:** 2026-04-22

---

## Problem Statement

This agent solves an inverse materials design problem: given a target property profile (strength, toughness, hardness, corrosion resistance, etc.) and constraints (budget, geometry, available equipment), output a steel grade and processing route that plausibly achieves it.

The output is a ranked set of candidates with associated uncertainty — not a deterministic engineering answer. That distinction matters and should be communicated to users throughout.

---

## Novelty and Contributions

A literature review (see `literature_review/literature_review.md`) confirms the following positioning:

**Forward property prediction for steels is a solved problem.** Random forests, GBMs, TabPFN, and domain-specific LLMs (SteelBERT) all perform this task well. This is not a contribution of this project — it is infrastructure.

**The contributions are:**

1. **Physics-informed two-stage forward model.** Rather than mapping composition + processing → properties directly, the model routes through CALPHAD-computed thermodynamic intermediate variables (Ac1, Ac3, Ms, Bs, equilibrium phase fractions at key temperatures). This grounds the forward model in physical reality, improves generalization to non-standard compositions, and — critically — makes the model architecture defensible to materials science reviewers in a way that pure regression is not. No published steel ML paper uses this formulation. The comparison against a direct-regression GBM baseline is the primary methodological evaluation in Phase 2.

2. **Quantitative processing route recommendation from a property target.** No published work produces a specific, parameterized heat treatment schedule (austenitizing temperature, quench medium, temper temperature/time) from a user-specified property target across multiple steel families. SteelBERT (Acta Materialia 2025) suggests one qualitative route for one steel family with no quantitative parameters. The TMCP paper (Sci. Rep. 2021) covers one route family only.

3. **Calibrated three-signal uncertainty.** Materials ML papers routinely report R² and label it uncertainty quantification. This pipeline produces empirically calibrated prediction intervals plus two additional orthogonal signals (ensemble disagreement, data distance), with coverage verified against a chemistry-stratified held-out set. This is a methodological contribution regardless of the application domain.

4. **Multi-route coverage.** Q&T, normalize-and-temper, TMCP, austempering, and case hardening within a unified pipeline, with route classification as an explicit ML task.

5. **Agentic pipeline for wrought steels.** MCP-based multi-agent alloy evaluation exists for additive manufacturing alloys only. This project applies that architecture to wrought/heat-treated steels.

6. **Cost estimation with sensitivity.** Not present in any steel design paper.

**What to avoid claiming as novel:** direct composition → property prediction, use of LLMs for materials queries, retrieval-based candidate ranking, CALPHAD for phase validation. These are all established. The novel claims are the two-stage model architecture, the uncertainty framework, and the integrated pipeline connecting them to actionable processing recommendations.

**Publication positioning:** the two-stage forward model (contribution 1) is the component that differentiates this from a system paper and enables submission to npj Computational Materials or Acta Materialia. Without it, the paper is mid-tier. With a rigorous ablation (two-stage vs. direct GBM, family-stratified evaluation, empirical calibration plots), the paper has a clear methodological argument.

---

## Architecture Overview

The agent is a pipeline, not a monolithic model:

```
User Query
  → Parse target + constraints
  → Generate candidates (LLM + retrieval)
  → Feasibility pre-filter (composition rules + empirical bounds)  ← cheap gate, runs first
  → Retrieve nearest real data points (FAISS)                      ← grounding backbone
  → CALPHAD feature computation (Ac1, Ac3, Ms, Bs, phase fractions) ← thermodynamic intermediate
  → Score candidates: [composition + processing + CALPHAD features] → GBM → properties
  → MatBERT ensemble scorer (parallel)
  → Compute uncertainty (tree variance + ensemble disagreement + data distance)
  → OOD flag (if FAISS distance > threshold)
  → CALPHAD phase validation (route feasibility check)
  → Processing route (route classification → parameter estimation)
  → Cost + sensitivity
  → Ranked candidates with grounded predictions + uncertainty
```

Each stage is a discrete, testable component. This keeps the system auditable and allows individual components to be swapped or improved independently.

Key design decisions reflected in this order:
- Feasibility pre-filter runs **before** scoring to avoid wasting model calls on metallurgically impossible candidates.
- CALPHAD features are computed **as inputs to the forward model**, not only as a validation gate. This is the two-stage architecture: composition + processing → thermodynamic features → mechanical properties.
- Retrieval is a **backbone**, not a step — nearest neighbors attach to every prediction as grounding evidence.
- Uncertainty is **three-signal** (model variance, ensemble disagreement, data distance) and calibrated against held-out coverage, not just reported as nominal intervals.
- Processing is **two-layer**: route classification (ML, high confidence) followed by parameter estimation (CALPHAD/lookup tables, reported as ranges).

---

## Phase 1 — Data Foundation

**Status:** In progress (~85% complete)
**Estimated effort:** 4–8 weeks
**Risk level:** High — this is the most likely point of failure for the project

The data layer is the bottleneck. Most projects in this space fail here, not at the modeling stage. Know your coverage before writing agent code.

### Current State (as of 2026-04-22)

**~4,014 property rows, ~3,670 unique steels** across 12 ingested sources. See `data/DATA.md` for full source inventory and coverage gaps.

| Source | Records | Reliability | Notes |
|--------|---------|-------------|-------|
| SteelBench v1.0 (NIMS/EMK/Kaggle) | 1,360 | 2–5 | YS, UTS, hardness; sparse processing |
| ASM Vol.1 (Knovel exports) | 385 | 4 | Carbon/alloy compositions + bar properties |
| ASM Vol.4 (Q&T curves, anneal, stainless) | 225 | 4 | Primary HRC source; austenitize/quench/temper triples |
| S.K. Mondal textbook appendix | 272 | 4 | SAE grade compositions + coarse processing |
| Cheng et al. 2024 Fe–C–Mn–Al | 580 | 3 | Most processing-rich; no yield |
| NIMS fatigue DB (Agrawal 2014) | 437 | 5 | Only `fatigue_limit_MPa` source; full Q&T + carburize params |
| Others (Figshare, Zenodo, ASTM specs, AZoM) | ~755 | 2–4 | Composition + properties; sparse processing |

**Remaining critical gaps** (see `data/DATA.md` for full list):
- `hardness_HRC` — data downloaded (~243 records from ASM tempering curves + ~66 tool steel records). Parsers not yet written. Medium-high priority.
- `fracture_tough_KIC` — only 2 rows. Need 300M/H11/H13/D-6A tables.
- Tool steels — data downloaded (ASM Vol.4 hardening/tempering tables, 66 grades). Parser not yet written.
- Maraging aging parameters — 0%.

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

### Additional Phase 1 Deliverables (beyond database)

**Composition constraint tables per steel family**
Before any inverse design work, hard-code the valid composition ranges for each steel family (carbon, low-alloy, HSLA, stainless, tool, maraging). These bounds constrain the search space in Phase 3 and prevent the optimizer from generating metallurgically impossible candidates. Source from AISI/ASTM grade specifications — not from the training data. Families and their primary constraints:

| Family | Key bounds |
|--------|-----------|
| Carbon | C ≤ 1.0%, Si ≤ 0.6%, low alloy additions |
| Low-alloy (AISI 4xxx/8xxx) | C 0.1–0.65%, Cr + Ni + Mo ≤ ~5% total |
| HSLA structural | C ≤ 0.25%, yield via microalloying (V/Nb/Ti), no quench required |
| Martensitic stainless | Cr 11–18%, C 0.1–1.2%, low Ni |
| Austenitic stainless | Cr ≥ 16%, Ni ≥ 8%, C ≤ 0.08% (or ≤ 0.03% for L grades) |
| Tool steel | C 0.5–2.5%, high Cr/Mo/W/V combinations by sub-family |
| Maraging | C ≤ 0.03%, Ni 17–19%, Co 7–10%, Mo 3–6%, Ti 0.2–1.7% |

Carbon equivalent (CE) should also be computed per-candidate as a weldability check: `CE = C + Mn/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15`. CE > 0.45 flags poor weldability.

**Chemistry-stratified train/test split**
Do not use a random split. A random split allows the test set to contain compositions nearly identical to training samples — the model will appear to generalize well even if it is only memorizing near-neighbors. Instead, cluster compositions (e.g., k-means on normalized element space) and hold out entire clusters as the test set. This is the split that will be used for all Phase 2 evaluation. Define and freeze it at the end of Phase 1 so it cannot be adjusted after seeing model performance.

**Database deliverable**

A structured database (SQLite or Postgres) with schema:

```
composition (wt%) → target properties → processing route (where available)
```

Document coverage gaps explicitly before moving to Phase 2. Do not understate what is missing.

---

## Phase 2 — Forward Model

**Status:** Not started
**Estimated effort:** 3–5 weeks
**Dependencies:** Phase 1 complete (including stratified split)

A reliable forward scorer is the foundation of the inverse design loop. It evaluates candidate solutions. Build this before attempting inverse design.

### Components

**Step 1 — CALPHAD feature engineering (run before any ML)**
For every composition in the dataset, compute the following thermodynamic features using PyCalphad with an open TDB file:
- Ac1, Ac3 (austenite start/finish on heating)
- Ms (martensite start on cooling)
- Bs (bainite start on cooling)
- Equilibrium phase fractions at 850°C, 1000°C, and 1200°C (austenite, ferrite, carbide)

These features encode the composition's thermodynamic identity in a physically meaningful way that raw wt% vectors do not. Compositions that look similar in wt% space can have very different transformation temperatures and phase stability — those differences are exactly what controls properties.

For compositions where TDB coverage is incomplete (typically high-Mn, high-Al, or multi-principal element grades), fall back to Andrews empirical equations for Ms/Ac1/Ac3 and flag those records as `[empirical CALPHAD]` in the feature table. Do not discard them — the empirical features still carry useful signal, just less precise.

Precompute and cache these features for the full training set. At inference time, compute on-demand for candidate compositions. For standard AISI grades, cache lookups.

**Step 2 — Two-stage GBM (the primary contribution)**
Train two models and compare them rigorously:

*Baseline:* Direct GBM — inputs are composition vector + processing params only, no CALPHAD features. This replicates the arXiv:2003.01943 approach and is the comparison point for the paper.

*Two-stage model:* GBM with CALPHAD thermodynamic features appended to the input. Inputs are composition + processing + {Ac1, Ac3, Ms, Bs, phase fractions}. This is the novel architecture.

The comparison between these two models on the same chemistry-stratified held-out set is the central result of Phase 2 and the primary evidence for the CALPHAD intermediate contribution. If the two-stage model does not outperform the baseline, the contribution claim weakens substantially — that outcome needs to be reported honestly, not massaged.

**Processing parameter integration**
Feed processing parameters as numeric features alongside composition and CALPHAD features where data permits. If processing data coverage is insufficient, scope the forward model to composition + CALPHAD features → property first, and add processing as a secondary refinement layer later.

**Interval calibration**
GBM confidence intervals are systematically miscalibrated by default. After training, fit isotonic regression (or Platt scaling) on the held-out set to calibrate the intervals. The calibrated model — not the raw GBM output — is what enters Phase 3. A 95% prediction interval that covers only 70% of held-out observations is not a 95% interval; it is a miscalibrated one.

**FAISS distance index**
Build a FAISS index over the training set. **Do not use raw L2 distance on wt% vectors.** A 0.5 wt% difference in C is metallurgically far more significant than a 0.5 wt% difference in Cu, and raw L2 treats them identically. Instead, weight the composition dimensions by GBM feature importance scores from the trained model — this produces a distance metric consistent with what the model has learned to care about. Build the index after training, using importance-weighted composition vectors.

Both the retrieval use and the uncertainty S3 signal depend on this index being built correctly.

### Deliverable

Two trained forward scorers (baseline + two-stage), with rigorous comparative evaluation on the chemistry-stratified held-out test set. Calibrated intervals for the two-stage model. FAISS index with importance-weighted distance metric. Ablation table showing performance improvement from CALPHAD features, broken down by steel family.

---

## Phase 3 — Inverse Design Loop

**Status:** Not started
**Estimated effort:** 4–6 weeks
**Dependencies:** Phase 2 complete (GBM + calibrated intervals + FAISS index)

The core agent capability. Given target properties, search for compositions and processing routes.

### Candidate Generation

Three complementary methods run in parallel and merge before scoring:

**1. Retrieval-based (primary)**
Embed the target property vector and retrieve nearest neighbors from the training set via FAISS. Fast, grounded in real data, produces immediately interpretable candidates. This should be the first working version of the agent, and the one used to establish the retrieval baseline before adding optimization.

**2. LLM-guided search**
Use an LLM to propose candidate grades from domain knowledge (e.g., "for high-toughness low-temperature service, consider 4340 or 300M"). Particularly effective for standard grades. LLM output is candidate grade names only — no processing parameters from the LLM.

LLM output is a grade name, not a composition. A **grade → nominal composition lookup table** is required to convert grade names into composition vectors before the feasibility pre-filter and CALPHAD feature computation can run. This lookup table must be built and tested as part of Phase 3 setup. Source: AISI/ASTM grade specification tables already ingested in Phase 1. If a proposed grade name is not in the lookup table, the candidate is flagged as unknown and dropped before scoring — do not hallucinate compositions.

**3. Constrained optimization (add last)**
Use the GBM as an objective function and optimize over composition space within the family-specific bounds defined in Phase 1. BoTorch or differential evolution. Do not attempt this before the retrieval baseline is evaluated — optimization without constraints will find degenerate solutions, and you need the baseline to know whether optimization adds value.

### Feasibility Pre-filter

Before scoring, run every candidate through a fast rules-based gate. This is cheap and eliminates metallurgically impossible candidates before they consume model calls.

Checks to include:
- Composition within family bounds (from Phase 1 constraint tables)
- Carbon equivalent within weldability limits (if weldability is a user constraint)
- Empirical martensite formation bound (Andrews Ms equation): if target route is Q&T but Ms < 150°C for the composition, flag for review
- Basic phase stability: austenitic stainless requires Ni ≥ 8% + sufficient Cr; maraging requires C ≤ 0.03%

This layer uses empirical rules, not CALPHAD. CALPHAD runs later as the physics validation step. Do not use Andrews equations as a substitute for CALPHAD for non-standard compositions — use them only as a pre-filter.

### Retrieval as Grounding Backbone

Every scored prediction must attach its nearest neighbors from the training set. The output format is:

```
Predicted UTS: 950 MPa  [80% CI: 900–1010 MPa]
Grounded by 3 similar steels: 4340 (920 MPa), 4340H (965 MPa), 8640 (945 MPa)
Processing routes on similar steels: austenitize 845–870°C, oil quench, temper 540–595°C
```

This is not decoration. It directly addresses the main failure mode of pure ML recommenders: outputs that are statistically plausible but not grounded in any real material. If retrieval finds no close neighbors (FAISS distance above threshold), the prediction is flagged OOD regardless of model confidence.

### Three-Signal Uncertainty

Every prediction reports three uncertainty signals, not one:

| Signal | Source | What it measures |
|--------|--------|-----------------|
| Model variance | GBM tree variance across the ensemble | Epistemic: model disagreement |
| Ensemble disagreement | ∣GBM prediction − MatBERT prediction∣ | Cross-architecture divergence: flag high-uncertainty compositions |
| Data distance | FAISS L2 distance to nearest training neighbors | Extrapolation risk: how far from known data |

The calibrated interval from Phase 2 integrates model variance. Ensemble disagreement and data distance are reported separately as qualitative flags, not folded into the interval — combining them would require calibrating the combined signal, which is a harder problem than it looks.

**OOD flag:** if FAISS distance to nearest training neighbor exceeds a threshold set at the 95th percentile of training set self-distances, the prediction is flagged: ⚠️ *Outside training distribution — use with caution.*

### Transformer Ensemble Scorer — MatBERT fine-tuned

Do not start fine-tuning until GBM baseline is complete and evaluated. The GBM answer is needed to determine whether a transformer adds signal at this data scale.

Fine-tuning plan:
- **Base model**: MatBERT (LBNL, github.com/lbnlp/MatBERT) — pre-trained on materials science literature, better tokenization for chemical formulas and processing terms than vanilla RoBERTa.
- **Text format**: encode each record as a structured sentence: `"Steel composition: C 0.42 wt%, Mn 0.75 wt%, Cr 0.95 wt%, Mo 0.20 wt%. Heat treatment: austenitized at 860 °C, oil quenched, tempered at 580 °C."` → regression label.
- **Target**: UTS first (best coverage), yield strength second.
- **Role in pipeline**: ensemble member for disagreement signal only, not primary scorer. If GBM and MatBERT agree closely, report higher confidence. If they diverge sharply, raise uncertainty flag.
- **Do not use MatBERT as a weak label generator** for records missing processing data. Inferring labels from a model and then training on those labels creates correlated errors that are undetectable in evaluation. Missing processing data stays missing.

### Agent Pipeline

```
1. Parse user query → target property vector + constraints
2. Generate candidates (retrieval + LLM + optionally: constrained optimization)
3. Feasibility pre-filter (composition bounds + empirical rules — cheap gate)
4. Retrieve nearest real data points (FAISS); attach as grounding evidence
5. Score candidates (GBM primary + MatBERT ensemble)
6. Compute uncertainty (tree variance + ensemble disagreement + data distance)
7. Apply OOD flag where FAISS distance exceeds threshold
8. CALPHAD phase validation
9. Preliminary processing route sketch (route classification only at this stage)
10. Rank and return top-3 candidates with grounded predictions + uncertainty
```

### Deliverable

Given a property target, return the top-3 candidate grades, each with: predicted properties + calibrated intervals, three uncertainty signals, nearest-neighbor grounding evidence, OOD flag if applicable, and a preliminary processing route classification.

---

## Phase 4 — Processing Detail Expansion

**Status:** Not started
**Estimated effort:** 4–6 weeks
**Dependencies:** Phase 3 complete; CALPHAD integration optional but strongly recommended

This phase transforms a candidate steel grade into a detailed, actionable processing route.

### The Core Challenge

Precise process recommendations — exact austenitizing temperatures, quench severity, temper time — require either a CALPHAD model calibrated to the specific composition or a retrieval system over well-annotated literature. Generic LLM output in this space sounds confident but is unreliable for anything outside standard grades. The agent should be explicit about this distinction.

### Two-Layer Processing Approach

Processing recommendation is split into two distinct layers with different confidence profiles. Do not conflate them.

**Layer 1 — Route classification (ML, high confidence)**
Classify the candidate into a processing route family: Q&T, normalize-and-temper, TMCP, austempering, case hardening. This is a 5-class classification problem. The existing dataset (NIMS fatigue + SteelBench + ASM Vol.4) has decent route labels and this layer should achieve high accuracy. Output is a route family with a confidence score.

**Layer 2 — Parameter estimation (CALPHAD + lookup tables, reported as ranges)**
Given a route classification, fill in the key process parameters. These are never single point estimates — they are ranges unless directly supported by a lookup table for the specific grade.

| Route | Parameters | Primary Source |
|-------|-----------|----------------|
| Q&T | Austenitizing temp/time, quench medium, temper temp/time | CALPHAD (Ac1/Ac3) for non-standard; ASM lookup for AISI grades |
| Normalize-and-temper | Normalizing temp, temper temp/time | CALPHAD + ASM lookup |
| TMCP | Reheat temp, finishing temp, coiling temp | Empirical correlations; sparse data coverage |
| Case hardening | Atmosphere, case depth target, carburize temp/time | Empirical; limited dataset coverage |
| Austempering | Austenitizing temp, bainite hold temp/time | CALPHAD Ms/Bs computation |

**Parameter source tagging**
Every parameter in the output must be tagged as: `[CALPHAD]`, `[lookup: ASM grade table]`, `[retrieval: similar steel]`, or `[empirical correlation]`. Do not mix sources without flagging which is which. LLM-generated parameter values are not permitted in Layer 2 output.

**Output grounding**
For standard AISI grades, curated lookup tables beat any model — use them preferentially. Reserve CALPHAD for compositions outside the AISI grade system. For genuinely novel compositions, output ranges wider than the dataset would suggest and say so explicitly.

### Deliverable

Given a steel grade + route classification from Phase 3, output a processing route specifying parameterized temperatures, times, and sequences. Each parameter tagged by source. Parameters reported as ranges unless a specific grade lookup is available.

---

## Phase 5 — Cost and Manufacturability

**Status:** Not started
**Estimated effort:** 1–2 weeks
**Dependencies:** Phase 3 complete

### Scope (what is realistic)

- **Alloy surcharge cost:** Compute $/ton based on composition and current LME spot prices for alloying elements plus scrap base. This is tractable and useful.
- **Processing cost multiplier:** Apply a rough cost multiplier per route type (e.g., Q&T adds ~$X/ton vs. normalized). Rough order-of-magnitude, not a quote.
- **Cost sensitivity:** For each ranked candidate, compute ∂cost/∂x for the major alloying elements (Ni, Mo, Cr, Co). This tells the user which elements are driving cost and is often more actionable than the total cost figure — e.g., "this recommendation is Ni-sensitive: ±1% Ni changes cost by ±$85/ton."

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
| RL/active learning feedback loops | Adds complexity before core prediction quality is established; revisit post-v1 |
| Heavy unconstrained optimization (BoTorch without bounds) | Degenerate solutions without composition family constraints; add only after constraint layer is proven |
| Section size / hardenability coupling | Correct processing route for a given composition depends on part geometry (cross-section). A 4340 oil-quenched at 25mm through-hardens; at 100mm it does not. Out of scope for v1 — add as a user input constraint in a future version. |

---

## Technical Stack (Proposed)

| Component | Tool |
|-----------|------|
| Orchestration | Python + MCP server architecture |
| Database | SQLite (prototype) → Postgres (production) |
| Forward model (primary) | XGBoost/LightGBM (GBM) — built first in Phase 2 |
| Forward model (ensemble) | MatBERT (LBNL) fine-tuned on SteelBench — ensemble disagreement signal only; add only after GBM baseline is evaluated |
| CALPHAD | PyCalphad + open TDB files |
| Inverse search | BoTorch (Bayesian opt) + FAISS (retrieval) |
| Cost data | LME API or scraped spot prices |
| LLM backbone | Claude (via Anthropic API) |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Phase 1 data insufficient for processing params | High | High | Scope forward model to composition → property only; add processing layer later |
| MatBERT ensemble adds noise rather than signal at this data scale | Medium | Medium | Evaluate GBM baseline first; if ensemble disagreement signal is uncorrelated with actual error, drop the transformer and use GBM-only with tree variance |
| CALPHAD TDB files unavailable for target compositions | Medium | Medium | Use Andrews equations as pre-filter only; report wider parameter ranges and flag as `[empirical]` |
| Forward model extrapolates outside training distribution | High | High | FAISS OOD flag + hard composition family constraints — these are the primary defenses |
| LLM outputs unreliable processing parameters | High | High | LLM only proposes candidate grade names; all process parameters come from CALPHAD, lookup tables, or retrieval — never from the LLM directly |
| Calibration failure: GBM intervals don't cover stated percentage | High | High | Mandatory isotonic regression calibration on held-out set; report empirical coverage rate alongside nominal coverage in evaluation |
| Train/test leakage from random split giving falsely good OOD metrics | Medium | High | Chemistry-stratified split defined and frozen in Phase 1 before any modeling |
| Feasibility pre-filter too aggressive, rejecting valid candidates | Low | Medium | Track pre-filter rejection rate; if > 20% of LLM-proposed candidates are rejected, audit the rules |
| CALPHAD feature computation too slow at inference time | Medium | Medium | Precompute and cache for all training compositions + all standard AISI grades; only run on-demand for novel compositions. Andrews fallback for TDB gaps. |
| Two-stage model does not outperform direct GBM | Medium | High | If CALPHAD features add no signal, investigate whether TDB coverage is too sparse and whether Andrews-derived features carry any signal independently. Report the result regardless — negative results on this comparison are publishable as a finding. |
| CALPHAD TDB coverage gaps for specialty grades (tool steels, high-Mn, maraging) | High | Medium | Use Andrews empirical equations as fallback; tag features as [empirical]. Widen prediction intervals for those compositions to reflect the lower-fidelity thermodynamics. |

---

## Success Criteria

**Phase 1:**
- Structured database with documented coverage and coverage gaps explicitly quantified.
- Composition constraint tables defined per steel family and committed to code.
- Chemistry-stratified train/test split defined, frozen, and documented before any modeling begins.

**Phase 2:**
- Two-stage GBM (CALPHAD features) outperforms direct GBM baseline on chemistry-stratified held-out test set. If it does not, investigate why and report honestly — do not discard the baseline result.
- Performance reported **family-stratified** (carbon, low-alloy, HSLA, stainless, tool, maraging) in addition to aggregate. A model with aggregate R² = 0.90 that scores R² = 0.30 on tool steels is not a good model. Aggregate metrics alone will not pass peer review from reviewers who know the field.
- Direct comparison against arXiv:2003.01943 (same NIMS dataset, random forest baseline) on the overlapping test samples. This is the published benchmark for this task.
- Calibrated 90% prediction intervals cover ≥ 88% of held-out observations (within 2% of nominal is acceptable; systematic undercoverage is not). Calibration curve (expected vs. actual coverage) produced as a paper figure.
- FAISS index built with importance-weighted distance metric; self-distance distribution and OOD threshold documented.

**Phase 3:**
- Agent returns a valid top-3 candidate list with grounded nearest-neighbor evidence for ≥ 80% of well-posed queries.
- Retrieval baseline evaluated before optimization is added. Optimization only added if it improves ranking quality on a defined benchmark.
- OOD flag correctly identifies held-out compositions from underrepresented families (tool steels, maraging) at > 80% recall.
- Ensemble disagreement signal is positively correlated with actual prediction error — if it is not, the transformer member is dropped.

**Phase 4:**
- Processing route classification achieves ≥ 90% accuracy on route family (Q&T vs. normalize vs. TMCP etc.) on held-out records with known routes.
- CALPHAD-derived austenitizing windows match published values for standard AISI grades within ±15°C.
- All output parameters tagged by source; no untagged parameter estimates in any output.

**Phase 5:**
- Alloy surcharge cost estimates within ±10% of independently-computed values.
- Cost sensitivity (∂cost/∂element) reported for the top-3 alloying elements in each recommendation.
