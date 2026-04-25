# Literature Review: Steel Processing Recommendation Agent

**Last Updated:** 2026-04-22
**Purpose:** Establish prior art, identify gaps, and position the contributions of this project.

---

## Summary Verdict

Forward property prediction for steels from composition and processing parameters is a crowded, well-solved space. The genuine gap — and the contribution of this project — is the end-to-end agentic pipeline that takes a target property profile and returns an explainable, quantitative processing route. No published work does this, even crudely.

---

## Closest Prior Work

### 1. TMCP Steel Forward + Inverse Platform
**Reference:** "A machine-learning-based alloy design platform that enables both forward and inverse predictions for thermo-mechanically controlled processed (TMCP) steel alloys," *Nature Scientific Reports*, 2021.
**URL:** https://www.nature.com/articles/s41598-021-90237-z

**What it does:** Builds both a forward model (composition + TMCP parameters → properties) and a genetic-algorithm-based inverse model for TMCP steels.

**Inputs:** Chemical composition + TMCP processing parameters (finishing temperature, coiling temperature, reduction ratio).
**Outputs:** Yield strength, UTS, elongation.

**Why it matters:** Most directly comparable paper. Demonstrates the forward + inverse loop is tractable for a specific steel family.

**Key gaps:**
- Scoped exclusively to TMCP (one processing route family). Does not handle quench-and-temper, normalize-and-temper, austempering, or case hardening.
- Inverse design uses a genetic algorithm — no agent interface, no natural language query, no explainability.
- No cost component.
- No processing parameter generation beyond the TMCP-specific variables it was trained on.

---

### 2. SteelBERT — Steel Design with LLM
**Reference:** "Steel design based on a large language model," *Acta Materialia*, 2025.
**PDF:** `tian_2025_steelbert_llm_steel_design.pdf`
**URL:** https://www.sciencedirect.com/science/article/abs/pii/S1359645424010115
**Code + data:** https://github.com/mgedata/SteelScientist | Model: https://huggingface.co/MGE-LLMs/SteelBERT

**What it does:** Pretrains a DeBERTa-based model (SteelBERT) on 4.2M materials science abstracts + 55K full-text steel articles. Encodes composition and fabrication process as natural language, predicts YS/UTS/elongation. Fine-tunes on 64 experimental 15Cr austenitic stainless samples to demonstrate adaptation.

**Performance:** R² = 0.78–0.83 (general literature model), 0.87–0.90 (fine-tuned on 15Cr stainless).

**Inputs:** Natural language description of composition and fabrication process sequence.
**Outputs:** YS, UTS, elongation. One optimized fabrication sequence suggestion for the 15Cr case study.

**Why it matters:** The closest paper to our LLM-based approach. Demonstrates that NLP over steel literature can encode processing knowledge.

**Published training dataset:** `datasets/data.csv` in the GitHub repo — 677 rows NLP-extracted from 157 DOIs. **Not worth ingesting:** material names are generic ("Steel 1", "Sample A"), Fe stored as balance (not in composition columns), processing in free-text paragraphs only, reliability ~2. The dataset encodes composition + processing text + YS/UTS/elongation.

**Key gaps:**
- Fabrication sequence "recommendation" is rudimentary: suggests "cold rolling + tempering" for one austenitic stainless case with no quantitative parameters (no temperatures, no hold times, no quench specification).
- Validated on 18 steels total for the general model; 64 samples for the specialized model. Not a systematic evaluation.
- Scoped to austenitic stainless steels for the fabrication suggestion task.
- No retrieval layer, no CALPHAD integration, no uncertainty quantification, no cost estimation.

---

### 3. Physics-Informed ML for Steel CCT Diagrams
**Reference:** "Physics-Informed Machine Learning for Steel Development: A Computational Framework and CCT Diagram Modelling," arXiv:2512.03050, 2025 preprint.
**PDF:** `hedstrom_2025_physics_ml_cct_steel.pdf`
**URL:** https://arxiv.org/abs/2512.03050

**What it does:** ML model trained on 4,100 CCT diagrams to predict phase transformation temperatures and microstructure from composition and austenitizing conditions. Generates complete CCT diagrams (100 cooling curves) in under 5 seconds.

**Performance:** Phase classification F1 > 88% for all phases. Temperature MAE < 20°C for ferrite, pearlite, martensite; bainite MAE ~27°C.

**Why it matters:** Directly applicable to Phase 4 of this project. This model can replace or augment PyCalphad for computing Ac1/Ac3 and phase transformation windows from composition — which is the critical input to processing template parameter-filling. **Contact the Hedström group at KTH for dataset access.**

