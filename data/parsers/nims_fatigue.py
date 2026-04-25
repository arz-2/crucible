"""
Parser for NIMS MatNavi Fatigue Database — Agrawal et al. preprocessed extract.

SOURCE
------
National Institute for Materials Science (NIMS) MatNavi Fatigue Database.
Original DB: http://smds.nims.go.jp/fatigue/index_en.html
Preprocessed extract published as Additional file 1 in:
  Agrawal et al., "Exploration of data science techniques to predict fatigue
  strength of steel from composition and processing parameters."
  Integrating Materials and Manufacturing Innovation 3:8 (2014).
  DOI: 10.1186/2193-9772-3-8 (Open Access, CC-BY 2.0)

FILE
----
data/NIMS_fatigue/nims_fatigue_agrawal.xlsx
  Sheet: "nims.csv" — 437 rows, 27 columns

  To place the file: copy 40192_2013_16_MOESM1_ESM.xlsx (downloaded from the
  SpringerOpen article page, "Additional file 1") to the path above.

DATASET OVERVIEW
----------------
437 records: 378 Q&T, 48 carburizing, 11 normalized.
Carbon and low-alloy steels (SAE 10xx, 13xx, 4xxx, 8xxx families).
This is the ONLY source of fatigue_limit_MPa data in the project.

COLUMN MAPPING
--------------
Composition (wt%): C, Si, Mn, P, S, Ni, Cr, Cu, Mo
  — V, Nb, Ti, Al, W are absent from this dataset (not measured)

Processing parameters (Agrawal encoding):
  NT   — Normalizing Temperature (°C). All rows have NT; it doubles as the
          austenitize/reheat temp for normalized steels.
  THT  — Through Hardening Temperature = austenitize temp for Q&T (°C).
          Value of 30 = "not used" placeholder.
  THt  — Through Hardening Time (min). 30 = placeholder.
  THQCr — Cooling Rate for Through Hardening (°C/s):
            0  → no forced quench (normalize / carburize route)
            8  → oil quench (~8 °C/s, QmT=30 confirms room-temp oil)
            24 → water quench (~24 °C/s)
  CT   — Carburization Temperature (°C). 30 = "not carburized".
  Ct   — Carburization Time (min).
  DT   — Diffusion Temperature (°C). 30 = placeholder.
  Dt   — Diffusion Time (min).
  QmT  — Quench Media Temperature (°C):
            30  → room-temperature water or oil (paired with THQCr for distinction)
            60  → warm oil (post-carburize quench)
            140 → hot salt / martempering bath (post-carburize)
  TT   — Tempering Temperature (°C). 30 = "no tempering" placeholder.
  Tt   — Tempering Time (min). 0 = no tempering.
  TCr  — Cooling Rate for Tempering (°C/s).

Other columns (not stored in our schema):
  RedRatio — Reduction ratio ingot→bar (stored in notes)
  dA, dB, dC — Area proportions of inclusion types (stored in notes)

TARGET
------
  Fatigue — Rotating bending fatigue strength at 10^7 cycles (MPa)
             → stored in fatigue_limit_MPa

ROUTE CLASSIFICATION LOGIC
---------------------------
  CT > 100  → 'carburize'   (case-hardening route)
  THT > 100 → 'QT'          (quench and temper)
  else      → 'normalize'   (NT only, air cool)

QUENCH MEDIUM INFERENCE
-----------------------
  Q&T  + THQCr=24 → 'water'
  Q&T  + THQCr=8  → 'oil'
  Carburize + QmT=60  → 'oil'
  Carburize + QmT=140 → 'other'  (warm salt/martempering bath)
  Normalize           → None (air cool, no quench_medium recorded)

STEEL FAMILY
------------
  Carburizing steels (CT>100): always 'low-alloy' (even plain-C grades are
    included in this family for model consistency, as processing route matters
    more than composition for ML partitioning)
  Q&T/normalize: Cr+Ni+Mo > 0.4 wt% → 'low-alloy', else → 'carbon'

DATA QUALITY NOTES
------------------
- Reliability: 5 (NIMS primary lab measurements, rotating bending fatigue rigs)
- All fatigue values are at 10^7 cycles (R=-1 fully reversed bending), which is
  the standard definition of the endurance limit for ferrous materials.
- The Agrawal preprocessing replaces "not applicable" process parameters with
  30 (for temperatures) or 0 (for times). These are NOT real measurements —
  do not use NT/THT/TT values of exactly 30 as training features.
- 24 replicate measurements exist across 12 conditions (max 3 per condition).
  Replicates are kept as separate property rows — they provide real scatter
  information useful for uncertainty quantification.
- Composition only covers 9 elements. NULL for V, Nb, Ti, Al, W means "not
  reported", which is consistent with plain carbon / low-alloy steels of this era.
- The Sl. No. column is the original NIMS sequential index — stored in notes
  for traceability back to the primary NIMS DB.

SOURCE_ID: src_nims_fatigue
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

SOURCE_ID   = "src_nims_fatigue"
RELIABILITY = 5
SOURCE_YEAR = 2014  # year of the Agrawal preprocessed extract

_PLACEHOLDER_TEMP = 30.0   # Agrawal's sentinel for "parameter not used"
_DEFAULT_FILE = Path(__file__).parent.parent / "NIMS_fatigue" / "nims_fatigue_agrawal.xlsx"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _det_id(prefix: str, *parts: Any) -> str:
    key = "_".join(str(p) for p in parts)
    h = hashlib.md5(key.encode()).hexdigest()[:10]
    return f"{prefix}_{h}"


def _classify_route(row: pd.Series) -> str:
    if row["CT"] > _PLACEHOLDER_TEMP:
        return "case_harden"   # carburizing → schema enum 'case_harden'
    if row["THT"] > _PLACEHOLDER_TEMP:
        return "QT"
    return "normalize"


def _quench_medium(row: pd.Series, route: str) -> Optional[str]:
    if route == "normalize":
        return None
    if route == "case_harden":
        if row["QmT"] >= 100:
            return "other"   # warm salt / martempering bath (~140 °C)
        return "oil"         # post-carburize oil quench at 60 °C
    # Q&T
    if row["THQCr"] >= 20:
        return "water"
    if row["THQCr"] >= 5:
        return "oil"
    return None              # THQCr=0 but route=QT shouldn't occur


def _austenitize_temp(row: pd.Series, route: str) -> Optional[float]:
    if route == "case_harden":
        t = row["CT"]
    elif route == "QT":
        t = row["THT"]
    else:
        t = row["NT"]
    return float(t) if t > _PLACEHOLDER_TEMP else None


def _temper_temp(row: pd.Series) -> Optional[float]:
    tt = row["TT"]
    return float(tt) if tt > _PLACEHOLDER_TEMP else None


def _temper_time(row: pd.Series) -> Optional[float]:
    tt = row["Tt"]
    return float(tt) if tt > 0 else None


def _steel_family(row: pd.Series, route: str) -> str:
    if route == "case_harden":
        return "low-alloy"
    alloy_sum = row["Cr"] + row["Ni"] + row["Mo"]
    return "low-alloy" if alloy_sum > 0.4 else "carbon"


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_nims_fatigue(path: Optional[Path] = None) -> List[Dict]:
    """
    Return SteelIngestBundle-compatible dicts for the NIMS fatigue dataset.

    Usage:
        from data.parsers.nims_fatigue import parse_nims_fatigue, SOURCE_ID
        from data.ingest import ensure_source, ingest_bundles

        ensure_source(
            source_id=SOURCE_ID,
            source_type="NIMS",
            reliability=RELIABILITY,
            pub_year=SOURCE_YEAR,
            notes=(
                "NIMS MatNavi Fatigue Database — 437 rows of carbon and low-alloy "
                "steels with composition, heat treatment parameters, and rotating "
                "bending fatigue strength at 10^7 cycles. Preprocessed extract from "
                "Agrawal et al. IMMI 2014 Additional file 1 (CC-BY 2.0). "
                "Primary source: http://smds.nims.go.jp/fatigue/index_en.html"
            ),
        )
        records = parse_nims_fatigue()
        print(ingest_bundles(records))
    """
    fpath = Path(path) if path else _DEFAULT_FILE
    if not fpath.exists():
        raise FileNotFoundError(
            f"NIMS fatigue file not found at {fpath}.\n"
            "Download Additional file 1 from:\n"
            "  https://immi.springeropen.com/articles/10.1186/2193-9772-3-8\n"
            "and save it as data/NIMS_fatigue/nims_fatigue_agrawal.xlsx"
        )

    df = pd.read_excel(fpath)

    # Build per-row data structures first, then group by steel_id.
    # This is necessary because ingest_bundle does session.add(steel) with no
    # conflict handling — if two rows share a steel_id (same composition, different
    # processing conditions), the second bundle would raise IntegrityError and drop
    # the new processing+property records entirely.  Grouping emits one bundle per
    # unique composition with all conditions attached.
    from collections import defaultdict
    steel_map: Dict[str, Dict] = {}           # steel_id → steel/comp record
    proc_map:  Dict[str, Dict] = {}           # proc_id  → processing record (dedup)
    rows_by_steel: Dict[str, list] = defaultdict(list)  # steel_id → list of (proc_id, prop_rec)

    for _, row in df.iterrows():
        sl_no  = int(row["Sl. No."])
        route  = _classify_route(row)
        family = _steel_family(row, route)
        qm     = _quench_medium(row, route)
        aust_t = _austenitize_temp(row, route)
        tmpr_t = _temper_temp(row)
        tmpr_m = _temper_time(row)
        fatigue = float(row["Fatigue"])

        comp_key = (
            row["C"], row["Si"], row["Mn"], row["P"], row["S"],
            row["Ni"], row["Cr"], row["Cu"], row["Mo"]
        )
        steel_id = _det_id("v_nf", *comp_key)
        comp_id  = _det_id("v_nf_c", *comp_key)

        proc_key = (
            *comp_key, route,
            aust_t or 0, qm or "",
            tmpr_t or 0, tmpr_m or 0,
            row["CT"], row["Ct"],
            row["DT"], row["Dt"],
            row["THQCr"],
        )
        proc_id = _det_id("v_nf_p", *proc_key)

        # property_id includes sl_no to keep replicates distinct
        prop_id = _det_id("v_nf_prop", *comp_key, route,
                          aust_t or 0, tmpr_t or 0, tmpr_m or 0, sl_no)

        # Register steel (first occurrence wins for notes/family)
        if steel_id not in steel_map:
            comp_rec: Dict[str, Any] = {
                "steel_id":       steel_id,
                "composition_id": comp_id,
                "C":  round(float(row["C"]),  4),
                "Si": round(float(row["Si"]), 4),
                "Mn": round(float(row["Mn"]), 4),
                "P":  round(float(row["P"]),  4),
                "S":  round(float(row["S"]),  4),
                "Ni": round(float(row["Ni"]), 4),
                "Cr": round(float(row["Cr"]), 4),
                "Cu": round(float(row["Cu"]), 4),
            }
            if row["Mo"] > 0:
                comp_rec["Mo"] = round(float(row["Mo"]), 4)

            steel_map[steel_id] = {
                "steel": {
                    "steel_id":     steel_id,
                    "steel_family": family,
                    "source_id":    SOURCE_ID,
                    "notes": (
                        f"NIMS fatigue DB. "
                        f"C={row['C']:.3f} Si={row['Si']:.2f} Mn={row['Mn']:.2f} "
                        f"Cr={row['Cr']:.2f} Ni={row['Ni']:.2f} Mo={row['Mo']:.3f}."
                    ),
                },
                "composition": comp_rec,
            }

        # Register processing record (deduplicated — same condition, multiple replicates)
        if proc_id not in proc_map:
            proc_rec: Dict[str, Any] = {
                "processing_id": proc_id,
                "steel_id":      steel_id,
                "route_type":    route,
                "notes": (
                    f"NIMS fatigue DB row {sl_no}. "
                    f"NT={row['NT']}°C, THT={row['THT']}°C, "
                    f"TT={row['TT']}°C, Tt={row['Tt']}min, "
                    f"CT={row['CT']}°C, Ct={row['Ct']}min, "
                    f"DT={row['DT']}°C, Dt={row['Dt']}min, "
                    f"THQCr={row['THQCr']}°C/s, QmT={row['QmT']}°C, "
                    f"RedRatio={row['RedRatio']}, "
                    f"dA={row['dA']}, dB={row['dB']}, dC={row['dC']}."
                ),
            }
            if aust_t is not None:
                proc_rec["austenitize_temp_C"] = aust_t
            if qm:
                proc_rec["quench_medium"] = qm
            if tmpr_t is not None:
                proc_rec["temper_temp_C"] = tmpr_t
            if tmpr_m is not None:
                proc_rec["temper_time_min"] = tmpr_m
            proc_map[proc_id] = proc_rec

        prop_rec: Dict[str, Any] = {
            "property_id":       prop_id,
            "steel_id":          steel_id,
            "processing_id":     proc_id,
            "test_temp_C":       25.0,
            "fatigue_limit_MPa": fatigue,
        }
        rows_by_steel[steel_id].append((proc_id, prop_rec))

    # Assemble one bundle per unique steel
    records: List[Dict] = []
    for steel_id, steel_data in steel_map.items():
        # Collect all processing records for this steel
        used_proc_ids = {pid for pid, _ in rows_by_steel[steel_id]}
        processing = [proc_map[pid] for pid in used_proc_ids]
        properties = [prop for _, prop in rows_by_steel[steel_id]]

        records.append({
            "steel":          steel_data["steel"],
            "composition":    steel_data["composition"],
            "processing":     processing,
            "properties":     properties,
            "microstructure": [],
        })

    n_rows = sum(len(rows_by_steel[sid]) for sid in steel_map)
    n_qt   = sum(1 for pid, proc in proc_map.items() if proc["route_type"] == "QT")
    n_ch   = sum(1 for pid, proc in proc_map.items() if proc["route_type"] == "case_harden")
    n_nm   = sum(1 for pid, proc in proc_map.items() if proc["route_type"] == "normalize")
    logger.info(
        f"NIMS fatigue: {len(records)} steels, {len(proc_map)} conditions, "
        f"{n_rows} property rows "
        f"(QT={n_qt}, case_harden={n_ch}, normalize={n_nm})"
    )
    return records
