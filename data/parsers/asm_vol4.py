"""
Parser for ASM Handbook Vol.4 (Heat Treating) Knovel table exports,
plus new Vol.1 (Properties and Selection) tables added in the second batch.

Vol.4 tables: QT grade tables (4340, 4130, 4140, 8640, 6150, D6A, 300M, H11 Mod, H13),
              HR/normalize/anneal properties, hardness after tempering (wide-format),
              maraging properties, tool steel heat treatment schedules,
              fracture toughness (4340, D6AC).

Vol.1 tables: Martensitic stainless steels, L/S tool steels.
              Ingested under SOURCE_ID_V1 = "src_asm_vol1" to reuse the existing
              source registration without adding a new entry.

SOURCE_ID: src_asm_vol4
Files: data/ASM/vol4_*.csv and data/ASM/vol1_{stainless,tool}*.csv
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

SOURCE_ID = "src_asm_vol4"
SOURCE_ID_V1 = "src_asm_vol1"
RELIABILITY = 4
BASE_DIR = Path(__file__).parent.parent / "ASM"

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _det_id(prefix: str, *parts: Any) -> str:
    key = "_".join(str(p) for p in parts)
    return f"{prefix}_{hashlib.md5(key.encode()).hexdigest()[:10]}"


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _range_midpoint(val: Any) -> Optional[float]:
    """Parse 'X - Y', 'X max', 'X (Average of N tests)', footnoted values, or plain number."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return _safe_float(val)
    s = str(val).strip()
    if not s or s in ("-", "nan", ""):
        return None
    # Strip trailing footnote like (a), (b)
    s = re.sub(r"\s*\([a-z]\)\s*$", "", s).strip()
    # "X (Average of N tests)"
    m = re.match(r"^([\d.]+)\s*\(Average", s, re.IGNORECASE)
    if m:
        return _safe_float(m.group(1))
    # "X - Y" or "X - Y"
    m = re.match(r"^([\d.]+)\s*[-–]\s*([\d.]+)$", s)
    if m:
        return round((float(m.group(1)) + float(m.group(2))) / 2, 4)
    # "X max"
    m = re.match(r"^([\d.]+)\s*max$", s, re.IGNORECASE)
    if m:
        return round(float(m.group(1)) / 2, 4)
    try:
        return float(s)
    except ValueError:
        return None


def _load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";", skiprows=4, header=0, dtype=str, encoding="utf-8-sig")


def _valid_rows(df: pd.DataFrame) -> pd.DataFrame:
    if "No." not in df.columns:
        return df.iloc[0:0]
    mask = df["No."].astype(str).str.strip().str.match(r"^\d+$")
    return df[mask].copy()


def _col(df: pd.DataFrame, *fragments: str) -> Optional[str]:
    """Return the first column whose name contains all fragments (case-insensitive, newlines ignored)."""
    for col in df.columns:
        col_low = col.lower().replace("\n", " ")
        if all(f.lower() in col_low for f in fragments):
            return col
    return None


def _sae_to_family(grade_str: str) -> str:
    digits = re.sub(r"[^0-9]", "", grade_str)
    if re.match(r"^1[0-5]", digits):
        return "carbon"
    if re.match(r"^[2-9]", digits):
        return "low-alloy"
    return "other"


def _clamp_hb(val: Optional[float]) -> Optional[float]:
    return val if (val is not None and val <= 700) else None


def _fix_uts_ys(uts: Optional[float], ys: Optional[float]):
    """Return (uts, ys) pair safe for schema. If YS > UTS, drop YS and log a warning."""
    if uts is not None and ys is not None and ys > uts:
        logger.warning("YS (%.0f) > UTS (%.0f) — dropping YS (source data issue)", ys, uts)
        return uts, None
    return uts, ys


def _group_by_steel(records: List[Dict]) -> List[Dict]:
    """Merge records that share a steel_id into a single bundle.

    The ingest pipeline skips an entire bundle when it finds a duplicate
    steel_id — so emitting one bundle per (steel, temper_temp) row loses all
    but the first row's processing and properties.  This helper collapses them.
    """
    from collections import OrderedDict
    steel_map: Dict[str, Dict] = OrderedDict()
    proc_map:  Dict[str, List] = {}
    prop_map:  Dict[str, List] = {}
    comp_map:  Dict[str, Any]  = {}

    for rec in records:
        sid = rec["steel"]["steel_id"]
        if sid not in steel_map:
            steel_map[sid] = rec["steel"]
            proc_map[sid]  = []
            prop_map[sid]  = []
            comp_map[sid]  = rec.get("composition")
        proc_map[sid].extend(rec.get("processing", []))
        prop_map[sid].extend(rec.get("properties", []))

    return [{
        "steel":          steel_map[sid],
        "composition":    comp_map[sid],
        "processing":     proc_map[sid],
        "properties":     prop_map[sid],
        "microstructure": [],
    } for sid in steel_map]


# ---------------------------------------------------------------------------
# Condition parsers
# ---------------------------------------------------------------------------

def _condition_to_route(cond: str) -> str:
    cond_l = cond.lower()
    if "anneal" in cond_l:
        return "anneal"
    if "normaliz" in cond_l:
        return "normalize"
    if "as-rolled" in cond_l or "as rolled" in cond_l:
        return "as_rolled"
    return "QT"


def _extract_temp_c(text: str) -> Optional[float]:
    """Extract first temperature in degrees C from a description string."""
    m = re.search(r"([\d]+(?:\s*[-–]\s*[\d]+)?)\s*\xb0C", text, re.IGNORECASE)
    if not m:
        return None
    return _range_midpoint(m.group(1))