**Key gaps:**
- Focused on CCT diagrams only — does not connect to mechanical property prediction or processing route recommendation.
- Welding-specific CCT scope; heat treatment CCT coverage needs verification.
- Not integrated into any agent or design pipeline.

---

### 4. Multi-Agent GNN + LLM for Alloy Design
**Reference:** "Rapid and automated alloy design with graph neural network-powered large language model-driven multi-agent AI," *MRS Bulletin*, 2025.
**URL:** https://link.springer.com/article/10.1557/s43577-025-00953-4

**What it does:** GNN-powered LLM multi-agent system for alloy design. Multiple specialized agents (knowledge retrieval, property prediction, optimization) coordinated by an LLM orchestrator.

**Why it matters:** Demonstrates the multi-agent architecture pattern this project adopts. Shows that LLM orchestration over specialized physics-aware tools is viable for alloy design.

**Key gaps:**
- Focuses on composition optimization, not processing route generation.
- Does not target steels specifically.
- No quantitative processing parameters in the output.

---

### 5. Agentic Alloy Evaluation with MCP
**Reference:** "Agentic Additive Manufacturing Alloy Evaluation," arXiv:2510.02567, *Additive Manufacturing Letters*, January 2026.
**URL:** https://arxiv.org/abs/2510.02567

**What it does:** MCP-based multi-agent system for evaluating SS316L and IN718 in additive manufacturing. Agents generate thermophysical property diagrams and lack-of-fusion process maps autonomously.

**Why it matters:** Uses the same MCP tool-calling architecture as this project. Validates the approach for materials engineering tasks.

**Key gaps:**
- Additive manufacturing only — laser powder bed fusion process maps are a completely different design space from wrought steel heat treatment.
- Two alloys only; not a general design system.
- No inverse design capability — evaluates candidate alloys, does not generate them.

---

### 6. AlloyGPT
**Reference:** "End-to-end prediction and design of additively manufacturable alloys using a generative AlloyGPT model," *npj Computational Materials*, 2025.
**URL:** https://www.nature.com/articles/s41524-025-01768-2

**What it does:** Generative LLM that performs both forward property prediction and inverse alloy design by encoding alloy data as structured text sequences.

**Why it matters:** Demonstrates that a single generative LLM can handle both forward and inverse alloy design tasks without a separate optimization loop.

**Key gaps:**
- Targets additively manufactured alloys, not wrought/heat-treated steels.
- No processing route generation — composition only.
- No cost estimation or manufacturability assessment.

---

### 7. NIMS Fatigue Strength Prediction — Agrawal et al. 2014
**Reference:** "Exploration of data science techniques to predict fatigue strength of steel from composition and processing parameters," *Integrating Materials and Manufacturing Innovation* 3:8 (2014).
**PDF:** `agrawal_2014_fatigue_strength_prediction_nims.pdf`
**URL:** https://immi.springeropen.com/articles/10.1186/2193-9772-3-8
**Data (Additional file 1):** `40192_2013_16_MOESM1_ESM.xlsx` — 437 rows, CC-BY 2.0

**What it does:** Benchmarks random forest, neural nets, and statistical models on 437 NIMS fatigue measurements. Explores feature importance for rotating-bending fatigue strength prediction from composition + heat treatment parameters (Q&T, carburizing, normalizing).

**Inputs:** Composition (C, Si, Mn, P, S, Ni, Cr, Cu, Mo) + full heat treatment parameters (austenitize temp/time, quench medium, carburize temp/time/diffusion, temper temp/time).
**Outputs:** Fatigue strength at 10⁷ cycles (MPa) — rotating bending, R=−1.

**Why it matters:** The Agrawal preprocessed extract is the **primary source of `fatigue_limit_MPa`** in this project (437 rows, NIMS reliability=5). The encoding conventions (30°C sentinel for "not used", THQCr for quench medium, QmT for carburize quench temperature) are documented here and are essential for correctly interpreting the dataset. Also establishes carbon/low-alloy steel fatigue as a solvable ML prediction task.

**Dataset status:** ✅ Ingested as `src_nims_fatigue`. Parser at `data/parsers/nims_fatigue.py`.

**Key gaps:**
- Only carbon and low-alloy SAE grades (10xx, 13xx, 4xxx, 8xxx) — no stainless, maraging, tool steels.
- 9 composition elements only — V, Nb, Ti, Al, W not measured.
- Fatigue scope only — no yield, UTS, hardness, or toughness in this dataset.
- No processing route recommendation or inverse design capability.

