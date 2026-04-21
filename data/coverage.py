"""
Coverage report — run this after every major ingest batch.

Prints a breakdown of non-null coverage per column, grouped by source and steel family.
The goal is to make gaps visible before you start modeling.

Usage:
    python -m data.coverage
    python -m data.coverage --source NIMS
    python -m data.coverage --family low-alloy
"""

from __future__ import annotations

import argparse
from typing import Optional

import pandas as pd
from sqlalchemy import text

from .database import engine


PROPERTY_COLS = [
    "yield_strength_MPa", "uts_MPa", "elongation_pct", "reduction_area_pct",
    "hardness_HV", "hardness_HRC", "hardness_HB",
    "charpy_J", "fracture_tough_KIC_MPa_sqrt_m", "fatigue_limit_MPa",
]

PROCESSING_COLS = [
    "austenitize_temp_C", "austenitize_time_min", "quench_medium",
    "temper_temp_C", "temper_time_min",
    "finishing_temp_C", "coiling_temp_C",
]

COMPOSITION_COLS = [
    "C", "Mn", "Si", "Cr", "Ni", "Mo", "V", "Nb", "Ti", "Al", "Cu",
]


def _load_joined(source_filter: Optional[str], family_filter: Optional[str]) -> pd.DataFrame:
    query = """
        SELECT
            s.steel_id,
            s.steel_family,
            src.source_type,
            src.reliability,
            c.C, c.Mn, c.Si, c.Cr, c.Ni, c.Mo, c.V, c.Nb, c.Ti, c.Al, c.Cu,
            pr.route_type,
            pr.austenitize_temp_C, pr.austenitize_time_min, pr.quench_medium,
            pr.temper_temp_C, pr.temper_time_min,
            pr.finishing_temp_C, pr.coiling_temp_C,
            p.yield_strength_MPa, p.uts_MPa, p.elongation_pct,
            p.reduction_area_pct, p.hardness_HV, p.hardness_HRC, p.hardness_HB,
            p.charpy_J, p.fracture_tough_KIC_MPa_sqrt_m, p.fatigue_limit_MPa
        FROM steels s
        JOIN sources src ON s.source_id = src.source_id
        LEFT JOIN compositions c ON s.steel_id = c.steel_id
        LEFT JOIN properties p ON s.steel_id = p.steel_id
        LEFT JOIN processing pr ON p.processing_id = pr.processing_id
    """
    conditions = []
    if source_filter:
        conditions.append(f"src.source_type = '{source_filter}'")
    if family_filter:
        conditions.append(f"s.steel_family = '{family_filter}'")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    with engine.connect() as conn:
        return pd.read_sql(text(query), conn)


def _coverage_table(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    rows = []
    for col in cols:
        if col not in df.columns:
            continue
        n_total = len(df)
        n_filled = df[col].notna().sum()
        rows.append({
            "column": col,
            "n_total": n_total,
            "n_filled": n_filled,
            "coverage_pct": round(100 * n_filled / n_total, 1) if n_total > 0 else 0.0,
        })
    return pd.DataFrame(rows).sort_values("coverage_pct", ascending=False)


def run_report(
    source_filter: Optional[str] = None,
    family_filter: Optional[str] = None,
) -> None:
    df = _load_joined(source_filter, family_filter)
    n_rows = len(df)
    n_steels = df["steel_id"].nunique() if "steel_id" in df.columns else 0

    print(f"\n{'='*60}")
    print(f"  STEEL DATABASE COVERAGE REPORT")
    if source_filter:
        print(f"  Filter: source_type = {source_filter}")
    if family_filter:
        print(f"  Filter: steel_family = {family_filter}")
    print(f"  Total rows (steel × property): {n_rows}")
    print(f"  Unique steels: {n_steels}")
    print(f"{'='*60}\n")

    if n_rows == 0:
        print("  No data found. Run an ingest first.")
        return

    print("── COMPOSITION COVERAGE ─────────────────────────────────")
    print(_coverage_table(df, COMPOSITION_COLS).to_string(index=False))

    print("\n── PROCESSING COVERAGE ──────────────────────────────────")
    print(_coverage_table(df, PROCESSING_COLS).to_string(index=False))

    # Processing linkage rate — key metric
    has_processing = df["route_type"].notna().sum()
    print(f"\n  Property rows with linked processing: {has_processing}/{n_rows} "
          f"({100*has_processing/n_rows:.1f}%)")

    print("\n── PROPERTY COVERAGE ────────────────────────────────────")
    print(_coverage_table(df, PROPERTY_COLS).to_string(index=False))

    print("\n── BREAKDOWN BY SOURCE ──────────────────────────────────")
    if "source_type" in df.columns:
        summary = (
            df.groupby("source_type")
            .agg(
                rows=("steel_id", "count"),
                steels=("steel_id", "nunique"),
                yield_pct=("yield_strength_MPa", lambda x: f"{100*x.notna().mean():.0f}%"),
                processing_pct=("austenitize_temp_C", lambda x: f"{100*x.notna().mean():.0f}%"),
            )
            .reset_index()
        )
        print(summary.to_string(index=False))

    print("\n── BREAKDOWN BY STEEL FAMILY ────────────────────────────")
    if "steel_family" in df.columns:
        summary = (
            df.groupby("steel_family")
            .agg(
                rows=("steel_id", "count"),
                yield_pct=("yield_strength_MPa", lambda x: f"{100*x.notna().mean():.0f}%"),
                hardness_pct=("hardness_HV", lambda x: f"{100*x.notna().mean():.0f}%"),
            )
            .reset_index()
        )
        print(summary.to_string(index=False))

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Steel database coverage report")
    parser.add_argument("--source", type=str, default=None, help="Filter by source_type")
    parser.add_argument("--family", type=str, default=None, help="Filter by steel_family")
    args = parser.parse_args()
    run_report(source_filter=args.source, family_filter=args.family)
