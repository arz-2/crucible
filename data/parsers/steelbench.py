"""
SteelBench v1.0 parser — DOI: 10.5281/zenodo.18530558

Dataset: 1,360 records (core open version), 25 columns.
License: CC-BY 4.0 — no bulk download restrictions.
Source: Zenodo, direct CSV download via API.

DATA QUALITY NOTES (read before training)
------------------------------------------
Three distinct provenance tiers in this dataset — weight them accordingly:

  nims_measured (360 rows)     — NIMS laboratory measurements. Highest quality.
                                  Reliability: 5
  emk_spec_verified (753 rows) — EMK (German steelmaker) specification values,
                                  cross-verified. Specification values represent
                                  minima/typical, not exact heat measurements.
                                  Reliability: 4
  kaggle_measured (247 rows)   — Unclear provenance scraped from Kaggle.
                                  Treat as supplementary only.
                                  Reliability: 2

COVERAGE GAPS
------------------------------------------
- austenitize_T: 51% filled
- quench_medium: 47% filled (only 3 values: air, water, oil)
- temper_T:      29% filled
- Al, Cu:        low coverage
- No Nb, Ti, B, N, W, P, S columns at all
- hardness:      73% filled but units are AMBIGUOUS (likely HRB for
                 stainless, possibly HRC for hardened grades — verify
                 before using this column for training)
- elongation:    49% filled
- impact_J_avg:  53% filled

WHAT THIS DATASET IS GOOD FOR
------------------------------------------
Forward model for yield strength and UTS from composition + processing.
1,360 samples is enough to train a reasonable GBM. Do not trust this dataset
for hardness prediction until units are verified.

ZENODO DOWNLOAD URL
------------------------------------------
https://zenodo.org/api/records/18530558/files/steelbench_core_open.csv/content
"""

from __future__ import annotations

import io
import logging
import urllib.request
import uuid
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

ZENODO_URL = (
    "https://zenodo.org/api/records/18530558"
    "/files/steelbench_core_open.csv/content"
)

# Source IDs per data tier — registered separately in the DB
SOURCES = {
    "nims_measured":      "src_steelbench_nims",
    "emk_spec_verified":  "src_steelbench_emk",
    "kaggle_measured":    "src_steelbench_kaggle",
}

SOURCE_METADATA = {
    "src_steelbench_nims": {
        "source_type": "NIMS",
        "reliability": 5,
        "notes": "SteelBench v1.0 — NIMS-measured records. DOI: 10.5281/zenodo.18530558",
    },
    "src_steelbench_emk": {
        "source_type": "literature",
        "reliability": 4,
        "notes": "SteelBench v1.0 — EMK specification values, verified. "
                 "Represents spec minima/typical, not exact heat measurements. "
                 "DOI: 10.5281/zenodo.18530558",
    },
    "src_steelbench_kaggle": {
        "source_type": "literature",
        "reliability": 2,
        "notes": "SteelBench v1.0 — Kaggle-sourced records, unclear provenance. "
                 "Use as supplementary only. DOI: 10.5281/zenodo.18530558",
    },
}

# SteelBench steel_family → our schema enum
# SteelBench uses more granular family labels; we collapse to our 7-value enum.
# The original label is preserved in Steel.notes for downstream filtering.
FAMILY_MAP: Dict[str, str] = {
    "carbon_steel":           "carbon",
    "carbon_low":             "carbon",
    "carbon_medium":          "carbon",
    "carbon_high":            "carbon",
    "low_alloy_normalized":   "low-alloy",
    "low_alloy_QT":           "low-alloy",
    "low_alloy_other":        "low-alloy",
    "CrMo_QT":                "low-alloy",
    "NiCrMo_QT":              "low-alloy",
    "stainless_austenitic":   "stainless",
    "stainless_ferritic":     "stainless",
    "stainless_duplex":       "stainless",
    "stainless_steel":        "stainless",
    "stainless_martensitic":  "stainless",
    "stainless_PH":           "stainless",
    "high_Mn_austenitic":     "other",
    "nickel_superalloy":      "other",
}

# quench_medium passthrough — SteelBench values already match our enum
QUENCH_MAP: Dict[str, str] = {
    "air":   "air",
    "water": "water",
    "oil":   "oil",
}

