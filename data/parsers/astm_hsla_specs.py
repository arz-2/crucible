"""
Hand-curated parser for ASTM HSLA structural steel minimum specifications.

SOURCE
------
ASTM International published standards (public domain specification values):
  ASTM A36/A36M  — Carbon Structural Steel
  ASTM A572/A572M — High-Strength Low-Alloy Columbium-Vanadium Structural Steel
  ASTM A514/A514M — High-Yield-Strength, Quenched and Tempered Alloy Steel Plate
  ASTM A588/A588M — High-Strength Low-Alloy Structural Steel, up to 345 MPa YS
  ASTM A709/A709M — Structural Steel for Bridges (Grades 36, 50, HPS 70W, HPS 100W)

WHY HAND-CURATED
----------------
AZoM.com does not have individual datasheets for each ASTM HSLA grade
(only an overview article). MakeItFrom.com no longer serves individual
material pages. The ASTM specification values below are public domain,
authoritative, stable, and do not require scraping.

These are MINIMUM specification values, not measured typical values.
  - Yield strength = minimum specified (e.g. A36: 250 MPa)
  - UTS = minimum specified (for spec with single min) or midpoint of range
  - Elongation = minimum specified
  - Composition = maximum limits (or range where both min/max specified)
  - Hardness = not specified by ASTM (left NULL)

Reliability: 4 (primary standard documents, one step removed from individual
heat measurements). More reliable than secondary aggregation.

COVERAGE
--------
Total: 11 grade-condition records

A36:         1 grade (carbon structural — as-rolled)
A572:        5 grades (Gr 42, 50, 55, 60, 65 — HSLA, as-rolled)
A514:        1 grade (Q&T alloy plate — typical composition)
A588 Gr A:   1 grade (weathering HSLA — as-rolled)
A709:        3 grades (Gr 36, 50, HPS 70W bridge grades)

DATA QUALITY NOTES
------------------
- Processing_id is set for Q&T grades (A514) only; as-rolled grades have no
  heat treatment parameters from spec.
- A514 composition shown is typical of Grade B (most common); composition
  varies by grade letter (A through T).
- A572 composition: C, Mn, Si, Nb, V within maximums. No lower bounds
  except for A572-55/60/65 which require Nb+V+Ti ≥ 0.02%.
- A709 Grade HPS 70W and HPS 100W are weathering steels with Cu additions.
- No Charpy, HRC, HB in this dataset — spec only defines UTS and YS minima.

SOURCE_ID: src_astm_hsla_specs
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SOURCE_ID   = "src_astm_hsla_specs"
RELIABILITY = 4
SOURCE_YEAR = 2024  # current revision year (standards are continuously revised)


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def _det_id(prefix: str, *parts: Any) -> str:
    key = "_".join(str(p) for p in parts)
    h = hashlib.md5(key.encode()).hexdigest()[:10]
    return f"{prefix}_{h}"


# ---------------------------------------------------------------------------
# Grade definitions
# Each entry: grade, family, composition (wt% midpoints/maxima), properties,
#             route, austen_temp_C, quench_medium
#
# Composition note: values are MAXIMUM specification limits unless a range is
# provided — stored as single values (not midpoints). Where both min and max
# are specified (e.g. A514 Si 0.15–0.35), midpoint is stored.
# ---------------------------------------------------------------------------

_GRADES = [
    # ------------------------------------------------------------------
    # ASTM A36 — Carbon Structural Steel (ASTM A36/A36M)
    # ------------------------------------------------------------------
    {
        "grade":     "ASTM A36",
        "family":    "HSLA",
        "route":     "as_rolled",
        "austen":    None,
        "quench":    None,
        "comp": {"C": 0.26, "Mn": 1.03, "Si": 0.28, "P": 0.04, "S": 0.05, "Cu": 0.20},
        "uts_lo":    400,   # MPa minimum
        "uts_hi":    550,   # MPa maximum (A36 has a cap)
        "ys":        250,   # MPa minimum
        "elong":     23.0,  # % in 50 mm gauge
    },
    # ------------------------------------------------------------------
    # ASTM A572 — HSLA Columbium-Vanadium Structural Steel
    # All grades: as-rolled, normalized, or TMCP
    # ------------------------------------------------------------------
    {
        "grade":     "ASTM A572 Gr 42",
        "family":    "HSLA",
        "route":     "as_rolled",
        "austen":    None,
        "quench":    None,
        "comp": {"C": 0.21, "Mn": 1.35, "Si": 0.40, "P": 0.04, "S": 0.05,
                 "Nb": 0.05, "V": 0.06},
        "uts_lo":    415,
        "uts_hi":    None,
        "ys":        290,
        "elong":     20.0,
    },
    {
        "grade":     "ASTM A572 Gr 50",
        "family":    "HSLA",
        "route":     "as_rolled",
        "austen":    None,
        "quench":    None,
        "comp": {"C": 0.23, "Mn": 1.35, "Si": 0.40, "P": 0.04, "S": 0.05,
                 "Nb": 0.05, "V": 0.06},
        "uts_lo":    450,
        "uts_hi":    None,
        "ys":        345,
        "elong":     18.0,
    },
    {
        "grade":     "ASTM A572 Gr 55",
        "family":    "HSLA",
        "route":     "as_rolled",
        "austen":    None,
        "quench":    None,
        "comp": {"C": 0.25, "Mn": 1.35, "Si": 0.40, "P": 0.04, "S": 0.05,
                 "Nb": 0.05, "V": 0.06},
        "uts_lo":    485,
        "uts_hi":    None,
        "ys":        380,
        "elong":     17.0,
    },
    {
        "grade":     "ASTM A572 Gr 60",
        "family":    "HSLA",
        "route":     "as_rolled",
        "austen":    None,
        "quench":    None,
        "comp": {"C": 0.26, "Mn": 1.35, "Si": 0.40, "P": 0.04, "S": 0.05,
                 "Nb": 0.05, "V": 0.09},
        "uts_lo":    520,
        "uts_hi":    None,
        "ys":        415,
        "elong":     16.0,
    },
    {
        "grade":     "ASTM A572 Gr 65",
        "family":    "HSLA",
        "route":     "as_rolled",
        "austen":    None,
        "quench":    None,
        "comp": {"C": 0.26, "Mn": 1.35, "Si": 0.40, "P": 0.04, "S": 0.05,
                 "Nb": 0.05, "V": 0.09},
        "uts_lo":    550,
        "uts_hi":    None,
        "ys":        450,
        "elong":     15.0,
    },
    # ------------------------------------------------------------------
    # ASTM A514 — Q&T High-Yield-Strength Alloy Steel Plate
    # Composition shown is Grade B (typical). Q&T condition.
    # ------------------------------------------------------------------
    {
        "grade":     "ASTM A514 Gr B",
        "family":    "HSLA",
        "route":     "QT",
        "austen":    900,   # typical, mid-range
        "quench":    "water",
        "comp": {"C": 0.16, "Mn": 0.80, "Si": 0.25, "Cr": 0.50, "Mo": 0.43,
                 "B": 0.003, "P": 0.035, "S": 0.04},
        "uts_lo":    760,
        "uts_hi":    895,
        "ys":        690,
        "elong":     18.0,
    },
    # ------------------------------------------------------------------
    # ASTM A588 Grade A — Weathering HSLA Steel
    # Typical composition: C-Mn-Si + Cr + V + Cu for weathering
    # ------------------------------------------------------------------
    {
        "grade":     "ASTM A588 Gr A",
        "family":    "HSLA",
        "route":     "as_rolled",
        "austen":    None,
        "quench":    None,
        "comp": {"C": 0.19, "Mn": 1.025, "Si": 0.30, "Cr": 0.525, "V": 0.06,
                 "Cu": 0.325, "P": 0.04, "S": 0.05},
        "uts_lo":    485,
        "uts_hi":    620,
        "ys":        345,
        "elong":     18.0,
    },
    # ------------------------------------------------------------------
    # ASTM A709 — Structural Steel for Bridges
    # ------------------------------------------------------------------
    {
        "grade":     "ASTM A709 Gr 36",
        "family":    "HSLA",
        "route":     "as_rolled",
        "austen":    None,
        "quench":    None,
        "comp": {"C": 0.26, "Mn": 1.03, "Si": 0.28, "P": 0.04, "S": 0.05},
        "uts_lo":    400,
        "uts_hi":    550,
        "ys":        250,
        "elong":     23.0,
    },
    {
        "grade":     "ASTM A709 Gr 50",
        "family":    "HSLA",
        "route":     "as_rolled",
        "austen":    None,
        "quench":    None,
        "comp": {"C": 0.23, "Mn": 1.35, "Si": 0.40, "P": 0.04, "S": 0.05,
                 "Nb": 0.05, "V": 0.06},
        "uts_lo":    450,
        "uts_hi":    None,
        "ys":        345,
        "elong":     18.0,
    },
    {
        "grade":     "ASTM A709 HPS 70W",
        "family":    "HSLA",
        "route":     "TMCP",
        "austen":    None,
        "quench":    None,
        "comp": {"C": 0.11, "Mn": 1.10, "Si": 0.35, "Cr": 0.70, "Ni": 0.40,
                 "Mo": 0.08, "V": 0.04, "Nb": 0.04, "Cu": 0.35, "P": 0.02, "S": 0.006},
        "uts_lo":    585,
        "uts_hi":    760,
        "ys":        485,
        "elong":     19.0,
    },
]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_astm_hsla_specs() -> List[Dict]:
    """
    Return SteelIngestBundle-compatible dicts for the ASTM HSLA spec grades.

    Usage:
        from data.parsers.astm_hsla_specs import parse_astm_hsla_specs, SOURCE_ID
        from data.ingest import ensure_source, ingest_bundles

        ensure_source(
            source_id=SOURCE_ID,
            source_type="literature",
            reliability=RELIABILITY,
            pub_year=SOURCE_YEAR,
            notes=(
                "ASTM HSLA structural steel specifications (A36, A572, A514, "
                "A588, A709). Minimum specification values from published ASTM "
                "standards — public domain. YS and UTS are specification "
                "minimums, not measured typical values."
            ),
        )
        records = parse_astm_hsla_specs()
        print(ingest_bundles(records))
    """
    records: List[Dict] = []

    for g in _GRADES:
        grade = g["grade"]
        steel_id = _det_id("v_hsla", grade)
        comp_id  = _det_id("v_hsla_comp", grade)
        proc_id  = _det_id("v_hsla_proc", grade)
        prop_id  = _det_id("v_hsla_prop", grade)

        route = g["route"]

        # UTS: use midpoint if range given, else use minimum
        uts_lo = g["uts_lo"]
        uts_hi = g.get("uts_hi")
        uts = ((uts_lo + uts_hi) / 2.0) if uts_hi else float(uts_lo)

        processing: List[Dict] = []
        if route:
            proc_rec: Dict[str, Any] = {
                "processing_id": proc_id,
                "steel_id":      steel_id,
                "route_type":    route,
                "notes":         f"ASTM spec. {grade}.",
            }
            if g.get("austen"):
                proc_rec["austenitize_temp_C"] = float(g["austen"])
            if g.get("quench"):
                proc_rec["quench_medium"] = g["quench"]
            if route == "QT" and not g.get("quench"):
                proc_rec["quench_medium"] = "other"
            processing.append(proc_rec)

        prop: Dict[str, Any] = {
            "property_id":   prop_id,
            "steel_id":      steel_id,
            "processing_id": proc_id if processing else None,
            "test_temp_C":   25.0,
            "uts_MPa":              uts,
            "yield_strength_MPa":   float(g["ys"]),
            "elongation_pct":       float(g["elong"]),
        }

        comp_record: Dict[str, Any] = {
            "steel_id":       steel_id,
            "composition_id": comp_id,
        }
        for elem, val in g["comp"].items():
            if elem in {"C","Mn","Si","Cr","Ni","Mo","V","Nb","Ti","Al","Cu","N","P","S","Co","W"}:
                comp_record[elem] = round(float(val), 4)

        records.append({
            "steel": {
                "steel_id":     steel_id,
                "grade":        grade,
                "steel_family": g["family"],
                "source_id":    SOURCE_ID,
                "notes":        (
                    f"ASTM specification minimum values. {grade}. "
                    f"YS={g['ys']} MPa min, UTS={uts_lo} MPa min. "
                    "Values are specification limits, not measured typicals."
                ),
            },
            "composition":    comp_record,
            "processing":     processing,
            "properties":     [prop],
            "microstructure": [],
        })

    logger.info(f"ASTM HSLA specs: {len(records)} records")
    return records
