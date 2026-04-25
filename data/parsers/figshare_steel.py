"""
Parser for the Figshare Steel Strength dataset.

SOURCE
------
High-strength and high-alloy steel composition + mechanical properties dataset.
File: data/Figshare/steel_strength.csv
Access: https://figshare.com  (update SOURCE_DOI once confirmed)

COVERAGE
--------
311 records (312 lines minus header). All records have:
  - Composition: C, Mn, Si, Cr, Ni, Mo, V, N, Nb, Co, W, Al, Ti (wt%, no nulls)
  - Properties: yield strength (MPa), tensile strength (MPa), elongation (9 nulls)
  - No processing data — processing_id will be null in all property records

STEEL FAMILIES
--------------
  maraging  (~71 records): Co > 5 wt% and Ni > 8 wt%
  stainless (~126 records): Cr > 10.5 wt%
  low-alloy (~115 records): everything else

This dataset skews heavily toward high-strength/high-alloy compositions
(yield 1006–2510 MPa, mean ~1421 MPa). It is NOT representative of standard
AISI carbon steel grades — weight training data accordingly.

DATA QUALITY NOTES
------------------
- All 311 rows pass UTS >= yield validation.
- 9 rows have null elongation — stored as NULL, not 0.
- Composition columns are in wt%. The `formula` column in the CSV gives
  atomic fractions — not used (redundant with wt% columns).
- No hardness, no Charpy, no fracture toughness in source file.
- Reliability: 3 (literature-aggregated dataset; exact measurement provenance
  not disclosed in the Figshare release).

SOURCE_ID: src_figshare_steel
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

SOURCE_ID  = "src_figshare_steel"
RELIABILITY = 3
DATA_FILE  = Path(__file__).parent.parent / "Figshare" / "steel_strength.csv"

# Update once you confirm the exact Figshare DOI / URL
SOURCE_DOI  = None
SOURCE_YEAR = None   # update if publication year is known


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


def _classify_family(row: pd.Series) -> str:
    """
    Classify steel family from composition.
    Priority: maraging > stainless > low-alloy.
    """
    co = _safe_float(row.get("co")) or 0.0
    ni = _safe_float(row.get("ni")) or 0.0
    cr = _safe_float(row.get("cr")) or 0.0
    w  = _safe_float(row.get("w"))  or 0.0
    v  = _safe_float(row.get("v"))  or 0.0
    c  = _safe_float(row.get("c"))  or 0.0

    if co > 5.0 and ni > 8.0:
        return "maraging"
    if cr > 10.5:
        return "stainless"
    if (w > 1.0 or v > 1.0) and c > 0.5:
        return "tool"
    return "low-alloy"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_figshare_steel(path: Optional[Path] = None) -> List[Dict]:
    """
    Parse the Figshare steel strength CSV.

    Returns:
        List of dicts matching SteelIngestBundle structure, ready for ingest_bundles().

    Usage:
        from data.parsers.figshare_steel import parse_figshare_steel, SOURCE_ID
        from data.ingest import ensure_source, ingest_bundles

        ensure_source(
            source_id=SOURCE_ID,
            source_type="literature",
            reliability=3,
            doi=SOURCE_DOI,
            pub_year=SOURCE_YEAR,
            notes=(
                "Figshare steel strength dataset. 311 high-strength/high-alloy "
                "steel records (maraging, stainless, low-alloy). Composition in "
                "wt%; yield + UTS + elongation. No processing data."
            ),
        )
        records = parse_figshare_steel()
        print(ingest_bundles(records))
    """
    fpath = path or DATA_FILE
    df = pd.read_csv(fpath)

    # Composition column map: CSV name → schema field name
    COMP_MAP = {
        "c":  "C",
        "mn": "Mn",
        "si": "Si",
        "cr": "Cr",
        "ni": "Ni",
        "mo": "Mo",
        "v":  "V",
        "n":  "N",
        "nb": "Nb",
        "co": "Co",
        "w":  "W",
        "al": "Al",
        "ti": "Ti",
    }

    records: List[Dict] = []

    for i, row in df.iterrows():
        formula = str(row.get("formula", "")).strip()

        # Build composition dict (skip zero values — store as NULL not 0.0)
        comp_vals: Dict[str, float] = {}
        for csv_col, schema_field in COMP_MAP.items():
            v = _safe_float(row.get(csv_col))
            if v is not None and v > 0.0:
                comp_vals[schema_field] = v

        # Deterministic ID from full composition signature
        id_key = "_".join(f"{k}{comp_vals.get(k, 0)}" for k in sorted(COMP_MAP.values()))
        steel_id = _det_id("v_fsh", id_key)
        comp_id  = _det_id("v_fsh_comp", id_key)
        prop_id  = _det_id("v_fsh_prop", id_key)

        family = _classify_family(row)

        # Use formula string as grade label (most informative identifier available)
        grade_label = formula if formula else f"Figshare_{i+1}"

        uts    = _safe_float(row.get("tensile strength"))
        yield_ = _safe_float(row.get("yield strength"))
        elong  = _safe_float(row.get("elongation"))

        if uts is None and yield_ is None:
            continue

        comp_dict: Dict[str, Any] = {"steel_id": steel_id, "composition_id": comp_id}
        comp_dict.update(comp_vals)

        prop: Dict[str, Any] = {
            "property_id": prop_id,
            "steel_id": steel_id,
            "processing_id": None,
            "test_temp_C": 25.0,
        }
        if uts    is not None: prop["uts_MPa"]            = uts
        if yield_ is not None: prop["yield_strength_MPa"] = yield_
        if elong  is not None: prop["elongation_pct"]      = elong

        records.append({
            "steel": {
                "steel_id": steel_id,
                "grade": grade_label,
                "steel_family": family,
                "source_id": SOURCE_ID,
                "notes": (
                    f"Figshare steel strength dataset, row {i+1}. "
                    f"Family: {family}. No processing data."
                ),
            },
            "composition": comp_dict,
            "processing": [],
            "properties": [prop],
            "microstructure": [],
        })

    logger.info(f"Figshare steel: {len(records)} records parsed")
    return records