# ---------------------------------------------------------------------------
# Sub-parsers
# ---------------------------------------------------------------------------

def _parse_hr_norm_anneal(paths: List[Path]) -> List[Dict]:
    """Vol4 Table 3 (parts 1+2): HR / normalized / annealed carbon and alloy steels."""
    records: List[Dict] = []
    for path in paths:
        if not path.exists():
            logger.warning("Missing: %s", path.name)
            continue
        df = _valid_rows(_load_csv(path))

        grade_col = _col(df, "aisi grade") or _col(df, "grade")
        cond_col  = _col(df, "condition")
        uts_col   = _col(df, "tensile strength", "mpa")
        ys_col    = _col(df, "yield strength", "mpa")
        el_col    = _col(df, "elongation")
        ra_col    = _col(df, "reduction")
        hb_col    = _col(df, "hardness, hb")
        izod_col  = _col(df, "izod", "j")

        for _, row in df.iterrows():
            grade = str(row.get(grade_col, "")).strip() if grade_col else ""
            if not grade:
                continue
            cond = str(row.get(cond_col, "")).strip() if cond_col else ""

            route_type = _condition_to_route(cond)
            aus_c: Optional[float] = None
            if route_type in ("normalize", "anneal"):
                aus_c = _extract_temp_c(cond)

            uts  = _safe_float(row.get(uts_col))  if uts_col  else None
            ys   = _safe_float(row.get(ys_col))   if ys_col   else None
            el   = _safe_float(row.get(el_col))   if el_col   else None
            ra   = _safe_float(row.get(ra_col))   if ra_col   else None
            hb   = _clamp_hb(_safe_float(row.get(hb_col)) if hb_col else None)
            izod = _safe_float(row.get(izod_col)) if izod_col else None

            if uts is None and ys is None and hb is None:
                continue

            steel_id = _det_id("v4hrna", grade, route_type, str(aus_c))
            proc_id  = _det_id("proc_v4hrna", steel_id)

            proc: Dict[str, Any] = {
                "processing_id": proc_id,
                "steel_id":      steel_id,
                "route_type":    route_type,
            }
            if aus_c is not None and 600.0 <= aus_c <= 1400.0:
                proc["austenitize_temp_C"] = aus_c

            prop: Dict[str, Any] = {
                "property_id":        _det_id("prop_v4hrna", steel_id),
                "steel_id":           steel_id,
                "processing_id":      proc_id,
                "uts_MPa":            uts,
                "yield_strength_MPa": ys,
                "elongation_pct":     el,
                "reduction_area_pct": ra,
                "hardness_HB":        hb,
                "test_temp_C":        25.0,
            }
            if izod is not None:
                prop["charpy_J"] = izod
                prop["notes"] = "Impact value is Izod (not Charpy V-notch)"

            records.append({
                "steel": {
                    "steel_id":     steel_id,
                    "grade":        f"AISI {grade}",
                    "steel_family": _sae_to_family(grade),
                    "source_id":    SOURCE_ID,
                    "notes":        f"ASM Vol.4 Table 3. {grade}, {cond}.",
                },
                "composition":    None,
                "processing":     [proc],
                "properties":     [prop],
                "microstructure": [],
            })
    records = _group_by_steel(records)
    logger.info("HR/norm/anneal: %d records", len(records))
    return records


def _parse_qt_table(
    path: Path,
    grade: str,
    aus_temp_c: float,
    quench_medium: str,
    family: str,
    tag: str,
    condition_col: Optional[str] = None,
    charpy: bool = False,
) -> List[Dict]:
    """Generic parser for QT tables with temper temperature as the row index."""
    if not path.exists():
        logger.warning("Missing: %s", path.name)
        return []

    df = _valid_rows(_load_csv(path))

    temper_col = _col(df, "tempering temperature", "\xb0c")
    uts_col    = _col(df, "tensile strength", "mpa")
    ys_col     = _col(df, "yield strength", "mpa")
    el_col     = _col(df, "elongation")
    ra_col     = _col(df, "reduction")
    hb_col     = _col(df, "hardness, hb")
    hrc_col    = _col(df, "hardness, hrc")

    if charpy:
        impact_col  = _col(df, "charpy", "j")
        impact_note = None
    else:
        impact_col  = _col(df, "izod", "j") or _col(df, "impact", "j")
        impact_note = "Impact energy is Izod (not Charpy V-notch)"

    # Locate the condition column for water-vs-oil differentiation (4130)
    actual_cond_col: Optional[str] = None
    if condition_col:
        actual_cond_col = _col(df, condition_col)

    records: List[Dict] = []
    for _, row in df.iterrows():
        temper_c = _safe_float(row.get(temper_col)) if temper_col else None
        uts  = _safe_float(row.get(uts_col))  if uts_col  else None
        ys   = _safe_float(row.get(ys_col))   if ys_col   else None
        el   = _safe_float(row.get(el_col))   if el_col   else None
        ra   = _safe_float(row.get(ra_col))   if ra_col   else None
        hb   = _clamp_hb(_safe_float(row.get(hb_col)) if hb_col else None)
        hrc  = _safe_float(row.get(hrc_col))  if hrc_col  else None

        impact_raw = str(row.get(impact_col, "")).strip() if impact_col else ""
        impact_m = re.match(r"^([\d.]+)", impact_raw)
        impact = _safe_float(impact_m.group(1)) if impact_m else None

        if uts is None and ys is None:
            continue

        # Override quench medium from condition column if present (4130)
        qm = quench_medium
        if actual_cond_col:
            cv = str(row.get(actual_cond_col, "")).lower()
            if "water" in cv:
                qm = "water"
            elif "oil" in cv:
                qm = "oil"

        steel_id = _det_id(f"v4qt_{tag}", grade, str(aus_temp_c), qm)
        proc_id  = _det_id(f"proc_v4qt_{tag}", steel_id, str(temper_c))

        proc: Dict[str, Any] = {
            "processing_id":      proc_id,
            "steel_id":           steel_id,
            "route_type":         "QT",
            "austenitize_temp_C": aus_temp_c,
            "quench_medium":      qm,
        }
        if temper_c is not None and 100.0 <= temper_c <= 800.0:
            proc["temper_temp_C"] = temper_c
        elif temper_c is not None:
            proc["notes"] = f"temper_temp={temper_c}\xb0C (outside schema [100,800] range)"

        uts, ys = _fix_uts_ys(uts, ys)
        prop: Dict[str, Any] = {
            "property_id":        _det_id(f"prop_v4qt_{tag}", steel_id, str(temper_c)),
            "steel_id":           steel_id,
            "processing_id":      proc_id,
            "uts_MPa":            uts,
            "yield_strength_MPa": ys,
            "elongation_pct":     el,
            "reduction_area_pct": ra,
            "hardness_HB":        hb,
            "hardness_HRC":       hrc if (hrc is not None and hrc <= 70) else None,
            "test_temp_C":        25.0,
        }
        if impact is not None:
            prop["charpy_J"] = impact
            if impact_note:
                prop["notes"] = impact_note

        records.append({
            "steel": {
                "steel_id":     steel_id,
                "grade":        grade,
                "steel_family": family,
                "source_id":    SOURCE_ID,
                "notes":        f"ASM Vol.4. {grade} QT, aus={aus_temp_c}\xb0C, quench={qm}.",
            },
            "composition":    None,
            "processing":     [proc],
            "properties":     [prop],
            "microstructure": [],
        })
    records = _group_by_steel(records)
    logger.info("QT %s: %d records", grade, len(records))
    return records


