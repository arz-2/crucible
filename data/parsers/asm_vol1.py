"""
Parser for ASM Handbook Volume 1 Knovel table exports.

SOURCE
------
ASM Handbook, Volume 1: Properties and Selection: Irons, Steels, and
High-Performance Alloys. ASM International, 1990.
Accessed via Knovel (CMU institutional license).

FILES AND TABLES
----------------
  vol1_estimated_mechanical_properties_nonresulfurized_carbon_steel_bars_part1/2/3.csv
                         — Table 9:  Estimated mechanical properties of
                           nonresulfurized carbon steel bars (101 records)
  vol1_astm_specifications_mechanical_properties_structural_plate.csv
                         — Table 7:  ASTM structural plate specs, min properties
                           (49 records; carbon, low-alloy, HSLA)
  vol1_carbon_steel_compositions_bars_rods_tubing.csv
                         — Table 12: Carbon steel compositions, bars/rods (48 grades)
  vol1_carbon_steel_compositions_structural_shapes_plate_sheet.csv
                         — Table 13: Carbon steel compositions, plate/sheet (43 grades)
  vol1_ams_alloy_steel_nominal_compositions_part1/2/3.csv
                         — Table 27: AMS alloy steel nominal compositions (149 grades)

DATA QUALITY NOTES
------------------
- All property values are TYPICAL or MINIMUM specification values, not individual
  heat measurements. Reliability: 4.
- Table 7 properties are MINIMUM ASTM specification values — treat as lower bounds,
  not typical measured properties. processing_id is always null (no heat treatment
  info given; as_rolled implied for structural plate).
- Table 9 processing types: Hot rolled / Cold drawn / ACD (annealed cold drawn) /
  SACD (spheroidize annealed cold drawn) / NCD (normalized cold drawn). All mapped
  to route_type with no temperature data — austenitize/temper temps are null.
- Tables 12/13 overlap in grade coverage; Table 12 (bars/rods) is used as primary.
  Table 13 adds plate/sheet product-form-specific limits for the same grades.
- Table 27 AMS designations map to nearest AISI-SAE grade via the 'nearest grade'
  column. Many AMS grades are product-form variants of the same composition.
- Composition values are nominal ranges; midpoints are stored.
- IDs are deterministic (content-based) so re-ingestion skips duplicates cleanly.

SOURCE_ID: src_asm_vol1
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

SOURCE_ID = "src_asm_vol1"
RELIABILITY = 4
BASE_DIR = Path(__file__).parent.parent / "ASM"


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _det_id(prefix: str, *parts: str) -> str:
    """Deterministic ID from content — safe to re-ingest without duplicates."""
    key = "_".join(str(p) for p in parts)
    h = hashlib.md5(key.encode()).hexdigest()[:10]
    return f"{prefix}_{h}"


def _parse_range_midpoint(val: Any) -> Optional[float]:
    """Parse composition/property range string to midpoint float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        import math
        return None if (isinstance(val, float) and math.isnan(val)) else float(val)
    s = str(val).strip()
    if s in ("-", "", "nan", "..."):
        return None
    m = re.match(r"^([\d.]+)\s*[-–]\s*([\d.]+)$", s)
    if m:
        return round((float(m.group(1)) + float(m.group(2))) / 2, 4)
    m = re.match(r"^([\d.]+)\s*max$", s, re.IGNORECASE)
    if m:
        return round(float(m.group(1)) / 2, 4)
    try:
        return float(s)
    except ValueError:
        return None


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", skiprows=4, header=0)
    df.columns = [c.replace("\n", " ").strip() for c in df.columns]
    return df


def _valid_rows(df: pd.DataFrame, no_col: str = "No.") -> pd.DataFrame:
    """Keep only rows where the row-number column is a digit (drops header/footer junk)."""
    mask = df[no_col].apply(
        lambda x: str(x).replace(".0", "").strip().isdigit() if pd.notna(x) else False
    )
    return df[mask].copy()


def _uns_to_sae(uns: str) -> Optional[str]:
    m = re.match(r"^G(\d{4})\d$", str(uns).strip(), re.IGNORECASE)
    if m:
        return m.group(1).lstrip("0") or "0"
    return None


def _sae_to_family(sae: Any) -> str:
    s = re.sub(r"[^0-9]", "", str(sae))[:4]
    if re.match(r"1[0-5]", s):
        return "carbon"
    if s:
        return "low-alloy"
    return "other"


