# Data Sources

Every data source in this project: what it contains, its quality, and its ingestion status.

---

## Ingested Sources (in steels.db)

| Source ID | Parser | Steels | Prop rows | Reliability | Notes |
|-----------|--------|--------|-----------|-------------|-------|
| `src_steelbench_nims` | `steelbench.py` | 720 | 720 | 5 | NIMS lab measurements — UTS-only |
| `src_steelbench_emk` | `steelbench.py` | 1,506 | 1,506 | 4 | EMK spec values — hardness is spec limits, not measurements |
| `src_steelbench_kaggle` | `steelbench.py` | 494 | 494 | 2 | Unclear provenance — HB confirmed |
| `src_asm_vol1` | `asm_vol1.py` + `asm_vol4.py` | 431 | 193 | 4 | ASM Vol.1 Knovel exports — 5 original tables + martensitic stainless + L/S tool steels |
| `src_asm_vol4` | `asm_vol4.py` | 218 | 396 | 4 | ASM Vol.4 QT curves, wide HRC tempering table, maraging, tool steel HT, fracture toughness |
| `src_mondal_appendix` | `mondal.py` | 272 | 78 | 4 | S.K. Mondal textbook appendix tables |
| `src_cheng_2024` | `cheng2024.py` | 580 | 580 | 3 | Fe–C–Mn–Al advanced steels; processing-rich; no yield |
| `src_figshare_steel` | `figshare_steel.py` | 312 | 312 | 3 | Figshare high-alloy dataset; no processing |
| `src_zenodo_steel_grades` | `zenodo_steel_grades.py` | 432 | 432 | 3 | Jalalian 2025 Zenodo; carbon + stainless; full properties |
| `src_nims_fatigue` | `nims_fatigue.py` | 155 | 437 | 5 | NIMS fatigue DB — rotating bending fatigue at 10⁷ cycles; carbon + low-alloy |
| `src_ammrc_kic_1973` | `ammrc_kic.py` | 181 | 375 | 4 | AMMRC MS 73-6 fracture toughness handbook; VLM-extracted; 374 KIC rows |

**Total as of 2026-04-25: 5,523 property rows, 5,301 unique steels**

---

## Detailed Source Notes

### SteelBench v1.0
- **Location:** Downloaded at runtime from Zenodo (DOI: 10.5281/zenodo.18530558)
- **License:** CC-BY 4.0

Three data tiers — weight training data accordingly:

| Tier | Source ID | Rows | Reliability | Critical Notes |
|------|-----------|------|-------------|----------------|
| NIMS measured | `src_steelbench_nims` | 360 | 5 | UTS-only — yield, hardness, Charpy, all processing params are null. Use only for UTS-from-composition models. |
| EMK spec-verified | `src_steelbench_emk` | 753 | 4 | Spec values (minima/typical). **Hardness column is spec limits, not measurements — exclude from hardness training.** |
| Kaggle measured | `src_steelbench_kaggle` | 247 | 2 | Unclear provenance. HB confirmed as Brinell. Exclude from held-out test set. |

Processing coverage: austenitize_T ~51%, quench_medium ~47%, temper_T ~29%.

---

### Mondal Appendix Tables
- **Location:** `data/Steel_metallurgy_Mondal_appendices/`
- **Source:** S.K. Mandal, *Steel Metallurgy: Properties, Specifications and Applications*, 1st Edition
- **Reliability:** 4

Four files: plain carbon (41 SAE 10xx/15xx), alloy steel (42 SAE 13xx/4xxx/5xxx/6xxx/8xxx/9xxx), free-cutting (14 SAE 11xx/12xx), and properties (39 records with coarse processing).

Notes: Schema S limit raised to 0.4 wt% for free-cutting steels. `austenitize_temp_C` is null in all property records — route type only.

---

### ASM Handbook Vol.1 (Knovel Table Exports)
- **Location:** `data/ASM/`
- **Source:** ASM Handbook Vol.1, 1990. CMU institutional license.
- **Reliability:** 4