def _parse_maraging_age_hardened(path: Path) -> List[Dict]:
    """Maraging age-hardened properties including KIC (fracture toughness)."""
    if not path.exists():
        logger.warning("Missing: %s", path.name)
        return []
    df = _valid_rows(_load_csv(path))

    grade_col = _col(df, "grade")
    ht_col    = _col(df, "heat treatment")
    uts_col   = _col(df, "tensile strength", "mpa")
    ys_col    = _col(df, "yield strength", "mpa")
    el_col    = _col(df, "elongation")
    ra_col    = _col(df, "reduction")
    kic_col   = _col(df, "fracture toughness", "mpa")

    records: List[Dict] = []
    for _, row in df.iterrows():
        grade = str(row.get(grade_col, "")).strip() if grade_col else ""
        if not grade:
            continue

        uts = _range_midpoint(row.get(uts_col)) if uts_col else None
        ys  = _range_midpoint(row.get(ys_col))  if ys_col  else None
        el  = _range_midpoint(row.get(el_col))  if el_col  else None
        ra  = _range_midpoint(row.get(ra_col))  if ra_col  else None
        kic = _range_midpoint(row.get(kic_col)) if kic_col else None

        if uts is None and ys is None:
            continue

        ht_val   = str(row.get(ht_col, "A")).strip() if ht_col else "A"
        steel_id = _det_id("v4mar_age", grade)
        proc_id  = _det_id("proc_v4mar_age", grade, ht_val)

        records.append({
            "steel": {
                "steel_id":     steel_id,
                "grade":        grade,
                "steel_family": "maraging",
                "source_id":    SOURCE_ID,
                "notes":        f"ASM Vol.4 Table 6. {grade} age-hardened. HT code: {ht_val}.",
            },
            "composition": None,
            "processing": [{
                "processing_id":      proc_id,
                "steel_id":           steel_id,
                "route_type":         "other",
                "austenitize_temp_C": 815.0,
                "quench_medium":      "air",
                "notes":              f"Solution anneal 815\xb0C/1h/AC, then age (HT={ht_val})",
            }],
            "properties": [{
                "property_id":                    _det_id("prop_v4mar_age", steel_id, ht_val),
                "steel_id":                       steel_id,
                "processing_id":                  proc_id,
                "uts_MPa":                        uts,
                "yield_strength_MPa":             ys,
                "elongation_pct":                 el,
                "reduction_area_pct":             ra,
                "fracture_tough_KIC_MPa_sqrt_m":  kic,
                "test_temp_C":                    25.0,
            }],
            "microstructure": [],
        })
    logger.info("Maraging age-hardened: %d records", len(records))
    return records