# ---------------------------------------------------------------------------
# Table 9 — carbon steel bar properties by processing
# ---------------------------------------------------------------------------

_T9_ROUTE_MAP = {
    "hot rolled":   "as_rolled",
    "cold drawn":   "as_rolled",
    "acd":          "anneal",      # annealed cold drawn
    "sacd":         "anneal",      # spheroidize annealed cold drawn
    "ncd":          "normalize",   # normalized cold drawn
}


def _parse_table9(paths: List[Path]) -> List[Dict]:
    dfs = [_valid_rows(_load_csv(p)) for p in paths]
    df = pd.concat(dfs, ignore_index=True)

    records: List[Dict] = []
    for _, row in df.iterrows():
        sae_raw = str(row.get("SAE and/or  AISI No.", "")).strip().rstrip(".0")
        uns_raw = str(row.get("UNS no.", "")).strip()
        processing_raw = str(row.get("type of  processing (a)", "")).strip()
        if not sae_raw or not processing_raw:
            continue

        route_key = processing_raw.lower()
        route_type = _T9_ROUTE_MAP.get(route_key, "as_rolled")
        family = _sae_to_family(sae_raw)

        steel_id = _det_id("asm9", sae_raw, processing_raw)
        proc_id  = _det_id("proc_asm9", sae_raw, processing_raw)

        proc_data: Dict[str, Any] = {
            "processing_id": proc_id,
            "steel_id": steel_id,
            "route_type": route_type,
        }

        yield_mpa = _safe_float(row.get("yield strength (MPa)"))
        uts_mpa   = _safe_float(row.get("tensile strength (MPa)"))
        elong     = _safe_float(row.get("elongation in  50 mm (2 in) (%)"))
        ra        = _safe_float(row.get("reduction  in area (%)"))
        hb        = _safe_float(row.get("hardness, HB (unitless)"))

        if not any(v is not None for v in [yield_mpa, uts_mpa, elong, ra, hb]):
            continue

        records.append({
            "steel": {
                "steel_id": steel_id,
                "grade": f"SAE {sae_raw}",
                "steel_family": family,
                "source_id": SOURCE_ID,
                "notes": (
                    f"ASM Vol.1 Table 9 — SAE {sae_raw} ({uns_raw}), "
                    f"processing: {processing_raw}. Typical bar properties."
                ),
            },
            "composition": None,
            "processing": [proc_data],
            "properties": [{
                "property_id": _det_id("prop_asm9", sae_raw, processing_raw),
                "steel_id": steel_id,
                "processing_id": proc_id,
                "yield_strength_MPa": yield_mpa,
                "uts_MPa": uts_mpa,
                "elongation_pct": elong,
                "reduction_area_pct": ra,
                "hardness_HB": hb,
                "test_temp_C": 25.0,
            }],
            "microstructure": [],
        })

    logger.info(f"Table 9: {len(records)} property records parsed")
    return records


# ---------------------------------------------------------------------------
# Table 7 — ASTM structural plate minimum properties
# ---------------------------------------------------------------------------

_ASTM_FAMILY_MAP = {
    "carbon steel":   "carbon",
    "low-alloy steel": "low-alloy",
    "hsla steels":    "HSLA",
}


def _parse_table7(path: Path) -> List[Dict]:
    df = _valid_rows(_load_csv(path))
    records: List[Dict] = []

    for _, row in df.iterrows():
        classification = str(row.get("classification", "")).strip()
        spec = str(row.get("ASTM  specification", "")).strip()
        grade = str(row.get("material grade or type", "")).strip()
        if not spec:
            continue

        family = _ASTM_FAMILY_MAP.get(classification.lower(), "other")
        grade_str = f"ASTM {spec}" + (f" Gr.{grade}" if grade and grade != "nan" else "")
        steel_id = _det_id("asm7", spec, grade)

        yield_mpa = _parse_range_midpoint(row.get("yield strength (a) (MPa)"))
        uts_mpa   = _parse_range_midpoint(row.get("tensile strength (a) (MPa)"))
        elong_200 = _safe_float(row.get("elongation (b) in  200 mm (8 in) (%)"))
        elong_50  = _safe_float(row.get("elongation (b) in  50 mm (2 in) (%)"))
        elong     = elong_50 if elong_50 is not None else elong_200

        if not any(v is not None for v in [yield_mpa, uts_mpa, elong]):
            continue

        records.append({
            "steel": {
                "steel_id": steel_id,
                "grade": grade_str,
                "steel_family": family,
                "source_id": SOURCE_ID,
                "notes": (
                    f"ASM Vol.1 Table 7 — {grade_str}. "
                    "Minimum ASTM specification values for structural plate. "
                    "No processing history — as-rolled implied."
                ),
            },
            "composition": None,
            "processing": [],
            "properties": [{
                "property_id": _det_id("prop_asm7", spec, grade),
                "steel_id": steel_id,
                "processing_id": None,
                "yield_strength_MPa": yield_mpa,
                "uts_MPa": uts_mpa,
                "elongation_pct": elong,
                "test_temp_C": 25.0,
            }],
            "microstructure": [],
        })

    logger.info(f"Table 7: {len(records)} property records parsed")
    return records


