"""
Parser for the Fe–C–Mn–Al steel dataset from:

  H. Cheng et al., "Composition design and optimization of Fe–C–Mn–Al steel
  based on machine learning," Physical Chemistry Chemical Physics, 2024.
  DOI: 10.1039/d3cp05453e

FILES
-----
  d3cp05453e1.xlsx  — 580 records, string categorical columns (parsed here)
  d3cp05453e2.xlsx  — 580 different records, numeric-encoded categoricals
                       (encoding key not published; excluded from this parser)

DATA QUALITY NOTES
------------------
- Compositions are experimental or literature-sourced values in wt%.
- These are advanced/lightweight steels: medium-/high-Mn (up to 30 wt%),
  high-Al (up to 13 wt%), TWIP/TRIP/medium-Mn families. steel_family='other'
  for all records.
- Properties: UTS (MPa) and TEL (total elongation %) only — no yield strength.
- Processing is multi-step: hot rolling → optional cold rolling → annealing
  → optional additional annealing → optional tempering. Mapped to a single
  ProcessingCreate record (best-fit route_type). Full process details in notes.
- Specimen dimensions and strain rate (GL, GW, GH, SR) stored in notes only.
- Zr is present in many records but not in the CompositionCreate schema;
  stored in steel.notes.
- Reliability: 3 (literature-aggregated, not single-source measurements).

SOURCE_ID: src_cheng_2024
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

SOURCE_ID = "src_cheng_2024"
RELIABILITY = 3
DATA_FILE = Path(__file__).parent.parent / "H.Cheng_et_al" / "d3cp05453e1.xlsx"

# ACM / HRCM / PCRAM / AACM / TCM → our QuenchMedium enum
_MEDIUM_MAP = {
    "air":     "air",
    "water":   "water",
    "oil":     "oil",
    "furnace": "other",   # furnace cooling has no exact enum match
    "gas":     "other",   # gas quench
}


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


def _map_medium(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip().lower()
    return _MEDIUM_MAP.get(s)


def _steel_family(row: pd.Series) -> str:
    mn = _safe_float(row.get("Mn")) or 0.0
    al = _safe_float(row.get("Al")) or 0.0
    cr = _safe_float(row.get("Cr")) or 0.0
    if mn > 5.0 or al > 2.0:
        return "other"   # medium-/high-Mn or lightweight steel
    if cr >= 10.0:
        return "stainless"
    c = _safe_float(row.get("C")) or 0.0
    if c <= 0.3 and mn <= 2.0 and cr <= 1.0:
        return "carbon"
    return "low-alloy"


def _build_grade(row: pd.Series) -> str:
    parts = []
    for el in ("C", "Mn", "Al", "Si", "Cr", "Ni", "Mo"):
        v = _safe_float(row.get(el))
        if v and v > 0:
            parts.append(f"{v:.2f}{el}")
    return "Fe-" + "-".join(parts) if parts else "Fe-alloy"


def parse_cheng2024(path: Optional[Path] = None) -> List[Dict]:
    """
    Parse d3cp05453e1.xlsx into SteelIngestBundle-compatible dicts.

    Returns:
        List of bundle dicts (580 records).

    Example:
        from data.parsers.cheng2024 import parse_cheng2024, SOURCE_ID
        from data.ingest import ensure_source, ingest_bundles

        ensure_source(
            source_id=SOURCE_ID,
            source_type="literature",
            reliability=3,
            doi="10.1039/d3cp05453e",
            pub_year=2024,
            notes="H. Cheng et al., PCCP 2024. Fe-C-Mn-Al advanced/lightweight steels. "
                  "580 records with full composition + processing + UTS + elongation. "
                  "File 2 (numeric-encoded) excluded — encoding key not published."
        )
        records = parse_cheng2024()
        result = ingest_bundles(records)
        print(result)
    """
    p = path or DATA_FILE
    df = pd.read_excel(p)

    records: List[Dict] = []
    for idx, row in df.iterrows():
        uts  = _safe_float(row.get("UTS"))
        tel  = _safe_float(row.get("TEL"))
        if uts is None and tel is None:
            continue

        # --- Composition ---
        c_val  = _safe_float(row.get("C"))
        mn_val = _safe_float(row.get("Mn"))
        al_val = _safe_float(row.get("Al"))
        si_val = _safe_float(row.get("Si"))
        cr_val = _safe_float(row.get("Cr"))
        ni_val = _safe_float(row.get("Ni"))
        mo_val = _safe_float(row.get("Mo"))
        ti_val = _safe_float(row.get("Ti"))
        nb_val = _safe_float(row.get("Nb"))
        b_raw  = _safe_float(row.get("B"))
        # Schema caps B at 0.1 wt% (steel B is normally <0.01 wt%).
        # Values >0.1 are stored in notes — likely a specialty alloy or unit error.
        b_val  = b_raw if (b_raw is None or b_raw <= 0.1) else None
        v_val  = _safe_float(row.get("V"))
        cu_val = _safe_float(row.get("Cu"))
        p_val  = _safe_float(row.get("P"))
        s_val  = _safe_float(row.get("S"))
        n_val  = _safe_float(row.get("N"))
        zr_val = _safe_float(row.get("Zr"))

        # --- Processing ---
        hrst   = _safe_float(row.get("HRST"))
        hrrr   = _safe_float(row.get("HRRR"))
        crrr   = _safe_float(row.get("CRRR"))
        at     = _safe_float(row.get("AT"))
        a_time = _safe_float(row.get("At"))
        acm    = _map_medium(row.get("ACM"))
        tt     = _safe_float(row.get("TT"))
        t_time = _safe_float(row.get("Tt"))

        # Anneal step active if AT > 50°C.
        # austenitize_temp_C schema min is 600°C (conventional steels).
        # Medium-Mn intercritical annealing can be 400–600°C — store in notes
        # rather than widening the schema, which is designed for standard grades.
        anneal_active = at is not None and at > 50.0
        anneal_in_schema = anneal_active and at >= 600.0
        temper_active = tt is not None and tt > 50.0

        # Cold rolling present → anneal route; hot-rolled only → TMCP
        has_cold_roll = crrr is not None
        route_type = "anneal" if has_cold_roll else "TMCP"

        proc: Dict[str, Any] = {
            "steel_id": "",          # filled below
            "route_type": route_type,
            "austenitize_temp_C":  at     if anneal_in_schema else None,
            "austenitize_time_min": a_time if anneal_in_schema else None,
            "quench_medium":       acm    if anneal_in_schema and acm else None,
            "temper_temp_C":       tt     if temper_active else None,
            "temper_time_min":     t_time if temper_active else None,
            "finishing_temp_C":    hrst   if not has_cold_roll and hrst else None,
            "reduction_ratio":     crrr   if has_cold_roll else hrrr,
        }

        # Additional context that doesn't fit schema columns
        extra_fields = {
            "HRST": hrst, "HRRR": hrrr, "HRS": row.get("HRS"),
            "HRCT": row.get("HRCT"), "HRCM": row.get("HRCM"),
            "PCRAT": row.get("PCRAT"), "PCRAt": row.get("PCRAt"), "PCRAM": row.get("PCRAM"),
            "CRRR": crrr, "CRS": row.get("CRS"),
            "AAT": row.get("AAT"), "Aat": row.get("Aat"), "AACM": row.get("AACM"),
            "GL": row.get("GL"), "GW": row.get("GW"), "GH": row.get("GH"),
            "SR": row.get("SR"),
        }
        proc_notes = "; ".join(f"{k}={v}" for k, v in extra_fields.items() if v is not None and str(v) not in ("nan", ""))

        grade_str = _build_grade(row)
        family = _steel_family(row)
        steel_id = _det_id("cheng24", idx, grade_str,
                           str(at), str(tt), str(crrr), str(hrrr))
        proc_id = _det_id("proc_cheng24", steel_id)

        proc["steel_id"] = steel_id
        proc["processing_id"] = proc_id
        proc["notes"] = proc_notes if proc_notes else None

        extras = []
        if zr_val and zr_val > 0:
            extras.append(f"Zr={zr_val:.4f} wt%")
        if anneal_active and not anneal_in_schema:
            extras.append(f"intercritical anneal AT={at}°C (below schema 600°C floor)")
        if b_raw is not None and b_raw > 0.1:
            extras.append(f"B={b_raw} wt% (exceeds schema cap, stored in notes only)")
        steel_notes = (
            f"Cheng 2024 (d3cp05453e), row {idx}. "
            + ("; ".join(extras) + ". " if extras else "")
            + f"Multi-step process: HR→{'CR→' if has_cold_roll else ''}anneal"
            + ("→temper" if temper_active else "") + "."
        )

        records.append({
            "steel": {
                "steel_id": steel_id,
                "grade": grade_str,
                "steel_family": family,
                "source_id": SOURCE_ID,
                "notes": steel_notes,
            },
            "composition": {
                "steel_id": steel_id,
                "C": c_val, "Mn": mn_val, "Si": si_val, "Cr": cr_val,
                "Ni": ni_val, "Mo": mo_val, "V": v_val, "Nb": nb_val,
                "Ti": ti_val, "Al": al_val, "Cu": cu_val,
                "B": b_val, "N": n_val, "P": p_val, "S": s_val,
            },
            "processing": [proc],
            "properties": [{
                "property_id": _det_id("prop_cheng24", steel_id),
                "steel_id": steel_id,
                "processing_id": proc_id,
                "uts_MPa": uts,
                "elongation_pct": tel,
                "test_temp_C": 25.0,
            }],
            "microstructure": [],
        })

    logger.info(f"Cheng 2024 parse complete: {len(records)} records")
    return records