def _parse_maraging_solution_annealed(path: Path) -> List[Dict]:
    """Maraging steels: range of properties in solution-annealed condition."""
    if not path.exists():
        logger.warning("Missing: %s", path.name)
        return []
    df = _valid_rows(_load_csv(path))

    grade_col = _col(df, "alloy") or _col(df, "grade")
    uts_col   = _col(df, "tensile strength", "mpa")
    ys_col    = _col(df, "yield strength", "mpa")
    el_col    = _col(df, "elongation")
    ra_col    = _col(df, "reduction")
    hrc_col   = _col(df, "hardness", "hrc")

    records: List[Dict] = []
    for _, row in df.iterrows():
        grade = str(row.get(grade_col, "")).strip() if grade_col else ""
        if not grade:
            continue

        uts = _range_midpoint(row.get(uts_col)) if uts_col else None
        ys  = _range_midpoint(row.get(ys_col))  if ys_col  else None
        el  = _range_midpoint(row.get(el_col))  if el_col  else None
        ra  = _range_midpoint(row.get(ra_col))  if ra_col  else None
        hrc = _range_midpoint(row.get(hrc_col)) if hrc_col else None

        if uts is None and ys is None:
            continue

        steel_id = _det_id("v4mar_sa", grade)
        proc_id  = _det_id("proc_v4mar_sa", grade)

        records.append({
            "steel": {
                "steel_id":     steel_id,
                "grade":        grade,
                "steel_family": "maraging",
                "source_id":    SOURCE_ID,
                "notes":        f"ASM Vol.4. {grade} solution-annealed [815\xb0C/1h/AC].",
            },
            "composition": None,
            "processing": [{
                "processing_id":      proc_id,
                "steel_id":           steel_id,
                "route_type":         "anneal",
                "austenitize_temp_C": 815.0,
                "quench_medium":      "air",
                "notes":              "Solution anneal: 815\xb0C, 1 h, air cooled",
            }],
            "properties": [{
                "property_id":        _det_id("prop_v4mar_sa", steel_id),
                "steel_id":           steel_id,
                "processing_id":      proc_id,
                "uts_MPa":            uts,
                "yield_strength_MPa": ys,
                "elongation_pct":     el,
                "reduction_area_pct": ra,
                "hardness_HRC":       hrc if (hrc is not None and hrc <= 70) else None,
                "test_temp_C":        25.0,
            }],
            "microstructure": [],
        })
    logger.info("Maraging solution-annealed: %d records", len(records))
    return records


def _parse_maraging_aging_hrc(path: Path) -> List[Dict]:
    """Maraging aging treatments and resultant HRC hardness."""
    if not path.exists():
        logger.warning("Missing: %s", path.name)
        return []
    df = _valid_rows(_load_csv(path))

    grade_col = _col(df, "grade")
    aging_col = _col(df, "aging treatment", "\xb0c") or _col(df, "aging", "c")
    hrc_col   = _col(df, "hardness, hrc") or _col(df, "nominal hardness")

    records: List[Dict] = []
    for _, row in df.iterrows():
        grade   = str(row.get(grade_col, "")).strip() if grade_col else ""
        aging_c = _range_midpoint(row.get(aging_col)) if aging_col else None
        hrc_raw = _range_midpoint(row.get(hrc_col)) if hrc_col else None

        if not grade or hrc_raw is None:
            continue
        hrc = hrc_raw if hrc_raw <= 70 else None
        if hrc is None:
            continue

        steel_id = _det_id("v4mar_hrc", grade)
        proc_id  = _det_id("proc_v4mar_hrc", grade, str(aging_c))

        proc: Dict[str, Any] = {
            "processing_id":      proc_id,
            "steel_id":           steel_id,
            "route_type":         "other",
            "austenitize_temp_C": 815.0,
            "quench_medium":      "air",
        }
        if aging_c is not None and 100.0 <= aging_c <= 800.0:
            proc["temper_temp_C"] = aging_c

        records.append({
            "steel": {
                "steel_id":     steel_id,
                "grade":        grade,
                "steel_family": "maraging",
                "source_id":    SOURCE_ID,
                "notes":        f"ASM Vol.4 Table 5. {grade} aging HRC table.",
            },
            "composition": None,
            "processing": [proc],
            "properties": [{
                "property_id":   _det_id("prop_v4mar_hrc", steel_id, str(aging_c)),
                "steel_id":      steel_id,
                "processing_id": proc_id,
                "hardness_HRC":  hrc,
                "test_temp_C":   25.0,
            }],
            "microstructure": [],
        })
    logger.info("Maraging aging HRC: %d records", len(records))
    return records


_HRC_TEMPER_TEMPS = [205, 260, 315, 370, 425, 480, 540, 595, 650]


def _parse_hardness_tempering(path: Path) -> List[Dict]:
    """Wide-format HRC vs temper temperature table -> one bundle per (grade, temper_temp)."""
    if not path.exists():
        logger.warning("Missing: %s", path.name)
        return []
    df = _valid_rows(_load_csv(path))

    grade_col = _col(df, "grade")
    ht_col    = _col(df, "heat treatment")

    # Map each temper temperature to its column
    hrc_cols: Dict[int, str] = {}
    for t in _HRC_TEMPER_TEMPS:
        col = _col(df, f"{t} \xb0c")
        if col:
            hrc_cols[t] = col

    if not hrc_cols:
        logger.warning("hardness_tempering: no HRC columns found")
        return []

    records: List[Dict] = []
    for _, row in df.iterrows():
        grade = str(row.get(grade_col, "")).strip() if grade_col else ""
        ht    = str(row.get(ht_col,    "")).strip() if ht_col    else ""
        if not grade:
            continue

        # Extract austenitize temp from heat treatment description
        aus_c: Optional[float] = None
        aus_m = re.search(
            r"(?:quench(?:ed)?) from\s+([\d]+)(?:\s*[-–]\s*([\d]+))?\s*\xb0C",
            ht, re.IGNORECASE,
        )
        if aus_m:
            lo = float(aus_m.group(1))
            hi = float(aus_m.group(2)) if aus_m.group(2) else lo
            aus_c = (lo + hi) / 2

        qm     = "water" if "water" in ht.lower() else "oil"
        family = _sae_to_family(grade)

        for temper_c, col in hrc_cols.items():
            raw = str(row.get(col, "")).strip()
            if not raw or raw in ("", "nan"):
                continue
            has_footnote = bool(re.search(r"\([a-z]\)$", raw.strip()))
            hrc = _range_midpoint(raw)
            if hrc is None or hrc > 70:
                continue  # HRB or invalid value

            steel_id = _det_id("v4hrc", grade, str(aus_c), qm)
            proc_id  = _det_id("proc_v4hrc", steel_id, str(temper_c))

            proc: Dict[str, Any] = {
                "processing_id": proc_id,
                "steel_id":      steel_id,
                "route_type":    "QT",
                "quench_medium": qm,
                "temper_temp_C": float(temper_c),
            }
            if aus_c is not None and 600.0 <= aus_c <= 1400.0:
                proc["austenitize_temp_C"] = aus_c

            notes = "Footnote on source value — may be HRB; treat as approximate" if has_footnote else None

            records.append({
                "steel": {
                    "steel_id":     steel_id,
                    "grade":        f"AISI {grade}",
                    "steel_family": family,
                    "source_id":    SOURCE_ID,
                    "notes":        f"ASM Vol.4 Table 1 hardness-tempering. {grade}.",
                },
                "composition": None,
                "processing": [proc],
                "properties": [{
                    "property_id":   _det_id("prop_v4hrc", steel_id, str(temper_c)),
                    "steel_id":      steel_id,
                    "processing_id": proc_id,
                    "hardness_HRC":  hrc,
                    "test_temp_C":   25.0,
                    "notes":         notes,
                }],
                "microstructure": [],
            })
    records = _group_by_steel(records)
    logger.info("Hardness tempering: %d records", len(records))
    return records