---

### 8. ML Approaches for Steel Mechanical Properties (NIMS Dataset Baseline)
**Reference:** "Machine Learning Approaches to Predicting and Understanding the Mechanical Properties of Steels," arXiv:2003.01943, 2020.
**URL:** https://arxiv.org/abs/2003.01943

**What it does:** Random forest + symbolic regression on 360 NIMS samples predicting fatigue strength, tensile strength, fracture strength, and hardness from composition and tempering temperature.

**Key findings:** Random forest performs best. Tempering temperature, C, Cr, Mo are the most influential features — consistent with physical understanding.

**Why it matters:** Establishes the baseline for the forward model we're building. 360 NIMS samples is the publicly cited dataset size for this task; SteelBench (1,360 samples, more properties) is a direct improvement.

**Key gaps:** Forward prediction only. No inverse design. No processing route generation.

---

### 9. Multitask Steel Property Prediction — TabPFN on TSDR
**Reference:** "Multitask-Informed Prior for In-Context Learning on Tabular Data: Application to Steel Property Prediction," arXiv:2603.22738, March 2026.
**URL:** https://arxiv.org/abs/2603.22738

**What it does:** Fine-tunes TabPFN (a transformer foundation model for tabular data) with multitask awareness for hot-rolling steel property prediction.

**Why it matters:** State-of-the-art benchmark for forward steel property prediction from composition + processing. Useful as a comparison point when evaluating our forward model in Phase 2.

**Key gaps:** Forward prediction only. Proprietary industrial TSDR dataset — not reproducible externally. No inverse design or agent capability.

---

### 10. Inverse Design of Inorganic Compounds with Generative AI (Review)
**Reference:** "Inverse Design of Inorganic Compounds with Generative AI," arXiv:2604.11827, April 2026.
**URL:** https://arxiv.org/abs/2604.11827

**What it does:** Broad review of generative AI methods (diffusion models, VAEs, GANs, LLMs, genetic algorithms) for inverse design of inorganic compounds including MOFs, zeolites, perovskites, and transition metal complexes.

**Relevance to this project:** Low for direct comparison; high for methodological context. Alloys are mentioned in passing only. The review's taxonomy of generative methods (conditional vs. unconditional generation, DL vs. EC approaches) is useful framing for how to think about our inverse design loop in Phase 3.

---

## Datasets Found in Literature

| Dataset | Records | Properties | Processing | Source | Status |
|---|---|---|---|---|---|
| SteelBench v1.0 | 1,360 | YS, UTS, elongation, Charpy, hardness | austenitize T, quench medium, temper T | NIMS + EMK + Kaggle | ✅ Ingested (`src_steelbench_*`) |
| NIMS MatNavi Fatigue DB (Agrawal 2014 extract) | 437 | fatigue_limit_MPa (rotating bending, 10⁷ cycles) | Full Q&T params + carburizing params | NIMS | ✅ Ingested (`src_nims_fatigue`) |
| Cheng et al. 2024 Fe–C–Mn–Al | 580 | UTS, elongation | Multi-step TMCP + anneal | Literature (PCCP 2024) | ✅ Ingested (`src_cheng_2024`) |
| SteelBERT training data (github.com/mgedata/SteelScientist) | 677 | YS, UTS, elongation | Free-text only | NLP-extracted from 157 DOIs | ❌ Not worth ingesting — generic names, no grade IDs, processing unstructured |
| NETL 9% Cr microstructure dataset (Rozman 2022) | ~33 alloys | YS, UTS, elongation, RA | Normalized + tempered (no temps) | NETL ORNL | ❌ Skip — CC-BY-NC-ND, specialty non-standard alloys, no processing params |
| TSDR industrial hot-rolling dataset (arXiv 2603.22738) | Undisclosed | YS, UTS, elongation | Hot-rolling parameters | Proprietary industrial | ❌ Not accessible |
| CCT diagram dataset (arXiv 2512.03050) | 4,100 diagrams | Phase fractions, transformation temps | Austenitizing conditions + cooling rates | KTH / literature | ⏳ Not released — contact Hedström group (pheds@kth.se) |
| All-in-One Steel Data v1.0 — CCT/TTT | 9,843 diagrams | Transformation temps (Ac1, Ac3, Ms, Bs), phase fractions | Austenitizing temp, grain size, cooling rates | steeldata.info | ⏳ $800 single-user license; free 200-diagram demo at steeldata.info |
| All-in-One Steel Data v1.0 — Tempering | 2,877 diagrams | Hardness vs. temper temperature curves | Temper temperature | steeldata.info | ⏳ Same license |
| All-in-One Steel Data v1.0 — Hardenability | 2,026 diagrams | Jominy hardness profiles | Austenitizing conditions | steeldata.info | ⏳ Same license |