# Route inference from quench medium + temper temperature
def _infer_route(quench: Optional[str], temper_T: Optional[float]) -> str:
    if quench == "air" and temper_T is not None:
        return "NT"
    if quench in ("water", "oil", "polymer") and temper_T is not None:
        return "QT"
    if quench in ("water", "oil", "polymer") and temper_T is None:
        return "QT"   # As-quenched, still classify as QT route
    if quench == "air" and temper_T is None:
        return "normalize"
    return "other"


def _safe_float(val: Any) -> Optional[float]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def load_steelbench_df(local_path: Optional[str] = None) -> pd.DataFrame:
    """
    Load SteelBench CSV. Downloads from Zenodo if no local path given.

    Args:
        local_path: Path to a locally saved copy of steelbench_core_open.csv.
                    If None, downloads directly from Zenodo.
    """
    if local_path:
        df = pd.read_csv(local_path)
        logger.info(f"Loaded SteelBench from local file: {local_path} ({len(df)} rows)")
    else:
        logger.info("Downloading SteelBench from Zenodo...")
        req = urllib.request.Request(ZENODO_URL, headers={"Accept": "*/*"})
        with urllib.request.urlopen(req) as r:
            df = pd.read_csv(io.BytesIO(r.read()))
        logger.info(f"Downloaded SteelBench: {len(df)} rows")
    return df


