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

### NIMS MatNavi MSDB
- **Location:** `data/AISI_steel_code_tables/` *(to be downloaded separately)*
- **Parser:** `data/parsers/nims.py` — `NIMSParser` / `parse_nims_file()`
- **Coverage:** JIS-grade structural steels; tensile, yield, hardness, Charpy linked to composition and some heat treatment data
- **Access:** Free registration at https://mits.nims.go.jp
- **Status:** Parser complete. File not yet downloaded.

**Before parsing:** Run `NIMSParser.inspect(path)` on the downloaded file to verify column names — NIMS has changed export headers across versions. The column maps in `nims.py` may need updating.

**Unit warning:** Older NIMS exports use kgf/mm² for strength. Set `force_kgf_conversion=True` if your file predates ~2018.

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

### AISI/SAE Grade Composition Tables
- **What's needed:** Nominal wt% composition ranges for standard grades (e.g., AISI 4340: C 0.38–0.43, Mn 0.60–0.80, Cr 0.70–0.90, Ni 1.65–2.00, Mo 0.20–0.30)
- **Why:** High-reliability ground truth for standard grades. More reliable than any model for compositions that are well-standardized.
- **Source options:** Hand-curate from AISI/SAE published standards, or find a structured open dataset
- **Use in pipeline:** Phase 4 lookup tables for standard-grade processing routes; validation reference for the forward model
- **Status:** Not acquired. The AISI code tables in this repo are the ordering protocol, not this.

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