| Table | File(s) | Records | Contents |
|-------|---------|---------|----------|
| Table 9 | `vol1_estimated_mechanical_properties_*.csv` | 101 | Carbon steel bar properties by route (as-rolled/anneal/normalize) |
| Table 7 | `vol1_astm_specifications_*.csv` | 46 | ASTM structural plate min-spec properties (no processing) |
| Table 12 | `vol1_carbon_steel_compositions_bars_rods.csv` | 48 | Carbon steel compositions — bars/rods |
| Table 13 | `vol1_carbon_steel_compositions_structural_shapes_*.csv` | 43 | Carbon steel compositions — plate/sheet |
| Table 27 | `vol1_ams_alloy_steel_nominal_compositions_*.csv` | 147 | AMS alloy steel nominal compositions |
| Table 11 | `vol1_minimum_mechanical_properties_martensitic_stainless_*.csv` | ~42 | Martensitic stainless min-spec properties — parsed via `asm_vol4.py` |
| Table 7 (tool) | `vol1_nominal_mechanical_properties_group_l_s_tool_steels.csv` | ~29 | L/S tool steel nominal properties — parsed via `asm_vol4.py` |

---

### ASM Handbook Vol.4 (Heat Treating, Knovel Table Exports)
- **Location:** `data/ASM/` (prefix `vol4_`)
- **Source:** ASM Handbook Vol.4, 1991. CMU institutional license.
- **Reliability:** 4

| Sub-parser | Files | Records | Contents |
|-----------|-------|---------|----------|
| `_parse_hr_norm_anneal` | `vol4_properties_selected_*.csv` (×2) | ~30 steel bundles / 80 raw rows | Carbon + alloy steels: as-rolled / normalized / annealed UTS, YS, elongation, RA, HB, Izod |
| `_parse_qt_table` | `vol4_typical_mechanical_properties_*.csv` (×9 grades) | 9 grade bundles | 4340, 4130, 4140, 8640, 6150, D6A, 300M, H11 Mod, H13 — full QT property curves |
| `_parse_maraging_*` | `vol4_*maraging*.csv` (×3 files) | ~15 bundles | Age-hardened (KIC!), solution-annealed, aging HRC |
| `_parse_hardness_tempering` | `vol4_typical_hardnesses_*.csv` | ~26 steel bundles / 238 raw rows | Wide HRC vs. temper-temp table (9 temper temps × ~26 grades) |
| `_parse_tool_steel_ht` | `vol4_hardening_and_tempering_*.csv` (×2) | ~37 bundles | Tool steel austenitize + temper params (processing-only) |
| `_parse_austenitizing_temps` | `vol4_typical_austenitizing_*.csv` | ~19 bundles | Austenitize temps for 19 grades (processing-only) |
| `_parse_4340_kic` | `vol4_notch_toughness_*.csv` | 3 bundles | 4340 KIC at 3 hardness levels |
| `_parse_d6ac_kic` | `vol4_*d6a*.csv` (×2) | ~8 bundles | D6AC fracture toughness (EAF/VAR methods + long transverse) |

**This is the primary source of HRC data (295 rows, 9.9% coverage) and QT parameter triples (austenitize + quench + temper). Also provides 15 KIC records.**

Notes: Izod impact values stored in `charpy_J` with a note. Maraging `route_type="other"` (no `age_harden` enum). Tool steels that appear in both part files produce 12 expected skips on re-ingest.

---

### NIMS MatNavi MSDB
- **Location:** Manual lookups only (bulk download not permitted)
- **Access:** https://mits.nims.go.jp
- **Reliability:** 5 (primary lab measurements)
- **Note:** Only NIMS rows already in SteelBench (360 rows) are in the DB. Additional manual extraction allowed for specific grades.

---

### Cheng et al. 2024 — Fe–C–Mn–Al Advanced Steel Dataset
- **Location:** `data/H.Cheng_et_al/d3cp05453e1.xlsx`
- **Source:** H. Cheng et al., PCCP 2024. DOI: 10.1039/d3cp05453e
- **Reliability:** 3

