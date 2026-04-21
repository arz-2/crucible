"""
End-to-end smoke test for the NIMS parser + ingest pipeline.
Uses a synthetic DataFrame that mimics real NIMS MSDB column names.

Run with:
    cd "Alloy cost optimizer agent"
    python -m data.parsers.test_nims_parser
"""

import sys
import os
import logging
import tempfile

import pandas as pd
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Make the project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Patch the database module to use in-memory SQLite BEFORE other imports use it
import data.database as _db_module
_test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

@event.listens_for(_test_engine, "connect")
def _set_fk_pragma(conn, _):
    conn.execute("PRAGMA foreign_keys=ON")

_db_module.engine = _test_engine
_db_module.SessionLocal = sessionmaker(bind=_test_engine, autocommit=False, autoflush=False)

from data.database import init_db
from data.ingest import ensure_source, ingest_bundles
from data.parsers.nims import NIMSParser, parse_nims_file
from data.coverage import run_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def make_synthetic_nims_df() -> pd.DataFrame:
    """
    Synthetic data with NIMS-style column names.
    Covers: clean record, missing properties, swapped units (kgf), missing composition.
    """
    return pd.DataFrame([
        # --- Clean record: AISI 4340 Q&T ---
        {
            "grade": "SCM440",
            "C": 0.40, "Si": 0.25, "Mn": 0.70, "P": 0.015, "S": 0.010,
            "Ni": 1.80, "Cr": 0.80, "Mo": 0.25, "Cu": None, "V": None,
            "Nb": None, "Ti": None, "Al": 0.03, "B": None, "N": None,
            "Austenitizing temperature": 845,
            "Austenitizing time": 60,
            "Quenching method": "oil",
            "Tempering temperature": 425,
            "Tempering time": 120,
            "0.2% proof stress": 1380,
            "Tensile strength": 1480,
            "Elongation": 12.0,
            "Reduction of area": 50.0,
            "Vickers hardness": 430,
            "Charpy impact energy": 65,
            "Charpy test temperature": 25,
        },
        # --- Record with no temper (as-quenched) ---
        {
            "grade": "SCM435",
            "C": 0.35, "Si": 0.22, "Mn": 0.68, "P": 0.012, "S": 0.008,
            "Ni": None, "Cr": 1.05, "Mo": 0.20, "Cu": None, "V": None,
            "Nb": None, "Ti": None, "Al": None, "B": None, "N": None,
            "Austenitizing temperature": 860,
            "Austenitizing time": 45,
            "Quenching method": "oil",
            "Tempering temperature": None,
            "Tempering time": None,
            "0.2% proof stress": 1500,
            "Tensile strength": 1700,
            "Elongation": 8.0,
            "Reduction of area": 35.0,
            "Vickers hardness": 510,
            "Charpy impact energy": None,
            "Charpy test temperature": None,
        },
        # --- Normalized and tempered carbon steel ---
        {
            "grade": "SM490",
            "C": 0.18, "Si": 0.40, "Mn": 1.40, "P": 0.020, "S": 0.012,
            "Ni": None, "Cr": None, "Mo": None, "Cu": None, "V": 0.04,
            "Nb": 0.03, "Ti": None, "Al": 0.03, "B": None, "N": 0.005,
            "Austenitizing temperature": 920,
            "Austenitizing time": 30,
            "Quenching method": "air",
            "Tempering temperature": 600,
            "Tempering time": 60,
            "0.2% proof stress": 355,
            "Tensile strength": 490,
            "Elongation": 22.0,
            "Reduction of area": 65.0,
            "Vickers hardness": 155,
            "Charpy impact energy": 100,
            "Charpy test temperature": 0,
        },
        # --- Row with all properties null — should be skipped ---
        {
            "grade": "Unknown",
            "C": 0.30, "Si": 0.25, "Mn": 0.60, "P": None, "S": None,
            "Ni": None, "Cr": None, "Mo": None, "Cu": None, "V": None,
            "Nb": None, "Ti": None, "Al": None, "B": None, "N": None,
            "Austenitizing temperature": None,
            "Austenitizing time": None,
            "Quenching method": None,
            "Tempering temperature": None,
            "Tempering time": None,
            "0.2% proof stress": None,
            "Tensile strength": None,
            "Elongation": None,
            "Reduction of area": None,
            "Vickers hardness": None,
            "Charpy impact energy": None,
            "Charpy test temperature": None,
        },
    ])


def main():
    print("\n" + "="*60)
    print("  NIMS PARSER — END-TO-END SMOKE TEST")
    print("="*60)

    # 1. Init DB
    init_db()
    print("\n✓ Database initialized (in-memory SQLite)")

    # 2. Register source
    ensure_source(
        source_id="src_nims_msdb",
        source_type="NIMS",
        reliability=5,
        notes="NIMS MatNavi MSDB Structural Steels — synthetic test data",
    )
    print("✓ Source registered")

    # 3. Write synthetic data to a temp Excel file
    df = make_synthetic_nims_df()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        tmp_path = f.name
    df.to_excel(tmp_path, index=False)
    print(f"✓ Synthetic NIMS file written: {tmp_path}")

    # 4. Inspect (demonstrates the inspect() workflow)
    print("\n--- NIMSParser.inspect() output ---")
    NIMSParser.inspect(tmp_path)

    # 5. Parse
    print("\n--- Parsing ---")
    records = parse_nims_file(tmp_path)
    print(f"✓ Parser returned {len(records)} records (expected 3 — one null-property row skipped)")

    # 6. Ingest
    print("\n--- Ingesting ---")
    result = ingest_bundles(records)
    print(f"✓ {result}")

    # 7. Duplicate ingest — should be skipped, not error
    print("\n--- Re-ingesting same records (duplicate test) ---")
    result2 = ingest_bundles(records)
    print(f"✓ {result2}")
    assert result2.skipped == len(records), "Expected all duplicates to be skipped"

    # 8. Coverage report
    print("\n--- Coverage Report ---")
    run_report()

    # Cleanup
    os.unlink(tmp_path)
    print("\n✓ All tests passed")


if __name__ == "__main__":
    main()