def parse_steelbench(
    local_path: Optional[str] = None,
    exclude_kaggle: bool = False,
    steel_families: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Parse SteelBench v1.0 into a list of raw dicts for ingest_bundles().

    Args:
        local_path:      Path to local CSV. Downloads from Zenodo if None.
        exclude_kaggle:  Drop kaggle_measured rows (data quality concern).
                         Recommended for the held-out test set.
        steel_families:  Filter to specific steel families (our schema values,
                         e.g. ['carbon', 'low-alloy']). None = include all.

    Returns:
        List of dicts matching SteelIngestBundle structure.

    Example:
        from data.parsers.steelbench import parse_steelbench, SOURCE_METADATA
        from data.ingest import ensure_source, ingest_bundles

        # Register all three sources
        for source_id, meta in SOURCE_METADATA.items():
            ensure_source(source_id=source_id, **meta)

        # Parse and ingest — exclude Kaggle for cleaner training data
        records = parse_steelbench(exclude_kaggle=True, steel_families=['carbon', 'low-alloy'])
        result = ingest_bundles(records)
        print(result)
    """
    df = load_steelbench_df(local_path)

    if exclude_kaggle:
        before = len(df)
        df = df[df["data_tier"] != "kaggle_measured"].reset_index(drop=True)
        logger.info(f"Excluded Kaggle rows: {before - len(df)} dropped, {len(df)} remaining")

    if steel_families:
        # Map our enum values back to SteelBench family names for filtering
        sb_families = {k for k, v in FAMILY_MAP.items() if v in steel_families}
        before = len(df)
        df = df[df["steel_family"].isin(sb_families)].reset_index(drop=True)
        logger.info(f"Family filter: {before - len(df)} dropped, {len(df)} remaining")

    records: List[Dict] = []
    skipped = 0

    for idx, row in df.iterrows():
        tier = str(row.get("data_tier", "kaggle_measured"))
        source_id = SOURCES.get(tier, "src_steelbench_kaggle")
        sb_family = str(row.get("steel_family", "other"))
        our_family = FAMILY_MAP.get(sb_family, "other")

        steel_id = f"sb_{uuid.uuid4().hex[:10]}"
        grade_id = str(row.get("grade_id", "")) or None

        # --- Composition ---
        comp_data: Dict[str, Any] = {"steel_id": steel_id}
        for sb_col, schema_col in [
            ("C", "C"), ("Mn", "Mn"), ("Si", "Si"), ("Cr", "Cr"),
            ("Ni", "Ni"), ("Mo", "Mo"), ("V", "V"), ("Cu", "Cu"), ("Al", "Al"),
        ]:
            comp_data[schema_col] = _safe_float(row.get(sb_col))

        has_comp = any(v is not None for k, v in comp_data.items() if k != "steel_id")
        if not has_comp:
            logger.warning(f"Row {idx} ({grade_id}): no composition data — skipping")
            skipped += 1
            continue

        # --- Processing ---
        quench_raw = str(row.get("quench_medium", "")).strip().lower()
        quench = QUENCH_MAP.get(quench_raw) if quench_raw else None
        austenitize_T = _safe_float(row.get("austenitize_T"))
        temper_T = _safe_float(row.get("temper_T"))
        has_proc = any(x is not None for x in [quench, austenitize_T, temper_T])

        proc_id = f"proc_{uuid.uuid4().hex[:10]}"
        proc_data: Dict[str, Any] = {
            "processing_id": proc_id,
            "steel_id": steel_id,
            "route_type": _infer_route(quench, temper_T),
            "austenitize_temp_C": austenitize_T,
            "quench_medium": quench,
            "temper_temp_C": temper_T,
        }

        # --- Properties ---
        yield_s = _safe_float(row.get("yield_strength"))
        uts = _safe_float(row.get("tensile_strength"))
        elong = _safe_float(row.get("elongation"))
        ra = _safe_float(row.get("reduction_area"))
        charpy = _safe_float(row.get("impact_J_avg"))
        hardness_raw = _safe_float(row.get("hardness"))  # units ambiguous — see module docstring

        has_prop = any(x is not None for x in [yield_s, uts, elong, ra, charpy, hardness_raw])
        if not has_prop:
            logger.warning(f"Row {idx} ({grade_id}): no property data — skipping")
            skipped += 1
            continue

        prop_id = f"prop_{uuid.uuid4().hex[:10]}"
        # NIMS rows in SteelBench are UTS-only records (confirmed by investigation).
        # yield, elongation, hardness, Charpy, and ALL processing params are null
        # for every NIMS row. This is intentional curation, not a parser bug.
        # Tag these rows so training code can partition them correctly:
        # use for UTS-from-composition models, exclude from yield/processing models.
        is_nims_uts_only = (tier == "nims_measured")

        # HARDNESS UNIT INVESTIGATION FINDINGS (2026-04-20):
        # Kaggle rows: HB (Brinell), confirmed against ASM Handbook reference values
        #   for AISI 1020/1040/1080/1095 to within ±2 HB. UTS/HB ratio = 3.53 ± 1.02.
        # EMK rows: NOT valid hardness. UTS/hardness ratio = 14.74 (physically impossible
        #   on any scale). Values capped at 70.0; these are EMK specification limits,
        #   not measurements. Must be excluded from training.
        # NIMS rows: all null (no hardness reported).
        # Result: only populate hardness_HB for Kaggle rows.
        hardness_HB = hardness_raw if tier == "kaggle_measured" else None

        prop_data: Dict[str, Any] = {
            "property_id": prop_id,
            "steel_id": steel_id,
            "processing_id": proc_id if has_proc else None,
            "yield_strength_MPa": yield_s,
            "uts_MPa": uts,
            "elongation_pct": elong,
            "reduction_area_pct": ra,
            "charpy_J": charpy,
            "hardness_HB": hardness_HB,
            "test_temp_C": 25.0,
        }

        records.append({
            "steel": {
                "steel_id": steel_id,
                "grade": grade_id,
                "steel_family": our_family,
                "source_id": source_id,
                # Preserve granular SteelBench family + source for downstream filtering
                "notes": f"sb_family={sb_family} | sb_source={row.get('source')} | "
                         f"heat_id={row.get('heat_id')}"
                         + (" | uts_only=True" if is_nims_uts_only else ""),
            },
            "composition": comp_data,
            "processing": [proc_data] if has_proc else [],
            "properties": [prop_data],
            "microstructure": [],
        })

    logger.info(
        f"SteelBench parse complete: {len(records)} records built, {skipped} skipped"
    )
    return records


def get_source_metadata() -> Dict[str, Dict]:
    """
    Return source metadata dicts ready for ensure_source().

    Usage:
        for source_id, meta in get_source_metadata().items():
            ensure_source(source_id=source_id, **meta)
    """
    return SOURCE_METADATA