580 records, most processing-rich dataset in the project. Multi-step route: hot rolling → cold rolling → annealing → tempering.

**Warnings:** `steel_family='other'` throughout (Mn up to 30 wt%). No yield strength — UTS and elongation only. Intercritical anneal temps <600°C stored in notes only. File 2 excluded (numeric categorical encoding without decode key).

---

### Figshare Steel Strength Dataset
- **Location:** `data/Figshare/steel_strength.csv`
- **Source:** https://figshare.com/articles/dataset/Steel_Strength_Data/7250453
- **Reliability:** 3

311 records. Composition (13 elements) + yield + UTS + elongation (9 null). Skews heavily toward high-alloy compositions (yield 1000–2500 MPa). No processing data. Families: maraging (Co>5, Ni>8), stainless (Cr>10.5), tool (W>1 or V>1 and C>0.5), low-alloy.

---

### Jalalian 2025 Zenodo — Carbon and Stainless Steel Grades
- **Location:** `data/Zenodo/Carbon_stainless_steel_grades.xlsx`
- **Source:** Jalalian, S. (2025). Zenodo. DOI: 10.5281/zenodo.17704410. CC-BY 4.0
- **Reliability:** 3 (aggregated from MatWeb, MakeItFrom, steel-grades.com)

538 rows: carbon (237) + stainless (301). 100% fill rate on HB, UTS, YS, elongation. Standards: AISI, EN, GB, UNS, ASTM. Processing one-hot flags (Quenching, Normalising, Annealing, Hot_Roll) mapped to route_type.

**Data fixes applied in parser:** P clamped at 0.1 (3 rows had midpoint 0.105), HB=710 dropped (ASTM A228 spring wire outlier), UTS/YS transposed in 23 GB/T rows (physically impossible yield > UTS by 2–4×).

---

### AMMRC MS 73-6 — Plane Strain Fracture Toughness (KIC) Data Handbook
- **Location:** `literature_review/Plane Strain Fracture Toughness (K.) Data Handbook for Metals.pdf`
- **Source:** Army Materials and Mechanics Research Center, AMMRC MS 73-6, 1973. Public domain.
- **Reliability:** 4
- **Parser:** `data/parsers/ammrc_kic.py`

The primary KIC source in the project. 33 tables (pages 16–54) covering structural and aerospace steels: 4330M, 4340, 300M, D6AC, H-11, maraging 200/250, 9Ni-4Co, 17-7 PH, PH 15-7 Mo, ASTM A533, and more.

**Extraction method:** pdf2image (300 DPI PNG) → Claude Opus vision model → structured JSON cached to `data/AMMRC_KIC/raw/page_NNN.json` → `SteelIngestBundle` validation → ingest. Re-running from cache costs no API calls. Requires `ANTHROPIC_API_KEY` in `.env` only on the first run.

**Data structure:** Each table has a composition legend (codes A/B/C/D/…) and a heat treatment legend (codes 1/2/3/…). Data rows cross-reference both codes. The parser groups by (comp_code, ht_code) pairs and emits one bundle per pair.

**Multi-sheet tables:** Tables spanning two PDF pages (common for 4340) are merged by `table_number`: `data_rows` concatenated, legend dicts unioned (second sheet wins for legend content).

**Property content:** KIC (MPa√m), test temperature (K → °C), yield strength (MPa), specimen type (WOL, CT, Bend, NR). 374 KIC rows across 181 steels.

**HT parsing notes:** Handbook uses "1550F (1117K) Oil Quench; Temper…" format — no "Austenitize" keyword. Parser detects austenitize temp from the first 4-digit K value ≥900 K preceding a quench keyword. Route detection: `has_quench AND has_temper → QT`.

**Data quality:** One validation failure per run (P=0.15 in one stainless composition; likely OCR misread of 0.015). Over-limit composition values are set to null with a warning log rather than failing the bundle.

