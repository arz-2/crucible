"""
Run all available parsers and ingest into steels.db.

Usage:
    uv run python -m data.parsers.ingest_all
"""

import logging
import sys
from data.database import init_db
from data.ingest import ensure_source, ingest_bundles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest_all")


def _run(label: str, records: list) -> None:
    if not records:
        log.warning(f"{label}: 0 records parsed — skipping")
        return
    result = ingest_bundles(records)
    log.info(f"{label}: {result.success} inserted, {result.skipped} skipped, {len(result.errors)} errors")
    for detail in result.errors[:5]:
        log.warning(f"  {detail}")


def main() -> None:
    init_db()

    # ------------------------------------------------------------------
    # Mondal appendix
    # ------------------------------------------------------------------
    from data.parsers.mondal import parse_mondal, SOURCE_ID as MONDAL_ID
    ensure_source(
        source_id=MONDAL_ID,
        source_type="literature",
        reliability=4,
        notes="S.K. Mandal, Steel Metallurgy: Properties, Specifications and Applications, 1st Ed.",
    )
    _run("Mondal", parse_mondal())

    # ------------------------------------------------------------------
    # ASM Handbook Vol.1
    # ------------------------------------------------------------------
    from data.parsers.asm_vol1 import parse_asm_vol1, SOURCE_ID as ASM_ID
    ensure_source(
        source_id=ASM_ID,
        source_type="literature",
        reliability=4,
        notes="ASM Handbook Vol.1: Properties and Selection: Irons, Steels, "
              "and High-Performance Alloys. ASM International, 1990. "
              "Accessed via Knovel (CMU institutional license).",
    )
    _run("ASM Vol.1", parse_asm_vol1())

    # ------------------------------------------------------------------
    # Cheng 2024
    # ------------------------------------------------------------------
    from data.parsers.cheng2024 import parse_cheng2024, SOURCE_ID as CHENG_ID
    ensure_source(
        source_id=CHENG_ID,
        source_type="literature",
        reliability=3,
        doi="10.1039/d3cp05453e",
        pub_year=2024,
        notes="H. Cheng et al., PCCP 2024. Fe-C-Mn-Al advanced/lightweight steels. "
              "580 records with full composition + processing + UTS + elongation. "
              "File 2 (numeric-encoded) excluded — encoding key not published.",
    )
    _run("Cheng 2024", parse_cheng2024())

    # ------------------------------------------------------------------
    # SteelBench v1.0
    # ------------------------------------------------------------------
    from data.parsers.steelbench import parse_steelbench, SOURCE_METADATA
    for source_id, meta in SOURCE_METADATA.items():
        ensure_source(source_id=source_id, **meta)
    _run("SteelBench", parse_steelbench())

    # ------------------------------------------------------------------
    # ASM Handbook Vol.4
    # ------------------------------------------------------------------
    from data.parsers.asm_vol4 import parse_asm_vol4, SOURCE_ID as ASM4_ID
    ensure_source(
        source_id=ASM4_ID,
        source_type="literature",
        reliability=4,
        notes="ASM Handbook Vol.4: Heat Treating. ASM International, 1991. "
              "Accessed via Knovel (CMU institutional license).",
    )
    _run("ASM Vol.4", parse_asm_vol4())

    log.info("Done. Run `uv run python -m data.coverage` to review.")


if __name__ == "__main__":
    main()