# ---------------------------------------------------------------------------
# Tables 12 & 13 — carbon steel compositions
# ---------------------------------------------------------------------------

def _parse_comp_table(path: Path, product_form: str) -> List[Dict]:
    df = _valid_rows(_load_csv(path))
    records: List[Dict] = []

    c_col  = next((c for c in df.columns if c.startswith("Cast or heat") and "; C " in c), None)
    mn_col = next((c for c in df.columns if c.startswith("Cast or heat") and "; Mn " in c), None)
    p_col  = next((c for c in df.columns if c.startswith("Cast or heat") and "; P " in c), None)
    s_col  = next((c for c in df.columns if c.startswith("Cast or heat") and "; S " in c), None)

    for _, row in df.iterrows():
        uns_raw = str(row.get("UNS number", "")).strip()
        sae_raw = str(row.get("SAE-AISI number", "")).strip().rstrip(".0")
        if not sae_raw:
            continue

        sae_clean = sae_raw.lstrip("0") or sae_raw
        family = _sae_to_family(sae_raw)
        steel_id = _det_id("asm_comp", sae_raw, product_form)

        comp: Dict[str, Any] = {
            "steel_id": steel_id,
            "C":  _parse_range_midpoint(row.get(c_col))  if c_col  else None,
            "Mn": _parse_range_midpoint(row.get(mn_col)) if mn_col else None,
            "P":  _parse_range_midpoint(row.get(p_col))  if p_col  else None,
            "S":  _parse_range_midpoint(row.get(s_col))  if s_col  else None,
        }

        if all(v is None for k, v in comp.items() if k != "steel_id"):
            continue

        records.append({
            "steel": {
                "steel_id": steel_id,
                "grade": f"SAE {sae_clean}",
                "steel_family": family,
                "source_id": SOURCE_ID,
                "notes": (
                    f"ASM Vol.1 Table 12/13 — SAE {sae_clean} ({uns_raw}), "
                    f"product form: {product_form}. Nominal composition range midpoints."
                ),
            },
            "composition": comp,
            "processing": [],
            "properties": [],
            "microstructure": [],
        })

    logger.info(f"Comp table ({product_form}): {len(records)} records parsed")
    return records


# ---------------------------------------------------------------------------
# Table 27 — AMS alloy steel compositions
# ---------------------------------------------------------------------------

_SI_PAT  = re.compile(r"(\d[\d.]*)\s*Si",  re.IGNORECASE)
_V_PAT   = re.compile(r"(\d[\d.]*)\s*V\b", re.IGNORECASE)
_MN_PAT  = re.compile(r"(\d[\d.]*)\s*Mn",  re.IGNORECASE)
_NB_PAT  = re.compile(r"(\d[\d.]*)\s*Nb",  re.IGNORECASE)


def _parse_other(other_str: str) -> Dict[str, Optional[float]]:
    """Extract additional elements from the 'other' free-text column."""
    result: Dict[str, Optional[float]] = {}
    if not other_str or other_str.strip() in ("-", "nan", ""):
        return result
    for pat, key in [(_SI_PAT, "Si"), (_V_PAT, "V"), (_MN_PAT, "Mn"), (_NB_PAT, "Nb")]:
        m = pat.search(other_str)
        if m:
            result[key] = _parse_range_midpoint(m.group(1))
    return result