---

### NIMS MatNavi Fatigue Database — Agrawal 2014 Extract
- **Location:** `data/NIMS_fatigue/nims_fatigue_agrawal.xlsx`
  - Copy `40192_2013_16_MOESM1_ESM.xlsx` (Additional file 1 from https://immi.springeropen.com/articles/10.1186/2193-9772-3-8) to that path.
- **Source:** NIMS MatNavi Fatigue DB (http://smds.nims.go.jp/fatigue/index_en.html), preprocessed by Agrawal et al. IMMI 2014 (CC-BY 2.0)
- **Reliability:** 5 (NIMS primary lab measurements)

437 records: 378 Q&T, 48 case-hardened (carburize), 11 normalized. Carbon and low-alloy steels (SAE 10xx, 4xxx, 8xxx families).

**This is the sole source of `fatigue_limit_MPa` in the project.** Values are rotating bending fatigue strength at 10⁷ cycles (R=−1 fully reversed). Processing coverage: austenitize temp + quench medium + temper temp + temper time for all 437 rows.

**File status:** `data/NIMS_fatigue/nims_fatigue_agrawal.xlsx` is present (placed 2026-04-21). **Ingested 2026-04-25** — 155 steels, 437 fatigue property rows in steels.db.

**Column encoding notes:** The Agrawal preprocessing uses 30°C as a sentinel for "parameter not used" (temperatures) and 0 for times. `THQCr` (cooling rate °C/s): 0 = no quench, 8 = oil (~8°C/s), 24 = water (~24°C/s). `QmT` (quench media temp): 30 = room-temp water/oil, 60 = warm oil (post-carburize), 140 = hot salt bath.

---

## Known Coverage Gaps (as of 2026-04-25)

| Gap | Severity | Notes |
|-----|----------|-------|
| `hardness_HRC` — ~295 rows (~5.3%) | Medium | **Improved from 0%** via ASM Vol.4 wide tempering table + QT curves. Main remaining gap: HSLA and maraging families show 0% HRC. |
| `hardness_HV` — 0 rows | High | Not in any current source. |
| `fracture_tough_KIC` — 389 rows (7.0%) | Low–Medium | **Greatly improved**: AMMRC MS 73-6 added 374 rows (181 steels). Remaining gap: no KIC for carbon, HSLA, or Cheng 2024 families. |
| `fatigue_limit_MPa` — 437 rows (7.9%) | Medium | Carbon/low-alloy only (NIMS fatigue DB). No stainless, maraging, or tool steel fatigue data. |
| `coiling_temp_C` — 0 rows | Medium | TMCP parameter; no coiling temp in any current source. |
| `temper_time_min` — partial | Medium | NIMS fatigue covers ~437 rows; still sparse for ASM/SteelBench records. |
| HSLA family — 0% hardness | Medium | A36/A572/A514/A588 present. No HB/HRC for structural grades. |
| `HSLA` — 0% Charpy | Low | Structural plate often spec'd by Charpy; no data here. |
| `other` family yield — 0% | Low | Cheng 2024 only has UTS; not fixable without new source. |

---

## Parsers Written, Not Yet Ingested

Parser scripts exist in `data/parsers/` but have not been run against steels.db.

| Parser | Proposed source ID | Records | Notes |
|--------|--------------------|---------|-------|
| `azom_scraper.py` | `src_azom_scraper` | ~8 | AZoM.com targeted scrape — tool steels + A36 + common alloy grades. To add more grades: find the AZoM ArticleID and append to `GRADE_ARTICLES`. Fetches at runtime; no local file needed. |
| `astm_hsla_specs.py` | `src_astm_hsla_specs` | 11 | Hand-curated ASTM min specs: A36, A572 Gr 42/50/55/60/65, A514 Gr B, A588 Gr A, A709 Gr 36/50/HPS 70W. Values are minimum limits, not typicals — weight training accordingly. |

---

## Downloaded, Parser Not Yet Written

Files on disk but not yet in steels.db (or ingested only as processing-only stubs with no properties).

| File group | Contents | Priority |
|------------|----------|----------|
| `vol4_recommended_annealing_temperatures_*.csv` | Anneal temp ranges for alloy steels (processing-only) | Low |
| `vol4_typical_heat_treatment_temperatures_*.csv` | HT temps for medium-C low-alloy steels (processing-only) | Low |
| `vol4_hardness_various_steels_section_sizes_austempered_parts.csv` | Austempered hardness (needs austemper route) | Low |

---

### ASM Vol.4 — Tool Steel Hardening and Tempering
- **Location:** `data/ASM/TableData_Hardening and Tempering of Tool Steels.csv` (50 rows) + `TableData_Hardening and Tempering of Tool Steels2.csv` (16 rows)
- **Source:** ASM Handbook Vol.4, 1991. Knovel table exports. CMU institutional license.
- **Reliability:** 4
- **Proposed source ID:** `src_asm_vol4_tool_steel`
- **Delimiter:** Semicolon (`;`), declared as `sep=;` in row 1. Skip 4 metadata rows, then headers on row 5.
- **Content:** 66 rows covering hardening temperatures, quench media, and tempering temperature ranges for the full AISI tool steel classification:
  - High-speed steels (M-series): M1, M2, M3, M4, M6, M7, M10, M30, M33, M34, M36, M41–M47
  - High-speed steels (T-series): T1, T2, T4, T5, T6, T8, T15
  - Hot-work steels (H-series): H10–H14, H19, H21–H26, H41–H43
  - Cold-work steels (A-series): A2–A10
  - Cold-work steels (O-series): O1, O2, O6, O7
  - Shock-resistant (S-series): S1, S2, S5, S7
  - Mold steels (P-series): P2, P3, P4, P6, P20, P21
  - Low-alloy special-purpose (L-series): L2, L3, L6
  - Carbon-tungsten (F-series): F1, F2
  - Water-hardening (W-series): W1, W2, W3
  - High-Cr cold-work (D-series): D1, D3, D4, D5, D7
- **Schema mapping:**
  - `hardening temperature (°C)` → `austenitize_temp_C` (store midpoint of range; full range string in notes)
  - `quenching medium(a)` → `quench_medium` (parse codes: O=oil, A=air, S=salt, W=water, B=brine; when multiple options listed, store the primary)
  - `tempering temperature (°C)` → `temper_temp_C` (store midpoint)
  - `preheat temperature (°C)` → notes field (not a schema column; it's a pre-austenitize step)
  - `route_type` → `QT` for all rows
  - No mechanical properties in this table — `properties` array will be empty. The records provide processing parameters only.
- **Parser notes:**
  - Strip footnote markers `(a)`, `(b)`, `(c)`, `(d)`, `(k)` from numeric fields before parsing.
  - File 2 rows 51–52 (L2) represent two processing options (water vs. oil quench) for the same grade — emit two separate processing records for L2.
  - Both files share the same column schema and can be processed in one pass.

---

### ASM Vol.4 — Tempering Hardness Curves (Carbon and Alloy Steels)
- **Location:** `data/ASM/TableData_Typical Hardnesses of Various Carbon and Alloy Steels after Tempering.csv`
- **Source:** ASM Handbook Vol.4, 1991. Knovel table export. CMU institutional license.
- **Reliability:** 4
- **Proposed source ID:** `src_asm_vol4_tempering`
- **Delimiter:** Semicolon (`;`), 4 metadata rows before header.
- **Content:** 27 steel grades × up to 10 tempering temperatures = up to 270 (grade, temper_temp, HRC) records. This is the primary source needed to close the `hardness_HRC` coverage gap.
  - Carbon steels (water-hardened): 1030, 1040, 1050, 1060, 1080, 1095, 1137, 1141, 1144
  - Alloy steels (water or oil-hardened): 1330, 2330, 3130, 4130, 5130, 8630, 1340, 3140, 4140, 4340, 4640, 8740, 4150, 5150, 6150, 8650, 8750, 9850
  - Tempering temperatures covered: 205, 260, 315, 370, 425, 480, 540, 595, 650 °C (9 temperatures; some grades missing the last one)
- **Schema mapping:**
  - One processing record per grade: `austenitize_temp_C` (midpoint from heat treatment column), `quench_medium` (from heat treatment column), `route_type=QT`
  - One property record per (grade, temper_temp) pair: `temper_temp_C`, `hardness_HRC`
  - `processing_id` links all property rows for the same grade to the same processing record
- **Parser notes:**
  - The `heat treatment` column contains free-text descriptions, e.g. `"Normalized at 900 °C, water quenched from 830–845 °C"` — extract austenitize range midpoint and quench medium with regex.
  - Several low-carbon grades have `95(a)` or similar at the lowest temper temps — `(a)` footnote means the value is HRB, not HRC. Store these as `NULL` in `hardness_HRC`; do not convert or mix scales.
  - Strip HTML entity `&degF` from column header strings when parsing.
  - Expected output: ~240 `hardness_HRC` rows (after excluding HRB values).

---

### ASM Vol.4 — Martensite Hardness Reference (C% vs HRC) — NOT for steels.db
- **Location:** `data/ASM/TableData_Hardness_for Various Carbon Contents and Percentages of Martensite for Some Low-Alloy Steels.csv`
- **Source:** ASM Handbook Vol.4, 1991. CMU institutional license.
- **Content:** 7 rows. Maps carbon content (0.18–0.48 wt%) to HRC at martensite fractions of 50%, 80%, 90%, 95%, 99.9%.
- **Not for steels.db.** This is a physics reference table, not records for individual steels. Its purpose is as a lookup for the two-stage forward model: given a martensite fraction from CALPHAD and a carbon content from the composition, this table gives an empirical HRC estimate — a direct physics-grounded prediction independent of training data.
- **Recommended use:** Hard-code as a static numpy array or small CSV in `data/reference/` and import into the CALPHAD feature engineering module. Label outputs from this lookup as `[empirical: martensite-HRC table]`.

---

## Reference / Lookup (not ingested)

### AISI Steel Code Tables
- **Location:** `data/AISI_steel_code_tables/`
- Only `STLCDPID_10-30-19.xlsx` is relevant — grade type codes and heat treatment type codes. Useful as validation reference.

---

## Planned (not yet acquired)

### PyCalphad + TDB Files
- Compute Ac1/Ac3 transformation temperatures from composition.
- Source: TPIS or community TDB repositories; `uv add pycalphad`
- Needed for Phase 3 (phase feasibility) and Phase 4 (processing parameter filling).

### CCT Model (KTH, arXiv:2512.03050)
- Phase feasibility check — determines whether a composition will form intended microstructure under a proposed cooling schedule.
- Status: Not integrated. Verify whether weights are publicly released.

### LME Spot Prices
- Live or periodic spot prices for Fe, Mn, Cr, Ni, Mo, V, Nb, Ti, etc.
- Needed for Phase 5 (alloy surcharge cost estimation).

---

## Data Quality Rules

- **Missing composition values are `NULL`, not `0`.** Imputing zero changes the metallurgy.
- **Do not mix hardness scales** (HV, HRC, HB) in a single training feature without conversion.
- **`processing_id` being null in `Properties`** is normal — many sources report composition + properties with no processing history.
- **NIMS rows in SteelBench** are UTS-only by design. Partition them separately; do not use for yield, hardness, or processing models.
- **EMK hardness in SteelBench** must be excluded from hardness training — confirmed as specification limits, not measurements.
- **ASTM min-spec rows** (src_astm_hsla_specs) are specification lower bounds, not measured typicals. Consider separate loss weighting vs. measured data.
- **Reliability weighting** must be applied at training time. Higher-reliability sources should dominate the loss.