def _parse_tool_steel_ht(paths: List[Path]) -> List[Dict]:
    """Tool steel hardening and tempering parameters -> processing-only bundles."""
    records: List[Dict] = []
    for path in paths:
        if not path.exists():
            logger.warning("Missing: %s", path.name)
            continue
        df = _valid_rows(_load_csv(path))

        grade_col  = _col(df, "steel type") or _col(df, "steel")
        aus_col    = _col(df, "hardening temperature", "\xb0c")
        qm_col     = _col(df, "quenching medium")
        temper_col = _col(df, "tempering temperature", "\xb0c")

        for _, row in df.iterrows():
            grade = str(row.get(grade_col, "")).strip() if grade_col else ""
            if not grade:
                continue

            aus_c    = _range_midpoint(str(row.get(aus_col, ""))) if aus_col else None
            temper_c = _range_midpoint(str(row.get(temper_col, ""))) if temper_col else None

            qm_raw = str(row.get(qm_col, "")).lower() if qm_col else ""
            if "salt" in qm_raw:
                qm: str = "salt_bath"
            elif "air" in qm_raw:
                qm = "air"
            elif "oil" in qm_raw:
                qm = "oil"
            else:
                qm = "other"

            steel_id = _det_id("v4tool", grade, str(aus_c), qm)
            proc_id  = _det_id("proc_v4tool", steel_id, str(temper_c))

            proc: Dict[str, Any] = {
                "processing_id": proc_id,
                "steel_id":      steel_id,
                "route_type":    "QT",
                "quench_medium": qm,
            }
            if aus_c is not None and 600.0 <= aus_c <= 1400.0:
                proc["austenitize_temp_C"] = aus_c
            if temper_c is not None and 100.0 <= temper_c <= 800.0:
                proc["temper_temp_C"] = temper_c

            records.append({
                "steel": {
                    "steel_id":     steel_id,
                    "grade":        grade,
                    "steel_family": "tool",
                    "source_id":    SOURCE_ID,
                    "notes":        f"ASM Vol.4 tool steel HT table. {grade}.",
                },
                "composition":    None,
                "processing":     [proc],
                "properties":     [],
                "microstructure": [],
            })
    records = _group_by_steel(records)
    logger.info("Tool steel HT: %d records", len(records))
    return records


def _parse_austenitizing_temps(path: Path) -> List[Dict]:
    """Austenitizing and martempering temperatures -> processing-only bundles."""
    if not path.exists():
        logger.warning("Missing: %s", path.name)
        return []
    df = _valid_rows(_load_csv(path))

    grade_col = _col(df, "grade")
    aus_col   = _col(df, "austenitizing temperature", "\xb0c")

    records: List[Dict] = []
    for _, row in df.iterrows():
        grade = str(row.get(grade_col, "")).strip() if grade_col else ""
        aus_c = _range_midpoint(str(row.get(aus_col, ""))) if aus_col else None
        if not grade or aus_c is None:
            continue

        family   = _sae_to_family(grade)
        steel_id = _det_id("v4aus", grade, str(aus_c))
        proc_id  = _det_id("proc_v4aus", steel_id)

        proc: Dict[str, Any] = {
            "processing_id": proc_id,
            "steel_id":      steel_id,
            "route_type":    "QT",
            "quench_medium": "oil",
        }
        if 600.0 <= aus_c <= 1400.0:
            proc["austenitize_temp_C"] = aus_c

        records.append({
            "steel": {
                "steel_id":     steel_id,
                "grade":        grade,
                "steel_family": family,
                "source_id":    SOURCE_ID,
                "notes":        f"ASM Vol.4 austenitizing table. {grade}, aus={aus_c}\xb0C.",
            },
            "composition":    None,
            "processing":     [proc],
            "properties":     [],
            "microstructure": [],
        })
    logger.info("Austenitizing temps: %d records", len(records))
    return records