---

## Gap Analysis — Where This Project is Novel

| Capability | State of the Art | This Project |
|---|---|---|
| Forward property prediction from composition | Solved — RF, GBM, TabPFN all perform well | Implemented as an internal scoring tool, not the contribution |
| Composition inverse design (property → composition) | Partial — TMCP paper (GA-based), SteelBERT (rudimentary) | Extends to multi-family steels with retrieval + optimization |
| **Processing route recommendation** | **Essentially absent** — SteelBERT suggests one qualitative route for one case | **Core contribution: quantitative route with temperatures, hold times, quench medium** |
| **Agentic pipeline (LLM orchestrator + tools)** | MCP agent demonstrated for AM alloys only | **Novel for wrought/heat-treated steels** |
| **Multi-route coverage** (QT, NT, TMCP, case harden, austemper) | TMCP paper covers TMCP only | **Cross-route coverage** |
| **CCT-informed processing windows** | CCT ML model exists but not integrated into any design pipeline | Integration with Phase 4 processing template engine |
| **Cost estimation** | Not present in any steel design paper | Novel component |
| Natural language query interface | SteelBERT accepts natural language input | Adopted and extended |

---

## Recommended Reading Order

1. arXiv:2003.01943 — baseline, establishes what the NIMS data can do with simple models
2. Nature Sci. Rep. 2021 (TMCP) — closest prior work, understand its scope and limitations
3. Acta Materialia 2025 (SteelBERT) — closest to our LLM approach, read critically
4. arXiv:2512.03050 (CCT ML) — directly applicable to Phase 4, contact authors for data
5. MRS Bulletin 2025 (multi-agent GNN + LLM) — architecture reference
6. arXiv:2604.11827 (generative AI review) — methodological context for Phase 3

---

## Action Items from Literature Search

### Completed
- [x] **Ingest NIMS fatigue DB** (Agrawal 2014 extract, Additional file 1) — 437 rows, `src_nims_fatigue`, parser at `data/parsers/nims_fatigue.py` *(done 2026-04-22)*
- [x] **Scavenge SteelBERT training dataset** — rejected; generic material names, Fe stored as balance, processing unstructured. Not worth ingesting.
- [x] **Rename PDF files** in `literature_review/` to reflect actual paper titles *(done 2026-04-22)*

### Data Acquisition (Pending)
- [ ] **Copy NIMS fatigue file to correct path:** `data/NIMS_fatigue/nims_fatigue_agrawal.xlsx` — file is `40192_2013_16_MOESM1_ESM.xlsx` from https://immi.springeropen.com/articles/10.1186/2193-9772-3-8 (Additional file 1)
- [ ] **Download steeldata.info demo** (free, 200 CCT + 100 tempering diagrams) — inspect whether data fields are structured HTML or image-based before buying. URL: https://www.steeldata.info/all_in_one/html/demo.html
  - If structured HTML: buy $800 license — 9,843 CCT + 2,877 tempering diagrams would replace CALPHAD for Phase 4 entirely
  - If image-based: email Hedström group (KTH) at pheds@kth.se — they likely digitized steeldata.info already (arXiv:2512.03050)
- [ ] **Download Knovel ASM Vol.4 tables** (CMU institutional license — priority order):
  1. "Typical Hardnesses of Various Carbon and Alloy Steels after Tempering" → fills `hardness_HRC` gap (Critical)
  2. "Hardening and Tempering of Tool Steels" → fills tool steel HRC + processing gap (Critical)
  3. "Typical Mechanical Properties of Standard 18 Nickel Maraging Steels in Age-Hardened Condition" → fills maraging processing gap (Medium)
  4. "Typical Mechanical Properties of Normalized Alloy Steel Sheet" — more normalized data
  5. "Typical Mechanical Properties of 300M / H11 Mod / H13 / D-6A" — fracture toughness + KIC

### Reading (Pending)
- [ ] Read TMCP paper (Sci. Rep. 2021) in full — understand their GA-based inverse design implementation before Phase 3
- [ ] Read SteelBERT (Acta Mat. 2025) in full — understand their fabrication sequence method
- [ ] Cite arXiv:2003.01943 as the forward model baseline to beat in Phase 2 evaluation