def _parse_table27(paths: List[Path]) -> List[Dict]:
    dfs = [_valid_rows(_load_csv(p)) for p in paths]
    df = pd.concat(dfs, ignore_index=True)

    records: List[Dict] = []
    for _, row in df.iterrows():
        ams = str(row.get("AMS designation", "")).strip()
        product_form = str(row.get("product form (a)", "")).strip()
        nearest_sae = str(row.get("nearest  proprietary or  AISI-SAE grade", "")).strip()
        uns_raw = str(row.get("UNS number", "")).strip()
        if not ams:
            continue

        # Infer steel_family from nearest SAE or UNS
        sae_digits = re.sub(r"[^0-9]", "", nearest_sae)[:4]
        family = _sae_to_family(sae_digits) if sae_digits else "low-alloy"

        other_str = str(row.get("other", ""))
        other_elements = _parse_other(other_str)

        steel_id = _det_id("asm27", ams, product_form[:20])

        comp: Dict[str, Any] = {
            "steel_id": steel_id,
            "C":  _parse_range_midpoint(row.get("C (%)")),
            "Cr": _parse_range_midpoint(row.get("Cr (%)")),
            "Ni": _parse_range_midpoint(row.get("Ni (%)")),
            "Mo": _parse_range_midpoint(row.get("Mo (%)")),
            **{k: v for k, v in other_elements.items() if v is not None},
        }

        if all(v is None for k, v in comp.items() if k != "steel_id"):
            continue

        records.append({
            "steel": {
                "steel_id": steel_id,
                "grade": f"AMS {ams}",
                "steel_family": family,
                "source_id": SOURCE_ID,
                "notes": (
                    f"ASM Vol.1 Table 27 — AMS {ams}, nearest SAE: {nearest_sae}, "
                    f"UNS: {uns_raw}, form: {product_form[:60]}. "
                    "Nominal composition range midpoints."
                    + (f" Other: {other_str}" if other_str.strip() not in ("-","nan","") else "")
                ),
            },
            "composition": comp,
            "processing": [],
            "properties": [],
            "microstructure": [],
        })

    logger.info(f"Table 27: {len(records)} AMS composition records parsed")
    return records


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_asm_vol1(
    base_dir: Optional[Path] = None,
    include_table9:  bool = True,
    include_table7:  bool = True,
    include_table12: bool = True,
    include_table13: bool = True,
    include_table27: bool = True,
) -> List[Dict]:
    """
    Parse all usable ASM Handbook Vol.1 Knovel table exports.

    Args:
        base_dir: Path to the ASM directory. Defaults to data/ASM/ relative to this file.

    Returns:
        List of dicts matching SteelIngestBundle structure.

    Example:
        from data.parsers.asm_vol1 import parse_asm_vol1, SOURCE_ID
        from data.ingest import ensure_source, ingest_bundles

        ensure_source(
            source_id=SOURCE_ID,
            source_type="literature",
            reliability=4,
            notes="ASM Handbook Vol.1: Properties and Selection: Irons, Steels, "
                  "and High-Performance Alloys. ASM International, 1990. "
                  "Accessed via Knovel (CMU institutional license)."
        )
        records = parse_asm_vol1()
        result = ingest_bundles(records)
        print(result)
    """
    d = base_dir or BASE_DIR
    records: List[Dict] = []

    if include_table9:
        paths = [
            d / f"vol1_estimated_mechanical_properties_nonresulfurized_carbon_steel_bars_part{i}.csv"
            for i in (1, 2, 3)
            if (d / f"vol1_estimated_mechanical_properties_nonresulfurized_carbon_steel_bars_part{i}.csv").exists()
        ]
        records += _parse_table9(paths)

    if include_table7:
        records += _parse_table7(d / "vol1_astm_specifications_mechanical_properties_structural_plate.csv")

    if include_table12:
        records += _parse_comp_table(d / "vol1_carbon_steel_compositions_bars_rods_tubing.csv", "bars_rods_tubing")

    if include_table13:
        records += _parse_comp_table(d / "vol1_carbon_steel_compositions_structural_shapes_plate_sheet.csv", "plate_sheet_strip")

    if include_table27:
        paths = [
            d / f"vol1_ams_alloy_steel_nominal_compositions_part{i}.csv"
            for i in (1, 2, 3)
            if (d / f"vol1_ams_alloy_steel_nominal_compositions_part{i}.csv").exists()
        ]
        records += _parse_table27(paths)

    logger.info(f"ASM Vol.1 parse complete: {len(records)} total records")
    return records
