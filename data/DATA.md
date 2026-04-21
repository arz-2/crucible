# Data Sources

This document describes every data source in this project: what it contains, what it's useful for, its quality, and its current ingestion status.

---

## Ingested / Ready to Ingest

### SteelBench v1.0
- **Location:** Downloaded at runtime from Zenodo (DOI: 10.5281/zenodo.18530558)
- **Parser:** `data/parsers/steelbench.py` — `parse_steelbench()`
- **Coverage:** 1,360 records; composition + mechanical properties for carbon, low-alloy, and stainless steels
- **License:** CC-BY 4.0
- **Status:** Parser complete. Not yet ingested.

Three data tiers — weight training data accordingly:

| Tier | Rows | Reliability | Notes |
|------|------|-------------|-------|
| `nims_measured` | 360 | 5 | NIMS lab measurements. UTS-only — yield, elongation, hardness, Charpy, and all processing params are null by design. Use only for UTS-from-composition models. |
| `emk_spec_verified` | 753 | 4 | EMK specification values (minima/typical), not exact heat measurements. Hardness column is spec limits, not measurements — exclude from hardness training. |
| `kaggle_measured` | 247 | 2 | Unclear provenance. Hardness confirmed as HB (Brinell). Exclude from held-out test set. |

Processing coverage: austenitize_T ~51%, quench_medium ~47% (air/water/oil only), temper_T ~29%. No Nb, Ti, B, N, W, P, S columns.

---

### Mondal Appendix Tables (SAE/AISI Composition + Properties)
- **Location:** `data/Steel_metallurgy_Mondal_appendices/`
- **Source:** S.K. Mandal, *Steel Metallurgy: Properties, Specifications and Applications*, 1st Edition
- **Parser:** `data/parsers/mondal.py` — `parse_mondal()`
- **Reliability:** 4 (textbook specification values — nominal ranges, not individual heat measurements)
- **Status:** Parser complete. Not yet ingested.

Four files, two categories:

**Composition tables (97 grades, composition-only records):**

| File | Grades | Elements |
|------|--------|----------|
| `Plain_carbon_steels.xlsx` | 41 SAE 10xx/15xx grades | C, Mn, S, P |
| `Standard_SAE_grade_alloy_steels.xlsx` | 42 SAE 13xx/4xxx/5xxx/6xxx/8xxx/9xxx grades | C, Mn, Cr, Ni, Mo, Si (where applicable) |
| `SAE_grade_free_cutting_resulphurised_steels_chemical_composition.xlsx` | 14 SAE 11xx/12xx grades | C, Mn, P, S |

Compositions are stored as midpoints of the published nominal ranges. Missing elements are `NULL` (not zero). Free-cutting steels have S up to 0.33 wt% by design — the schema S limit was raised to 0.4 wt% to accommodate them.

**Properties table (39 records, properties + coarse processing):**

| File | Records | Properties | Processing |
|------|---------|-----------|------------|
| `Properties_of_steel.xlsx` | 39 | yield MPa, UTS MPa, elongation, RA, hardness HB | Route type + temper temp (°F → °C converted) |

Processing methods mapped to route types: Hot Rolled/Cold Drawn → `as_rolled`, annealed → `anneal`, Case Hardened → `case_harden`, Drawn at temp → `QT` with temper_temp_C. Austenitizing temperature is not given in the source — left null. Composition is not in this table; records link by grade name only.

---

### ASM Handbook Vol.1 (Knovel Table Exports)
- **Location:** `data/ASM/`
- **Source:** ASM Handbook, Volume 1: Properties and Selection: Irons, Steels, and High-Performance Alloys. ASM International, 1990. Accessed via Knovel (CMU institutional license).
- **Parser:** `data/parsers/asm_vol1.py` — `parse_asm_vol1()`
- **Reliability:** 4 (handbook specification values — typical or minimum, not individual heat measurements)
- **Status:** Parser complete. Not yet ingested.

Total: **385 records** across 5 tables.

| Table | File(s) | Records | Contents | Bundle Type |
|-------|---------|---------|----------|-------------|
| Table 9 | `TableData9_1/2/3.csv` | 101 | Carbon steel bar properties by processing type | Steel + Processing + Properties |
| Table 7 | `TableData7.csv` | 46 | ASTM structural plate min properties (carbon, low-alloy, HSLA) | Steel + Properties (no processing) |
| Table 12 | `TableData12.csv` | 48 | Carbon steel compositions — bars/rods/tubing | Steel + Composition |
| Table 13 | `TableData13.csv` | 43 | Carbon steel compositions — plate/sheet/strip | Steel + Composition |
| Table 27 | `TableData27_1/2/3.csv` | 147 | AMS alloy steel nominal compositions | Steel + Composition |

**Table 9 processing types:** Hot Rolled → `as_rolled`, Cold Drawn → `as_rolled`, ACD (annealed cold drawn) → `anneal`, SACD (spheroidize annealed cold drawn) → `anneal`, NCD (normalized cold drawn) → `normalize`. No temperature data — austenitize/temper temps are null.

**Table 7 notes:** Properties are ASTM minimum specification values — treat as lower bounds, not typical. `processing_id` is always null (no heat treatment info given; as-rolled implied for structural plate).

**Tables 12/13 overlap:** Both cover carbon steel grades; Table 12 (bars/rods) and Table 13 (plate/sheet) represent product-form-specific composition limits for the same SAE grades. IDs are deterministic by (SAE grade + product form) so both ingest without collision.

**Table 27 notes:** AMS designations map to nearest AISI-SAE grade via the `nearest grade` column. Many AMS grades are product-form variants of the same base composition. `other` column parsed for Si, V, Mn, Nb via regex.

