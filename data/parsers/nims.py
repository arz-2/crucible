"""
NIMS MatNavi MSDB parser — Structural Steels Mechanical Properties Database.

HOW TO GET THE DATA
-------------------
1. Register (free) at https://mits.nims.go.jp
2. Navigate to MSDB → Structural Steels
3. Run a search with no filters to export the full dataset
4. Download as Excel (.xlsx) or CSV

IMPORTANT: Verify column names before running.
-------------------
NIMS has updated their export format across versions. The column name map in
`COLUMN_MAP` below was constructed from known MSDB exports, but the exact
strings in YOUR downloaded file may differ — especially for:
  - Heat treatment columns (sometimes Japanese-English mixed)
  - Property units (sometimes MPa, sometimes kgf/mm²)

Run `NIMSParser.inspect(path)` on your downloaded file first. It will print
the actual headers and a sample row so you can update the map if needed.

UNIT WARNINGS
-------------------
Older NIMS exports may use kgf/mm² instead of MPa for strength values.
1 kgf/mm² = 9.80665 MPa.
The parser checks for this and converts automatically if it can detect the unit,
but set `force_kgf_conversion=True` if you know the file uses kgf/mm².

NIMS database URL: https://mits.nims.go.jp/en/
Relevant sub-database: MSDB (Structural Steels)
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

SOURCE_ID = "src_nims_msdb"  # Used as the source_id for all NIMS records

# ---------------------------------------------------------------------------
# Column name map: NIMS export header → our schema field
#
# VERIFY THESE AGAINST YOUR ACTUAL DOWNLOAD.
# Run NIMSParser.inspect(path) to see what your file actually contains.
# Keys are lowercase-stripped versions of NIMS column headers.
# ---------------------------------------------------------------------------

# Composition columns (wt%)
COMPOSITION_MAP: Dict[str, str] = {
    "c":          "C",
    "carbon":     "C",
    "si":         "Si",
    "silicon":    "Si",
    "mn":         "Mn",
    "manganese":  "Mn",
    "p":          "P",
    "phosphorus": "P",
    "s":          "S",
    "sulfur":     "S",
    "ni":         "Ni",
    "nickel":     "Ni",
    "cr":         "Cr",
    "chromium":   "Cr",
    "mo":         "Mo",
    "molybdenum": "Mo",
    "cu":         "Cu",
    "copper":     "Cu",
    "v":          "V",
    "vanadium":   "V",
    "nb":         "Nb",
    "niobium":    "Nb",
    "ti":         "Ti",
    "titanium":   "Ti",
    "al":         "Al",
    "aluminum":   "Al",
    "aluminium":  "Al",
    "b":          "B",
    "boron":      "B",
    "n":          "N",
    "nitrogen":   "N",
    "w":          "W",
    "tungsten":   "W",
    "co":         "Co",
    "cobalt":     "Co",
}

# Processing columns — VERIFY THESE
PROCESSING_MAP: Dict[str, str] = {
    # Austenitizing
    "austenitizing temperature":         "austenitize_temp_C",
    "austenitizing temp.":               "austenitize_temp_C",
    "solution treatment temperature":    "austenitize_temp_C",
    "normalizing temperature":           "austenitize_temp_C",  # for NT route
    "quenching temperature":             "austenitize_temp_C",
    "heating temperature":               "austenitize_temp_C",
    "austenitizing time":                "austenitize_time_min",
    "austenitizing time (min)":          "austenitize_time_min",
    # Quench
    "quenching method":                  "quench_medium",
    "quench medium":                     "quench_medium",
    "cooling method":                    "quench_medium",
    # Temper
    "tempering temperature":             "temper_temp_C",
    "tempering temp.":                   "temper_temp_C",
    "aging temperature":                 "temper_temp_C",
    "tempering time":                    "temper_time_min",
    "tempering time (min)":              "temper_time_min",
}

# Property columns — VERIFY THESE
# Note: NIMS sometimes exports strength in kgf/mm² — see force_kgf_conversion
PROPERTY_MAP: Dict[str, str] = {
    "0.2% proof stress":                 "yield_strength_MPa",
    "0.2% proof strength":               "yield_strength_MPa",
    "yield strength":                    "yield_strength_MPa",
    "lower yield strength":              "yield_strength_MPa",
    "tensile strength":                  "uts_MPa",
    "ultimate tensile strength":         "uts_MPa",
    "elongation":                        "elongation_pct",
    "elongation (%)":                    "elongation_pct",
    "reduction of area":                 "reduction_area_pct",
    "reduction of area (%)":             "reduction_area_pct",
    "vickers hardness":                  "hardness_HV",
    "hardness (hv)":                     "hardness_HV",
    "hv":                                "hardness_HV",
    "rockwell hardness (hrc)":           "hardness_HRC",
    "hrc":                               "hardness_HRC",
    "brinell hardness":                  "hardness_HB",
    "hb":                                "hardness_HB",
    "charpy impact energy":              "charpy_J",
    "charpy absorbed energy":            "charpy_J",
    "charpy impact value":               "charpy_J",
    "charpy test temperature":           "charpy_test_temp_C",
    "fracture toughness (kic)":          "fracture_tough_KIC_MPa_sqrt_m",
    "kic":                               "fracture_tough_KIC_MPa_sqrt_m",
}

# NIMS quench medium strings → our enum values
QUENCH_MEDIUM_MAP: Dict[str, str] = {
    "water":        "water",
    "water quench": "water",
    "wq":           "water",
    "oil":          "oil",
    "oil quench":   "oil",
    "oq":           "oil",
    "air":          "air",
    "air cool":     "air",
    "ac":           "air",
    "polymer":      "polymer",
    "press":        "press_quench",
    "salt":         "salt_bath",
    "salt bath":    "salt_bath",
}

# NIMS grade → steel_family heuristic
# Extend this as you encounter new grades in the data
FAMILY_PATTERNS: List[Tuple[str, str]] = [
    (r"SUS|SS\d{3}|304|316|410|430",   "stainless"),
    (r"SKD|SKH|SKS",                    "tool"),
    (r"SM\d|SS\d|SB\d|SPV",            "carbon"),
    (r"SCM|SNCM|SNC|SCr|SMn",          "low-alloy"),
    (r"SA\d|SMA",                       "HSLA"),
    (r"AISI\s?4\d{3}|4\d{3}",          "low-alloy"),
    (r"AISI\s?[12]\d{3}",              "carbon"),
]


def _normalize_col(col: str) -> str:
    """Lowercase and strip a column header for map lookup."""
    return col.strip().lower()


def _infer_family(grade: Optional[str]) -> str:
    if not grade:
        return "other"
    for pattern, family in FAMILY_PATTERNS:
        if re.search(pattern, str(grade), re.IGNORECASE):
            return family
    return "other"


def _infer_route(row: pd.Series, col_map: Dict[str, str]) -> str:
    """
    Best-effort route_type inference from available processing columns.
    NIMS doesn't always have a dedicated 'route' column.
    """
    has_temper = "temper_temp_C" in col_map.values() and pd.notna(
        row.get(next((k for k, v in col_map.items() if v == "temper_temp_C"), None), None)
    )
    quench_col = next((k for k, v in col_map.items() if v == "quench_medium"), None)
    quench_val = str(row.get(quench_col, "")).lower() if quench_col else ""

    if "air" in quench_val and has_temper:
        return "NT"
    if quench_val and has_temper:
        return "QT"
    if quench_val:
        return "QT"
    if has_temper:
        return "NT"
    return "other"


class NIMSParser:
    """
    Parser for NIMS MatNavi MSDB Excel/CSV exports.

    Args:
        force_kgf_conversion: Convert strength values from kgf/mm² to MPa.
                              Set True if you know the file uses kgf/mm².
        header_rows:          Number of header rows to skip. NIMS files often
                              have 1–3 metadata rows before the column headers.
                              Use inspect() to determine the right value.
        sheet_name:           Excel sheet name or index (ignored for CSV).
    """

    KGF_TO_MPA = 9.80665

    def __init__(
        self,
        force_kgf_conversion: bool = False,
        header_rows: int = 0,
        sheet_name: int | str = 0,
    ):
        self.force_kgf_conversion = force_kgf_conversion
        self.header_rows = header_rows
        self.sheet_name = sheet_name

    @staticmethod
    def inspect(path: str | Path) -> None:
        """
        Print the actual column headers and first data row of a NIMS file.
        Run this on your downloaded file BEFORE parsing to verify column names.

        Usage:
            NIMSParser.inspect("my_nims_download.xlsx")
        """
        path = Path(path)
        if path.suffix in (".xlsx", ".xls"):
            df = pd.read_excel(path, nrows=5)
        else:
            df = pd.read_csv(path, nrows=5)

        print(f"\nFile: {path.name}")
        print(f"Shape (first 5 rows): {df.shape}")
        print(f"\nColumn headers ({len(df.columns)} total):")
        for i, col in enumerate(df.columns):
            print(f"  [{i:3d}] {col!r}")
        print(f"\nFirst data row:")
        if len(df) > 0:
            for col, val in df.iloc[0].items():
                print(f"  {col!r}: {val!r}")

    def _load_raw(self, path: Path) -> pd.DataFrame:
        if path.suffix in (".xlsx", ".xls"):
            df = pd.read_excel(
                path,
                sheet_name=self.sheet_name,
                skiprows=self.header_rows,
                header=0,
            )
        elif path.suffix == ".csv":
            df = pd.read_csv(path, skiprows=self.header_rows, header=0)
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}. Expected .xlsx, .xls, or .csv")
        logger.info(f"Loaded {len(df)} rows, {len(df.columns)} columns from {path.name}")
        return df

    def _build_col_map(self, df: pd.DataFrame) -> Dict[str, Dict[str, str]]:
        """
        Map actual DataFrame column names to schema field names.
        Returns three dicts: {df_col → schema_field} for composition, processing, properties.
        """
        comp_found: Dict[str, str] = {}
        proc_found: Dict[str, str] = {}
        prop_found: Dict[str, str] = {}

        for col in df.columns:
            norm = _normalize_col(str(col))
            if norm in COMPOSITION_MAP:
                comp_found[col] = COMPOSITION_MAP[norm]
            elif norm in PROCESSING_MAP:
                proc_found[col] = PROCESSING_MAP[norm]
            elif norm in PROPERTY_MAP:
                prop_found[col] = PROPERTY_MAP[norm]

        # Warn about unmapped columns (useful for updating the maps)
        all_mapped = set(comp_found) | set(proc_found) | set(prop_found)
        unmapped = [c for c in df.columns if c not in all_mapped]
        if unmapped:
            logger.warning(
                f"{len(unmapped)} columns not mapped to any schema field. "
                f"Check if any are relevant: {unmapped[:20]}"
            )

        return {"composition": comp_found, "processing": proc_found, "properties": prop_found}

    def _extract_grade(self, row: pd.Series) -> Optional[str]:
        """Look for a grade/designation column in the row."""
        grade_candidates = ["grade", "steel grade", "designation", "jis grade", "aisi", "material"]
        for col in row.index:
            if _normalize_col(str(col)) in grade_candidates:
                val = row[col]
                if pd.notna(val):
                    return str(val).strip()
        return None

    def _convert_units(self, val: Any, field: str) -> Optional[float]:
        """
        Convert a raw value to float, applying kgf→MPa if needed.
        Returns None if the value is missing or non-numeric.
        """
        if pd.isna(val) or val == "" or val is None:
            return None
        try:
            fval = float(val)
        except (TypeError, ValueError):
            logger.debug(f"Could not convert {val!r} to float for field {field!r}")
            return None

        strength_fields = {"yield_strength_MPa", "uts_MPa", "fatigue_limit_MPa",
                           "fracture_tough_KIC_MPa_sqrt_m"}
        if self.force_kgf_conversion and field in strength_fields:
            fval *= self.KGF_TO_MPA

        return fval

    def _map_quench_medium(self, raw: Any) -> Optional[str]:
        if pd.isna(raw) or raw is None:
            return None
        norm = str(raw).strip().lower()
        return QUENCH_MEDIUM_MAP.get(norm, "other")

    def parse(self, path: str | Path) -> List[Dict]:
        """
        Parse a NIMS MSDB export file into a list of raw dicts
        compatible with SteelIngestBundle.

        Returns:
            List of dicts, one per steel data point. Feed directly to ingest_bundles().

        Example:
            parser = NIMSParser()
            records = parser.parse("nims_steels.xlsx")
            from data.ingest import ingest_bundles
            result = ingest_bundles(records)
            print(result)
        """
        path = Path(path)
        df = self._load_raw(path)
        col_map = self._build_col_map(df)

        comp_map = col_map["composition"]
        proc_map = col_map["processing"]
        prop_map = col_map["properties"]

        if not comp_map:
            raise RuntimeError(
                "No composition columns found. Run NIMSParser.inspect() on your file "
                "and update COMPOSITION_MAP with the actual column headers."
            )
        if not prop_map:
            raise RuntimeError(
                "No property columns found. Run NIMSParser.inspect() on your file "
                "and update PROPERTY_MAP with the actual column headers."
            )

        records: List[Dict] = []

        for idx, row in df.iterrows():
            steel_id = f"nims_{uuid.uuid4().hex[:10]}"
            grade = self._extract_grade(row)
            steel_family = _infer_family(grade)

            # --- Composition ---
            comp_data: Dict[str, Any] = {"steel_id": steel_id}
            has_any_comp = False
            for col, field in comp_map.items():
                val = self._convert_units(row.get(col), field)
                comp_data[field] = val
                if val is not None:
                    has_any_comp = True

            if not has_any_comp:
                logger.warning(f"Row {idx}: all composition values null — skipping")
                continue

            # --- Processing ---
            proc_id = f"proc_{uuid.uuid4().hex[:10]}"
            proc_data: Dict[str, Any] = {
                "processing_id": proc_id,
                "steel_id": steel_id,
            }
            has_any_proc = False
            for col, field in proc_map.items():
                raw_val = row.get(col)
                if field == "quench_medium":
                    proc_data[field] = self._map_quench_medium(raw_val)
                else:
                    val = self._convert_units(raw_val, field)
                    proc_data[field] = val
                    if val is not None:
                        has_any_proc = True

            proc_data["route_type"] = _infer_route(row, {v: v for v in proc_map.values()})

            # --- Properties ---
            prop_id = f"prop_{uuid.uuid4().hex[:10]}"
            prop_data: Dict[str, Any] = {
                "property_id": prop_id,
                "steel_id": steel_id,
                "processing_id": proc_id if has_any_proc else None,
                "test_standard": "JIS",  # NIMS data is predominantly JIS
            }
            has_any_prop = False
            for col, field in prop_map.items():
                val = self._convert_units(row.get(col), field)
                prop_data[field] = val
                if val is not None:
                    has_any_prop = True

            if not has_any_prop:
                logger.warning(f"Row {idx}: all property values null — skipping")
                continue

            # --- Assemble bundle dict ---
            record: Dict = {
                "steel": {
                    "steel_id": steel_id,
                    "grade": grade,
                    "steel_family": steel_family,
                    "source_id": SOURCE_ID,
                    "notes": f"NIMS MSDB row {idx}",
                },
                "composition": comp_data,
                "processing": [proc_data] if has_any_proc else [],
                "properties": [prop_data],
                "microstructure": [],
            }
            records.append(record)

        logger.info(f"Parsed {len(records)} valid records from {path.name} ({len(df)} raw rows)")
        return records


def parse_nims_file(
    path: str | Path,
    force_kgf_conversion: bool = False,
    header_rows: int = 0,
) -> List[Dict]:
    """
    Convenience wrapper. Equivalent to NIMSParser(...).parse(path).

    Example:
        from data.parsers import parse_nims_file
        from data.ingest import ensure_source, ingest_bundles

        ensure_source(
            source_id="src_nims_msdb",
            source_type="NIMS",
            reliability=5,
            notes="NIMS MatNavi MSDB Structural Steels export"
        )
        records = parse_nims_file("nims_steels.xlsx")
        result = ingest_bundles(records)
        print(result)
    """
    parser = NIMSParser(
        force_kgf_conversion=force_kgf_conversion,
        header_rows=header_rows,
    )
    return parser.parse(path)