def _parse_4340_kic(path: Path) -> List[Dict]:
    """4340 fracture toughness: HB + estimated UTS + Charpy + KIC."""
    if not path.exists():
        logger.warning("Missing: %s", path.name)
        return []
    df = _valid_rows(_load_csv(path))

    hb_col     = _col(df, "hardness, hb")
    uts_col    = _col(df, "tensile strength", "mpa")
    charpy_col = _col(df, "charpy", "j")
    kic_col    = _col(df, "fracture toughness", "mpa") or _col(df, "plane-strain", "mpa")

    records: List[Dict] = []
    for _, row in df.iterrows():
        kic = _safe_float(row.get(kic_col)) if kic_col else None
        if kic is None:
            continue

        hb     = _safe_float(row.get(hb_col))    if hb_col     else None
        uts    = _safe_float(row.get(uts_col))    if uts_col    else None
        charpy = _safe_float(row.get(charpy_col)) if charpy_col else None

        steel_id = _det_id("v4_4340_kic", str(hb))
        proc_id  = _det_id("proc_v4_4340_kic", str(hb))

        records.append({
            "steel": {
                "steel_id":     steel_id,
                "grade":        "4340",
                "steel_family": "low-alloy",
                "source_id":    SOURCE_ID,
                "notes":        f"ASM Vol.4 Table 10. 4340 KIC at HB={hb}. UTS estimated from hardness.",
            },
            "composition": None,
            "processing": [{
                "processing_id":      proc_id,
                "steel_id":           steel_id,
                "route_type":         "QT",
                "austenitize_temp_C": 845.0,
                "quench_medium":      "oil",
            }],
            "properties": [{
                "property_id":                    _det_id("prop_v4_4340_kic", steel_id),
                "steel_id":                       steel_id,
                "processing_id":                  proc_id,
                "uts_MPa":                        uts,
                "hardness_HB":                    hb,
                "charpy_J":                       charpy,
                "fracture_tough_KIC_MPa_sqrt_m":  kic,
                "test_temp_C":                    25.0,
                "notes":                          "UTS estimated from hardness per ASM table",
            }],
            "microstructure": [],
        })
    logger.info("4340 KIC: %d records", len(records))
    return records


def _parse_d6ac_kic(paths: List[Path]) -> List[Dict]:
    """D6AC fracture toughness (Table 13 + Table 16): UTS/YS/elongation/RA + KIC."""
    records: List[Dict] = []
    for path in paths:
        if not path.exists():
            logger.warning("Missing: %s", path.name)
            continue
        df = _valid_rows(_load_csv(path))

        uts_col = _col(df, "tensile strength", "mpa")
        ys_col  = _col(df, "yield strength", "mpa")
        el_col  = _col(df, "elongation")
        ra_col  = _col(df, "reduction")
        # Table 16: "average plane-strain fracture toughness, KIC (MPa m0.5)"
        # Table 13: "fracture toughness (MPa m0.5)"
        kic_col = _col(df, "average", "mpa") or _col(df, "fracture toughness", "mpa")

        for _, row in df.iterrows():
            kic = _range_midpoint(row.get(kic_col)) if kic_col else None
            if kic is None:
                continue

            uts = _range_midpoint(row.get(uts_col)) if uts_col else None
            ys  = _range_midpoint(row.get(ys_col))  if ys_col  else None
            el  = _range_midpoint(row.get(el_col))  if el_col  else None
            ra  = _range_midpoint(row.get(ra_col))  if ra_col  else None

            steel_id = _det_id("v4_d6ac_kic", path.stem, str(uts), str(kic))
            proc_id  = _det_id("proc_v4_d6ac_kic", steel_id)

            records.append({
                "steel": {
                    "steel_id":     steel_id,
                    "grade":        "D6AC",
                    "steel_family": "low-alloy",
                    "source_id":    SOURCE_ID,
                    "notes":        f"ASM Vol.4. D6AC fracture toughness. Source: {path.stem}.",
                },
                "composition": None,
                "processing": [{
                    "processing_id":      proc_id,
                    "steel_id":           steel_id,
                    "route_type":         "QT",
                    "austenitize_temp_C": 925.0,
                    "quench_medium":      "oil",
                }],
                "properties": [{
                    "property_id":                    _det_id("prop_v4_d6ac_kic", steel_id),
                    "steel_id":                       steel_id,
                    "processing_id":                  proc_id,
                    "uts_MPa":                        uts,
                    "yield_strength_MPa":             ys,
                    "elongation_pct":                 el,
                    "reduction_area_pct":             ra,
                    "fracture_tough_KIC_MPa_sqrt_m":  kic,
                    "test_temp_C":                    25.0,
                }],
                "microstructure": [],
            })
    logger.info("D6AC KIC: %d records", len(records))
    return records