**Discarded files:** `TableData9.csv` and `TableData10.csv` are cast iron tables — not steel, excluded from ingestion.

---

### NIMS MatNavi MSDB
- **Location:** `data/AISI_steel_code_tables/` *(to be downloaded separately)*
- **Parser:** `data/parsers/nims.py` — `NIMSParser` / `parse_nims_file()`
- **Coverage:** JIS-grade structural steels; tensile, yield, hardness, Charpy linked to composition and some heat treatment data
- **Access:** Free registration at https://mits.nims.go.jp
- **Status:** Parser complete. File not yet downloaded.

**Before parsing:** Run `NIMSParser.inspect(path)` on the downloaded file to verify column names — NIMS has changed export headers across versions. The column maps in `nims.py` may need updating.

**Unit warning:** Older NIMS exports use kgf/mm² for strength. Set `force_kgf_conversion=True` if your file predates ~2018.

---

### Cheng et al. 2024 — Fe–C–Mn–Al Advanced Steel Dataset
- **Location:** `data/H.Cheng_et_al/d3cp05453e1.xlsx`
- **Source:** H. Cheng et al., "Composition design and optimization of Fe–C–Mn–Al steel based on machine learning," *Physical Chemistry Chemical Physics*, 2024. DOI: 10.1039/d3cp05453e
- **Parser:** `data/parsers/cheng2024.py` — `parse_cheng2024()`
- **Coverage:** 580 records; composition (17 elements) + multi-step processing + UTS + elongation
- **Reliability:** 3 (literature-aggregated, not single-source measurements)
- **Status:** Parser complete. Not yet ingested.

This is the most processing-rich dataset in the project. It covers advanced/lightweight steel families (medium-/high-Mn TWIP/TRIP, high-Al lightweight steels) with a detailed multi-step process record per sample: hot rolling → optional cold rolling → annealing → optional tempering.

Key schema notes:
- `steel_family = 'other'` for all records (Mn up to 30 wt%, Al up to 13 wt% — outside standard AISI families)
- Only UTS and elongation are reported — no yield strength
- Intercritical annealing temperatures of 200–580°C (below the schema's 600°C `austenitize_temp_C` floor) are stored in `notes` only; records with AT ≥ 600°C are stored in the field normally
- B values of 0.31 wt% (3 records) exceed the schema cap and are stored in notes — real steel B is normally < 0.01 wt%, suggesting a specialty alloy or source unit error
- `d3cp05453e2.xlsx` contains 580 additional records with numerically encoded categorical columns; the encoding key is not published — excluded from this parser

---

## Reference / Lookup (not ingested into steels.db)

### AISI Steel Code Tables
- **Location:** `data/AISI_steel_code_tables/`
- **What these are:** The AISI Steel Code is a standardized EDI ordering and communication protocol used between steelmakers and buyers. These are **not** composition databases.

| File | Contents | Relevant to project? |
|------|----------|----------------------|
| `STLCDPID_10-30-19.xlsx` | Grade type codes, heat treatment codes, product form codes, spec codes | Yes — useful as lookup/validation reference |
| `COMPORD-Tables-.xls` | EDI transaction and document type codes | No |
| `COMPORD-Tables-Proposed-for-Deletion-Tables.xls` | Codes proposed for removal from the COMPORD system | No |
| `Outside-Processing-Tables.xls` | Administrative outside-processing codes | No |
| `Shipping-and-Packaging-Tables.xls` | Logistics and packaging codes | No |

The `STLCDPID` file is useful for:
- Mapping grade family strings → our `steel_family` enum (Grade table, sheet `10 - Grade`: Carbon=1, Alloy=4, HSLA=2, Stainless=5, Microalloy=7)
- Validating heat treatment type codes (sheet `15 - Heat Treat`)

---

## Planned (not yet acquired)

### PyCalphad + TDB Files

### PyCalphad + TDB Files
- **What's needed:** `pycalphad` package + thermodynamic database files (.tdb) covering the Fe-C-Mn-Cr-Ni-Mo system
- **Why:** Compute Ac1/Ac3 transformation temperatures from composition. Directly sets austenitizing window for Phase 4 processing routes.
- **Source:** TPIS or community TDB repositories; `uv add pycalphad`
- **Status:** Not installed. Needed for Phase 3 (phase feasibility filter) and Phase 4 (processing parameter filling).

### CCT Model (KTH, arXiv:2512.03050)
- **What's needed:** Model weights and inference code from the KTH continuous cooling transformation ML model
- **Why:** Phase feasibility check — determines whether a given composition will form the intended microstructure under a proposed cooling schedule
- **Status:** Not integrated. Verify whether weights are publicly released.

### LME Spot Prices
- **What's needed:** Live or periodically updated spot prices for Fe, Mn, Cr, Ni, Mo, V, Nb, Ti, etc.
- **Why:** Phase 5 alloy surcharge cost estimation ($/ton)
- **Source:** LME API or scraped prices
- **Status:** Not acquired. Needed for Phase 5 only.

---

## Data Quality Rules

- **Missing composition values are `NULL`, not `0`.** Imputing zero changes the metallurgy.
- **Do not mix hardness scales** (HV, HRC, HB) in a single training feature without conversion.
- **`processing_id` being null in `Properties`** is normal — many sources report composition + properties with no processing history.
- **NIMS rows in SteelBench** are UTS-only by design. Partition them separately; do not use for yield, hardness, or processing models.
- **EMK hardness in SteelBench** must be excluded from training — confirmed as specification limits, not measurements.
- **Reliability weighting** must be applied at training time. Higher-reliability sources should dominate the loss.
