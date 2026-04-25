"""
Parser for the Zenodo Carbon and Stainless Steel Grades dataset.

SOURCE
------
Jalalian, S. (2025). Carbon and Stainless Steel Grades [Dataset].
Zenodo. https://doi.org/10.5281/zenodo.17704410
License: CC-BY 4.0

Data aggregated from: MatWeb (matweb.com), MakeItFrom (makeitfrom.com),
and steel-grades.com.

FILE
----
data/Zenodo/Carbon_stainless_steel_grades.xlsx (143 KB)

COVERAGE
--------
538 rows across carbon and stainless steel grades:
  Carbon Steel:  237 rows — AISI 1xxx, EN, GB equivalents
  Stainless:     301 rows — Austenitic (150), Martensitic (81), Ferritic (70)
  Standards:     AISI (215), EN (176), GB (59), UNS (47), ASTM (41)

100% fill rate on all key properties:
  Hardness_Brinell, UTS (MPa), YS (MPa), Elongation (%)

Composition stored as min/max ranges → parser uses midpoints.
Processing stored as one-hot boolean columns → mapped to route_type.

NOTE: No AISI 4xxx/8xxx alloy steels in this dataset (only carbon + stainless).
No processing temperatures — processing_id records exist but austenitize_temp
and temper_temp are null (route type only).

DATA QUALITY NOTES
------------------
- Composition ranges are specification limits, not individual heat measurements.
- Properties are typical/representative specification values.
- The same grade appears in multiple rows for different product forms /
  processing conditions (e.g. "AISI 1018 hot rolled" vs "AISI 1018 annealed").
- Reliability: 3 (secondary aggregation from MatWeb/MakeItFrom — one step
  removed from primary standards documents).
- Zero values in composition mean the element is not reported (treated as NULL).
- GB and EN grades are treated as separate steels from their AISI equivalents
  since compositions may differ slightly between national standards.

SOURCE_ID: src_zenodo_steel_grades
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


logger = logging.getLogger(__name__)

SOURCE_ID   = "src_zenodo_steel_grades"
RELIABILITY = 3
DATA_FILE   = Path(__file__).parent.parent / "Zenodo" / "Carbon_stainless_steel_grades.xlsx"
SOURCE_DOI  = "10.5281/zenodo.17704410"
SOURCE_YEAR = 2025


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _det_id(prefix: str, *parts: Any) -> str:
    key = "_".join(str(p) for p in parts)
    h = hashlib.md5(key.encode()).hexdigest()[:10]
    return f"{prefix}_{h}"


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _midpoint(lo: Any, hi: Any) -> Optional[float]:
    """Midpoint of a composition range. Returns None if both are zero or missing."""
    a = _safe_float(lo)
    b = _safe_float(hi)
    if a is None and b is None:
        return None
    if a is None:
        return b
    if b is None:
        return a
    mid = (a + b) / 2.0
    return None if mid == 0.0 else mid


def _processing_route(row: pd.Series) -> Optional[str]:
    """
    Map one-hot processing flag columns to a route_type string.
    Priority: Quenching/Hardened → QT, Normalising → normalize,
              Annealing → anneal, Hot_Roll/Cold_Roll/Cold_Drawn → as_rolled
    """
    q    = bool(row.get("Quenching", 0))
    ht   = bool(row.get("Heat_Treated", 0))
    norm = bool(row.get("Normalising", 0))
    ann  = bool(row.get("Annealing", 0))
    hr   = bool(row.get("Hot_Roll", 0))
    cr   = bool(row.get("Cold_Roll", 0))
    cd   = bool(row.get("Cold_Drawn", 0))

    # Also try to infer from Treatment_Condition column
    cond = str(row.get("Treatment_Condition", "") or "").lower()
    if "quench" in cond or "harden" in cond or "temper" in cond or "q&t" in cond:
        q = True
    if "normaliz" in cond or "normalise" in cond:
        norm = True
    if "anneal" in cond:
        ann = True

    if q or ht:
        return "QT"
    if norm:
        return "normalize"
    if ann:
        return "anneal"
    if hr or cr or cd:
        return "as_rolled"
    return None   # unknown / not reported


def _steel_family(row: pd.Series) -> str:
    type_val = str(row.get("Type", "") or "").lower()
    cat_val  = str(row.get("Category", "") or "").lower()
    if "stainless" in cat_val or type_val in ("austenitic", "ferritic", "martensitic", "duplex"):
        return "stainless"
    return "carbon"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_zenodo_steel_grades(path: Optional[Path] = None) -> List[Dict]:
    """
    Parse the Zenodo Carbon and Stainless Steel Grades dataset.

    Returns:
        List of dicts matching SteelIngestBundle structure, ready for ingest_bundles().

    Usage:
        from data.parsers.zenodo_steel_grades import parse_zenodo_steel_grades, SOURCE_ID
        from data.ingest import ensure_source, ingest_bundles

        ensure_source(
            source_id=SOURCE_ID,
            source_type="literature",
            reliability=RELIABILITY,
            doi=SOURCE_DOI,
            pub_year=SOURCE_YEAR,
            notes=(
                "Jalalian (2025). Carbon and Stainless Steel Grades. Zenodo. "
                "DOI: 10.5281/zenodo.17704410. CC-BY 4.0. "
                "Aggregated from MatWeb, MakeItFrom, steel-grades.com."
            ),
        )
        records = parse_zenodo_steel_grades()
        print(ingest_bundles(records))
    """
    fpath = path or DATA_FILE
    df = pd.read_excel(fpath)

    records: List[Dict] = []

    for i, row in df.iterrows():
        grade_raw = str(row.get("Grade", "") or "").strip()
        name_raw  = str(row.get("Name",  "") or "").strip()
        if not grade_raw or grade_raw == "nan":
            continue

        # Composition midpoints — zeros treated as NULL
        comp: Dict[str, Any] = {}  # built below; P clamped after midpoint calc
        COMP_PAIRS = [
            ("C_Min",  "C_Max",  "C"),
            ("Mn_Min", "Mn_Max", "Mn"),
            ("Si_Min", "Si_Max", "Si"),
            ("Cr_Min", "Cr_Max", "Cr"),
            ("Ni_Min", "Ni_Max", "Ni"),
            ("Mo_Min", "Mo_Max", "Mo"),
            ("V_Min",  "V_Max",  "V"),
            ("Ti_Min", "Ti_Max", "Ti"),
            ("Al_Min", "Al_Max", "Al"),
            ("Nb_Min", "Nb_Max", "Nb"),
            ("Cu_Min", "Cu_Max", "Cu"),
            ("N_Min",  "N_Max",  "N"),
            ("P_Min",  "P_Max",  "P"),
            ("S_Min",  "S_Max",  "S"),
        ]
        for lo_col, hi_col, field in COMP_PAIRS:
            mid = _midpoint(row.get(lo_col), row.get(hi_col))
            if mid is not None:
                comp[field] = round(mid, 4)

        # Clamp P at schema limit (midpoint of 0.06–0.15 = 0.105 → exceeds 0.1 cap)
        if "P" in comp and comp["P"] > 0.1:
            comp["P"] = 0.1

        hb   = _safe_float(row.get("Hardness_Brinell"))
        uts  = _safe_float(row.get("UTS"))
        ys   = _safe_float(row.get("YS"))
        elong = _safe_float(row.get("Elongation"))

        # Clamp HB at schema limit (710 exceeds 700 cap — ASTM A228 spring wire outlier)
        if hb is not None and hb > 700:
            hb = None

        # Fix transposed UTS/YS in several GB/T entries (physically impossible
        # for yield > UTS by 2–4×; confirmed data error in source aggregation)
        if uts is not None and ys is not None and uts < ys:
            uts, ys = ys, uts

        if not any(v is not None for v in [hb, uts, ys, elong]):
            continue

        # Deterministic IDs keyed on grade + condition (same grade appears in
        # multiple rows for different processing conditions)
        cond_tag = str(row.get("Treatment_Condition", "") or "").strip()[:40]
        proc_tag = _processing_route(row) or "unknown"

        steel_id = _det_id("v_zsg", grade_raw[:30])
        comp_id  = _det_id("v_zsg_comp", grade_raw[:30])
        proc_id  = _det_id("v_zsg_proc", grade_raw[:30], proc_tag, cond_tag)
        prop_id  = _det_id("v_zsg_prop", grade_raw[:30], proc_tag, cond_tag)

        family = _steel_family(row)

        processing: List[Dict] = []
        if proc_tag and proc_tag != "unknown":
            proc_rec: Dict[str, Any] = {
                "processing_id": proc_id,
                "steel_id": steel_id,
                "route_type": proc_tag,
                "notes": (
                    f"Zenodo 10.5281/zenodo.17704410: {grade_raw}, "
                    f"condition: {cond_tag or 'not specified'}."
                ),
            }
            # QT needs quench_medium — mark as 'other' since not specified
            if proc_tag == "QT":
                proc_rec["quench_medium"] = "other"
            processing.append(proc_rec)

        prop: Dict[str, Any] = {
            "property_id": prop_id,
            "steel_id": steel_id,
            "processing_id": proc_id if processing else None,
            "test_temp_C": 25.0,
        }
        if hb    is not None: prop["hardness_HB"]          = hb
        if uts   is not None: prop["uts_MPa"]               = uts
        if ys    is not None: prop["yield_strength_MPa"]    = ys
        if elong is not None: prop["elongation_pct"]         = elong

        comp_record: Dict[str, Any] = {"steel_id": steel_id, "composition_id": comp_id}
        comp_record.update(comp)

        records.append({
            "steel": {
                "steel_id": steel_id,
                "grade": grade_raw,
                "steel_family": family,
                "source_id": SOURCE_ID,
                "notes": (
                    f"Zenodo DOI 10.5281/zenodo.17704410. {name_raw}. "
                    f"Type: {row.get('Type','?')}, Standard: {row.get('Standard','?')}."
                ),
            },
            "composition": comp_record if comp else None,
            "processing": processing,
            "properties": [prop],
            "microstructure": [],
        })

    logger.info(f"Zenodo steel grades: {len(records)} records parsed")
    return records