def _parse_martensitic_stainless(paths: List[Path]) -> List[Dict]:
    """Vol.1 Table 11 (parts 1+2): minimum properties of martensitic stainless steels."""
    records: List[Dict] = []
    for path in paths:
        if not path.exists():
            logger.warning("Missing: %s", path.name)
            continue
        df = _valid_rows(_load_csv(path))

        type_col = _col(df, "type")
        cond_col = _col(df, "condition")
        uts_col  = _col(df, "tensile", "mpa")
        ys_col   = _col(df, "yield", "mpa") or _col(df, "0.2%", "mpa")
        el_col   = _col(df, "elongation")
        ra_col   = _col(df, "reduction")

        for _, row in df.iterrows():
            grade = str(row.get(type_col, "")).strip() if type_col else ""
            if not grade:
                continue
            cond = str(row.get(cond_col, "")).strip() if cond_col else ""

            uts = _safe_float(row.get(uts_col)) if uts_col else None
            ys  = _safe_float(row.get(ys_col))  if ys_col  else None
            el  = _safe_float(row.get(el_col))  if el_col  else None
            ra  = _safe_float(row.get(ra_col))  if ra_col  else None
            uts, ys = _fix_uts_ys(uts, ys)

            if uts is None and ys is None:
                continue

            route_type = _condition_to_route(cond)
            qm: Optional[str] = "oil" if route_type == "QT" else None

            steel_id = _det_id("v1_mss", grade, cond)
            proc_id  = _det_id("proc_v1_mss", steel_id)

            proc: Dict[str, Any] = {
                "processing_id": proc_id,
                "steel_id":      steel_id,
                "route_type":    route_type,
            }
            if qm:
                proc["quench_medium"] = qm

            records.append({
                "steel": {
                    "steel_id":     steel_id,
                    "grade":        f"Type {grade}",
                    "steel_family": "stainless",
                    "source_id":    SOURCE_ID_V1,
                    "notes":        f"ASM Vol.1 Table 11. Martensitic stainless type {grade}, {cond}.",
                },
                "composition": None,
                "processing":  [proc],
                "properties": [{
                    "property_id":        _det_id("prop_v1_mss", steel_id),
                    "steel_id":           steel_id,
                    "processing_id":      proc_id,
                    "uts_MPa":            uts,
                    "yield_strength_MPa": ys,
                    "elongation_pct":     el,
                    "reduction_area_pct": ra,
                    "test_temp_C":        25.0,
                    "notes":              "Minimum specification values (not typical measurements)",
                }],
                "microstructure": [],
            })
    records = _group_by_steel(records)
    logger.info("Martensitic stainless: %d records", len(records))
    return records


