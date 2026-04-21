"""
Parser for Mondal appendix tables — S.K. Mandal, "Steel Metallurgy:
Properties, Specifications and Applications", 1st Edition.

FILES
-----
  Plain_carbon_steels.xlsx                              — SAE 10xx/15xx composition ranges
  Standard_SAE_grade_alloy_steels.xlsx                  — SAE 13xx/4xxx/5xxx/6xxx/8xxx/9xxx composition ranges
  SAE_grade_free_cutting_resulphurised_steels_...xlsx   — SAE 11xx/12xx composition ranges
  Properties_of_steel.xlsx                              — mechanical properties linked to UNS + processing method

DATA QUALITY NOTES
------------------
- Composition values are NOMINAL RANGES from published standards, not individual heat measurements.
  Midpoints are stored; the range (±half-width) is meaningful context but the DB schema stores
  single floats. Treat model predictions from these records as grade-representative, not heat-specific.
- Property values are typical/representative, not measured on specific heats.
- Reliability: 4 (textbook specification values, high-quality source, not exact measurements).
- Processing temperatures in Properties_of_steel are in °F — converted to °C here.
- "Drawn XXXF" implies Q&T route: austenitized (assumed standard temp for grade), quenched, tempered at XXXF.
  Austenitizing temp is not given; left null. Do not infer it.

SOURCE_ID: src_mondal_appendix
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

SOURCE_ID = "src_mondal_appendix"
RELIABILITY = 4
BASE_DIR = Path(__file__).parent.parent / "Steel_metallurgy_Mondal_appendices"

COMP_FILES = {
    "carbon":      BASE_DIR / "Plain_carbon_steels.xlsx",
    "alloy":       BASE_DIR / "Standard_SAE_grade_alloy_steels.xlsx",
    "free_cutting": BASE_DIR / "SAE_grade_free_cutting_resulphurised_steels_chemical_composition.xlsx",
}
PROPS_FILE = BASE_DIR / "Properties_of_steel.xlsx"


# ---------------------------------------------------------------------------
# Composition range parsing
# ---------------------------------------------------------------------------

def _parse_range_midpoint(val: Any) -> Optional[float]:
    """
    Parse a composition range string to its midpoint.

    Handles:
      "0.28/0.33"  → 0.305
      "0.06 max"   → 0.03   (half of max)
      "0.35 max"   → 0.175
      "-"          → None
      NaN          → None
      1.70         → 1.70   (already numeric)
    """
    if val is None:
        return None
    if isinstance(val, float):
        import math
        return None if math.isnan(val) else val
    if isinstance(val, int):
        return float(val)

    s = str(val).strip()
    if s in ("-", "", "nan"):
        return None

    # "X/Y" range
    m = re.match(r"^([\d.]+)\s*/\s*([\d.]+)$", s)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return round((lo + hi) / 2, 5)

    # "X max"
    m = re.match(r"^([\d.]+)\s*max$", s, re.IGNORECASE)
    if m:
        return round(float(m.group(1)) / 2, 5)

    # Plain number
    try:
        return float(s)
    except ValueError:
        logger.debug(f"Could not parse composition value: {val!r}")
        return None


def _sae_to_family(sae: Any) -> str:
    s = str(sae).strip().lstrip("0")
    if re.match(r"^1[0-5]\d{2}", s):    # 10xx, 11xx, 12xx, 15xx
        return "carbon"
    if re.match(r"^[2-9]\d{3}", s):
        return "low-alloy"
    return "other"


# ---------------------------------------------------------------------------
# UNS → SAE mapping for the properties table
# ---------------------------------------------------------------------------

# UNS G-numbers follow: G + SAE 4-digit + trailing 0 (standard grade)
def _uns_to_sae(uns: str) -> Optional[str]:
    # UNS G-numbers: G + 4-digit SAE + 1-digit modifier (0 = standard grade)
    m = re.match(r"^G(\d{4})\d$", str(uns).strip(), re.IGNORECASE)
    if m:
        digits = m.group(1).lstrip("0") or "0"
        return digits
    return None


# ---------------------------------------------------------------------------
# Processing method parsing (Properties_of_steel.xlsx)
# ---------------------------------------------------------------------------

_FAHRENHEIT_PAT = re.compile(r"(\d+)\s*[°]?\s*[Ff]", re.IGNORECASE)


def _parse_processing(method: str) -> Tuple[str, Optional[float]]:
    """
    Returns (route_type, temper_temp_C).

    "Hot Rolled"            → ("as_rolled",  None)
    "Cold Drawn"            → ("as_rolled",  None)   # cold work, no HT
    "Hot Rolled, Annealed"  → ("anneal",     None)
    "Cold Drawn, Annealed"  → ("anneal",     None)
    "Case Hardened"         → ("case_harden",None)
    "Drawn 1000°F"          → ("QT",         537.8)
    "Drawn 800°F"           → ("QT",         426.7)
    """
    s = str(method).strip()
    lower = s.lower()

    # Tempered (Drawn at temperature) → QT
    m = _FAHRENHEIT_PAT.search(s)
    if m:
        temp_f = float(m.group(1))
        temp_c = round((temp_f - 32) * 5 / 9, 1)
        return "QT", temp_c

    if "case" in lower:
        return "case_harden", None
    if "anneal" in lower:
        return "anneal", None
    return "as_rolled", None


# ---------------------------------------------------------------------------
# Composition table parsers
# ---------------------------------------------------------------------------

def _parse_carbon_steels(path: Path) -> List[Dict]:
    df = pd.read_excel(path, sheet_name="Table_data")
    records = []
    for _, row in df.iterrows():
        sae = str(row.get("SAE No.", "")).strip()
        if not sae:
            continue
        steel_id = f"mondal_c_{uuid.uuid4().hex[:8]}"
        records.append({
            "steel": {
                "steel_id": steel_id,
                "grade": f"SAE {sae}",
                "steel_family": _sae_to_family(sae),
                "source_id": SOURCE_ID,
                "notes": f"Mondal appendix — Plain carbon steel SAE {sae}. Nominal composition range midpoints.",
            },
            "composition": {
                "steel_id": steel_id,
                "C":  _parse_range_midpoint(row.get("%C")),
                "Mn": _parse_range_midpoint(row.get("%Mn")),
                "S":  _parse_range_midpoint(row.get("%S (max)")),
                "P":  _parse_range_midpoint(row.get("%P (max)")),
            },
            "processing": [],
            "properties": [],
            "microstructure": [],
        })
    logger.info(f"Plain carbon steels: {len(records)} records parsed")
    return records


def _parse_alloy_steels(path: Path) -> List[Dict]:
    df = pd.read_excel(path, sheet_name="Table_data")
    records = []
    for _, row in df.iterrows():
        sae = str(row.get("SAE No.", "")).strip()
        if not sae:
            continue
        steel_id = f"mondal_a_{uuid.uuid4().hex[:8]}"

        others_raw = str(row.get("Others", "")).strip()
        # Parse Si from Others field if present (e.g. "Si 0.70/1.10")
        si_val: Optional[float] = None
        m = re.search(r"Si\s+([\d./]+(?:\s*max)?)", others_raw, re.IGNORECASE)
        if m:
            si_val = _parse_range_midpoint(m.group(1))

        records.append({
            "steel": {
                "steel_id": steel_id,
                "grade": f"SAE {sae}",
                "steel_family": _sae_to_family(sae),
                "source_id": SOURCE_ID,
                "notes": (
                    f"Mondal appendix — SAE alloy steel {sae}. Nominal composition range midpoints."
                    + (f" Others: {others_raw}" if others_raw and others_raw != "-" else "")
                ),
            },
            "composition": {
                "steel_id": steel_id,
                "C":  _parse_range_midpoint(row.get("%C")),
                "Mn": _parse_range_midpoint(row.get("%Mn")),
                "Cr": _parse_range_midpoint(row.get("%Cr")),
                "Ni": _parse_range_midpoint(row.get("%Ni")),
                "Mo": _parse_range_midpoint(row.get("%Mo")),
                "Si": si_val,
            },
            "processing": [],
            "properties": [],
            "microstructure": [],
        })
    logger.info(f"Alloy steels: {len(records)} records parsed")
    return records


def _parse_free_cutting_steels(path: Path) -> List[Dict]:
    df = pd.read_excel(path, sheet_name="Table_data")
    records = []
    for _, row in df.iterrows():
        sae = str(row.get("SAE No.", "")).strip()
        if not sae:
            continue
        steel_id = f"mondal_fc_{uuid.uuid4().hex[:8]}"
        records.append({
            "steel": {
                "steel_id": steel_id,
                "grade": f"SAE {sae}",
                "steel_family": "carbon",
                "source_id": SOURCE_ID,
                "notes": f"Mondal appendix — Free-cutting resulfurized steel SAE {sae}. Nominal composition range midpoints.",
            },
            "composition": {
                "steel_id": steel_id,
                "C":  _parse_range_midpoint(row.get("%C")),
                "Mn": _parse_range_midpoint(row.get("%Mn")),
                "P":  _parse_range_midpoint(row.get("%P")),
                "S":  _parse_range_midpoint(row.get("%S")),
            },
            "processing": [],
            "properties": [],
            "microstructure": [],
        })
    logger.info(f"Free-cutting steels: {len(records)} records parsed")
    return records


# ---------------------------------------------------------------------------
# Properties table parser
# ---------------------------------------------------------------------------

def _parse_properties(path: Path) -> List[Dict]:
    df = pd.read_excel(path, sheet_name="Table_data")
    records = []
    for _, row in df.iterrows():
        uns = str(row.get("UNS Number", "")).strip()
        method = str(row.get("Processing Method", "")).strip()
        if not uns or not method:
            continue

        sae = _uns_to_sae(uns)
        grade_str = f"SAE {sae}" if sae else uns
        family = _sae_to_family(sae) if sae else "other"

        route_type, temper_c = _parse_processing(method)

        steel_id = f"mondal_p_{uuid.uuid4().hex[:8]}"
        proc_id = f"proc_{uuid.uuid4().hex[:8]}"

        has_proc = True  # processing method is always given in this table

        proc_data: Dict[str, Any] = {
            "processing_id": proc_id,
            "steel_id": steel_id,
            "route_type": route_type,
            "temper_temp_C": temper_c,
            # Austenitizing temp intentionally omitted — not provided in source
        }
        # QT without quench_medium — set to "other" to satisfy schema validator
        if route_type == "QT":
            proc_data["quench_medium"] = "other"

        yield_mpa  = _safe_float(row.get("Yield Strength (MPa)"))
        uts_mpa    = _safe_float(row.get("Tensile Strength (MPa)"))
        elong      = _safe_float(row.get("Elongation in 2 in. (%"))
        ra         = _safe_float(row.get("Reduction in Area (%)"))
        hardness_hb = _safe_float(row.get("Brinell Hardness (H_b)"))

        prop_data: Dict[str, Any] = {
            "property_id": f"prop_{uuid.uuid4().hex[:8]}",
            "steel_id": steel_id,
            "processing_id": proc_id if has_proc else None,
            "yield_strength_MPa": yield_mpa,
            "uts_MPa": uts_mpa,
            "elongation_pct": elong,
            "reduction_area_pct": ra,
            "hardness_HB": hardness_hb,
            "test_temp_C": 25.0,
        }

        records.append({
            "steel": {
                "steel_id": steel_id,
                "grade": grade_str,
                "steel_family": family,
                "source_id": SOURCE_ID,
                "notes": f"Mondal appendix — {uns} ({grade_str}), processing: {method}. Typical properties.",
            },
            "composition": None,  # Not available in this table; UNS cross-ref only
            "processing": [proc_data] if has_proc else [],
            "properties": [prop_data],
            "microstructure": [],
        })
    logger.info(f"Properties table: {len(records)} records parsed")
    return records


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_mondal(
    base_dir: Optional[Path] = None,
    include_compositions: bool = True,
    include_properties: bool = True,
) -> List[Dict]:
    """
    Parse all Mondal appendix files into a list of raw dicts for ingest_bundles().

    Args:
        base_dir:             Path to the Steel_metallurgy_Mondal_appendices directory.
                              Defaults to the sibling directory relative to this file.
        include_compositions: Parse the three composition tables (carbon, alloy, free-cutting).
        include_properties:   Parse the properties table.

    Returns:
        List of dicts matching SteelIngestBundle structure.

    Example:
        from data.parsers.mondal import parse_mondal, SOURCE_ID
        from data.ingest import ensure_source, ingest_bundles

        ensure_source(
            source_id=SOURCE_ID,
            source_type="literature",
            reliability=4,
            notes="S.K. Mandal, Steel Metallurgy: Properties, Specifications and Applications, 1st Ed."
        )
        records = parse_mondal()
        result = ingest_bundles(records)
        print(result)
    """
    if base_dir is not None:
        comp_files = {k: base_dir / v.name for k, v in COMP_FILES.items()}
        props_file = base_dir / PROPS_FILE.name
    else:
        comp_files = COMP_FILES
        props_file = PROPS_FILE

    records: List[Dict] = []

    if include_compositions:
        records += _parse_carbon_steels(comp_files["carbon"])
        records += _parse_alloy_steels(comp_files["alloy"])
        records += _parse_free_cutting_steels(comp_files["free_cutting"])

    if include_properties:
        records += _parse_properties(props_file)

    logger.info(f"Mondal parse complete: {len(records)} total records")
    return records