def _parse_ls_tool_steels(path: Path) -> List[Dict]:
    """Vol.1 Table 7: nominal room-temperature properties of L and S group tool steels."""
    if not path.exists():
        logger.warning("Missing: %s", path.name)
        return []
    df = _valid_rows(_load_csv(path))

    type_col   = _col(df, "type")
    cond_col   = _col(df, "condition")
    uts_col    = _col(df, "tensile", "mpa")
    ys_col     = _col(df, "yield", "mpa") or _col(df, "0.2%", "mpa")
    el_col     = _col(df, "elongation")
    ra_col     = _col(df, "reduction")
    hrc_col    = _col(df, "hardness, hrc")
    impact_col = _col(df, "impact", "j")

    records: List[Dict] = []
    for _, row in df.iterrows():
        grade = str(row.get(type_col, "")).strip() if type_col else ""
        if not grade:
            continue
        cond = str(row.get(cond_col, "")).strip() if cond_col else ""

        uts  = _safe_float(row.get(uts_col))  if uts_col  else None
        ys   = _safe_float(row.get(ys_col))   if ys_col   else None
        el   = _safe_float(row.get(el_col))   if el_col   else None
        ra   = _safe_float(row.get(ra_col))   if ra_col   else None
        uts, ys = _fix_uts_ys(uts, ys)

        hrc_raw = str(row.get(hrc_col, "")).strip() if hrc_col else ""
        hrc: Optional[float] = None
        if hrc_raw and "hrb" not in hrc_raw.lower():
            m = re.match(r"^([\d.]+)", hrc_raw)
            if m:
                v = _safe_float(m.group(1))
                hrc = v if (v is not None and v <= 70) else None

        impact = _safe_float(row.get(impact_col)) if impact_col else None

        if uts is None and ys is None and hrc is None:
            continue

        route_type = _condition_to_route(cond)
        qm_str: Optional[str] = None
        aus_c: Optional[float] = None
        temper_c: Optional[float] = None

        if route_type == "QT":
            qm_str = "oil" if "oil" in cond.lower() else "other"
            aus_m = re.search(r"from\s+([\d]+)\s*\xb0C", cond, re.IGNORECASE)
            if aus_m:
                aus_c = float(aus_m.group(1))
            t_m = re.search(r"temper(?:ed)?\s+at[:\s]*([\d]+)\s*\xb0C", cond, re.IGNORECASE)
            if t_m:
                t_val = float(t_m.group(1))
                temper_c = t_val if 100.0 <= t_val <= 800.0 else None

        steel_id = _det_id("v1_lst", grade, cond)
        proc_id  = _det_id("proc_v1_lst", steel_id)

        proc: Dict[str, Any] = {
            "processing_id": proc_id,
            "steel_id":      steel_id,
            "route_type":    route_type,
        }
        if qm_str:
            proc["quench_medium"] = qm_str
        if aus_c is not None and 600.0 <= aus_c <= 1400.0:
            proc["austenitize_temp_C"] = aus_c
        if temper_c is not None:
            proc["temper_temp_C"] = temper_c

        prop: Dict[str, Any] = {
            "property_id":        _det_id("prop_v1_lst", steel_id),
            "steel_id":           steel_id,
            "processing_id":      proc_id,
            "uts_MPa":            uts,
            "yield_strength_MPa": ys,
            "elongation_pct":     el,
            "reduction_area_pct": ra,
            "hardness_HRC":       hrc,
            "test_temp_C":        25.0,
        }
        if impact is not None:
            prop["charpy_J"] = impact
            prop["notes"] = "Impact energy type not specified in source (Izod or Charpy)"

        records.append({
            "steel": {
                "steel_id":     steel_id,
                "grade":        f"AISI {grade}",
                "steel_family": "tool",
                "source_id":    SOURCE_ID_V1,
                "notes":        f"ASM Vol.1 Table 7. L/S tool steel {grade}, {cond}.",
            },
            "composition":    None,
            "processing":     [proc],
            "properties":     [prop],
            "microstructure": [],
        })
    logger.info("L/S tool steels: %d records", len(records))
    return records


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_asm_vol4(base_dir: Optional[Path] = None) -> List[Dict]:
    """
    Parse all ASM Vol.4 tables and the new Vol.1 stainless/tool tables.

    Returns:
        List of bundle dicts compatible with ingest_bundles().

    Example:
        from data.parsers.asm_vol4 import parse_asm_vol4, SOURCE_ID
        from data.ingest import ensure_source, ingest_bundles

        ensure_source(source_id=SOURCE_ID, source_type="literature", reliability=4,
                      notes="ASM Handbook Vol.4: Heat Treating. ASM International, 1991.")
        records = parse_asm_vol4()
        result = ingest_bundles(records)
        print(result)
    """
    d = base_dir or BASE_DIR
    records: List[Dict] = []

    # HR / normalize / anneal properties (Table 3, parts 1 + 2)
    records += _parse_hr_norm_anneal([
        d / "vol4_properties_selected_carbon_and_alloy_steels_hot_rolled_normalized_and_annealed.csv",
        d / "vol4_properties_selected_carbon_and_alloy_steels_hot_rolled_normalized_and_annealed_part2.csv",
    ])

    # QT property tables
    records += _parse_qt_table(
        d / "vol4_typical_mechanical_properties_of_4340_steel.csv",
        grade="4340", aus_temp_c=845.0, quench_medium="oil",
        family="low-alloy", tag="4340",
    )
    records += _parse_qt_table(
        d / "vol4_typical_mechanical_properties_of_heat_treated_4130_steel.csv",
        grade="4130", aus_temp_c=860.0, quench_medium="water",
        family="low-alloy", tag="4130", condition_col="condition",
    )
    records += _parse_qt_table(
        d / "vol4_typical_mechanical_properties_of_heat_treated_4140_steel.csv",
        grade="4140", aus_temp_c=845.0, quench_medium="oil",
        family="low-alloy", tag="4140",
    )
    records += _parse_qt_table(
        d / "vol4_typical_room_temperature_mechanical_properties_of_8640_steel.csv",
        grade="8640", aus_temp_c=845.0, quench_medium="oil",
        family="low-alloy", tag="8640",
    )
    records += _parse_qt_table(
        d / "vol4_typical_room_temperature_tensile_properties_of_heat_treated_6150_steel.csv",
        grade="6150", aus_temp_c=870.0, quench_medium="oil",
        family="low-alloy", tag="6150",
    )
    records += _parse_qt_table(
        d / "vol4_typical_mechanical_properties_d6a_steel_bar.csv",
        grade="D6A", aus_temp_c=925.0, quench_medium="oil",
        family="low-alloy", tag="D6A", charpy=True,
    )
    records += _parse_qt_table(
        d / "vol4_typical_mechanical_properties_300m_steel.csv",
        grade="300M", aus_temp_c=870.0, quench_medium="oil",
        family="low-alloy", tag="300M", charpy=True,
    )
    records += _parse_qt_table(
        d / "vol4_typical_longitudinal_mechanical_properties_h11_mod_steel.csv",
        grade="H11 Mod", aus_temp_c=1010.0, quench_medium="oil",
        family="tool", tag="H11Mod", charpy=True,
    )
    records += _parse_qt_table(
        d / "vol4_typical_longitudinal_mechanical_properties_h13_steel.csv",
        grade="H13", aus_temp_c=1010.0, quench_medium="air",
        family="tool", tag="H13", charpy=True,
    )

    # Maraging steels
    records += _parse_maraging_age_hardened(
        d / "vol4_typical_mechanical_properties_18ni_maraging_steels_age_hardened.csv"
    )
    records += _parse_maraging_solution_annealed(
        d / "vol4_typical_mechanical_properties_18ni_maraging_steels_solution_annealed.csv"
    )
    records += _parse_maraging_aging_hrc(
        d / "vol4_hardening_aging_treatments_hardnesses_maraging_steels.csv"
    )

    # Wide hardness vs tempering temperature table
    records += _parse_hardness_tempering(
        d / "vol4_typical_hardnesses_carbon_and_alloy_steels_after_tempering.csv"
    )

    # Processing-only tables
    records += _parse_tool_steel_ht([
        d / "vol4_hardening_and_tempering_of_tool_steels.csv",
        d / "vol4_hardening_and_tempering_of_tool_steels_part2.csv",
    ])
    records += _parse_austenitizing_temps(
        d / "vol4_typical_austenitizing_and_martempering_temperatures.csv"
    )

    # Fracture toughness (KIC)
    records += _parse_4340_kic(
        d / "vol4_notch_toughness_and_fracture_toughness_4340_steel_tempered_to_different_hardnesses.csv"
    )
    records += _parse_d6ac_kic([
        d / "vol4_typical_fracture_toughness_d6ac_eaf_var_or_eaf_aod_var.csv",
        d / "vol4_plane_strain_fracture_toughness_of_d_6ac_in_the_long_transverse_direction.csv",
    ])

    # Vol.1 new tables (ingested under src_asm_vol1)
    records += _parse_martensitic_stainless([
        d / "vol1_minimum_mechanical_properties_martensitic_stainless_steels.csv",
        d / "vol1_minimum_mechanical_properties_martensitic_stainless_steels_part2.csv",
    ])
    records += _parse_ls_tool_steels(
        d / "vol1_nominal_mechanical_properties_group_l_s_tool_steels.csv"
    )

    logger.info("ASM Vol.4 parse complete: %d total records", len(records))
    return records
