"""
Parser for AMMRC MS 73-6 — Plane Strain Fracture Toughness (KIC) Data
Handbook for Metals, William T. Matthews, Army Materials and Mechanics
Research Center, December 1973. AD-773 673. Public domain U.S. Gov. work.

This is the most comprehensive pre-1975 compilation of valid KIC measurements
for structural steels: 50 steels in Tables 1–33, each measured per ASTM
E399-72 on fatigue-pre-cracked specimens in neutral lab environment.

DATA QUALITY NOTES
------------------
- Reliability 4: ASTM E399-72 compliant measurements with cited references.
  Values shown are averages (typically ±10%) across several specimens.
- KIC units in the PDF: MN m⁻³/² = MPa√m exactly. The parenthetical SI
  value in each cell is taken directly with no conversion.
- Yield strength: MN/m² = MPa. Parenthetical value used directly.
- Temperature: Kelvin values (in parentheses) converted to Celsius.
- Orientation codes (L-T, T-L, etc.): first letter = loading direction,
  second = crack propagation. Mapped to schema Orientation field.
- processing_id is always set: every row has a heat treatment code.
- Some HT text could not be fully parsed (ausforming, special treatments);
  these get route_type='other' with the full text in processing.notes.

SCOPE
-----
Only Tables 1–33 (steels) are extracted. Ti/Al/Be tables are skipped.
Steel families: low-alloy, maraging, stainless, carbon.

APPROACH
--------
1. pdf2image converts each PDF page to a 300-DPI PNG.
2. Claude vision (claude-opus-4-7) extracts structured JSON per page:
   - Data rows: form, comp/HT codes, orientation, temp, yield, KIC
   - Composition legend: letter codes → wt% per element
   - Heat treatment legend: number codes → text descriptions
3. Multi-sheet tables are merged by table_number.
4. Compositions and HT descriptions are hydrated into each row group
   (one steel + one processing per unique comp×HT combination).

CACHE
-----
Extracted JSON is written to data/AMMRC_KIC/raw/page_NNN.json after each
API call. Subsequent runs read from cache — delete files to re-extract.

SOURCE_ID: src_ammrc_kic_1973
RELIABILITY: 4
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import re
import time
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import anthropic
import pdf2image

logger = logging.getLogger(__name__)

SOURCE_ID = "src_ammrc_kic_1973"
RELIABILITY = 4
_VISION_MODEL = "claude-opus-4-7"

PDF_PATH = (
    Path(__file__).parent.parent.parent
    / "literature_review"
    / "Plane Strain Fracture Toughness (K.) Data Handbook for Metals.pdf"
)
CACHE_DIR = Path(__file__).parent.parent / "AMMRC_KIC" / "raw"

# Steel tables: PDF pages 15–~55. Non-steel pages trigger early stop.
FIRST_STEEL_PAGE = 15
LAST_STEEL_PAGE = 65


# ---------------------------------------------------------------------------
# VLM extraction prompt
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """\
You are digitizing a table from a 1973 scanned military handbook
(AMMRC MS 73-6, "Plane Strain Fracture Toughness Data Handbook for Metals").

STEP 1 — Identify page type.
Return ONLY {"page_type": "non_steel"} if this page is:
- A titanium, aluminum, or beryllium alloy table, OR
- A references, bibliography, introduction, or blank page.

STEP 2 — If this is a STEEL table, return ONLY this JSON (no markdown, no extra text):

{
  "page_type": "data",
  "table_number": <integer>,
  "sheet": <integer — 1 if first/only sheet>,
  "sheet_of": <integer — total sheets for this table>,
  "steel_grade": "<primary grade name, e.g. AISI 4330M or 35NCD16>",
  "steel_category": "<from header, e.g. Steel, Low Alloy or Steel, Maraging>",
  "data_rows": [
    {
      "form": "<Bar, Plate, Forging, Billet, etc.>",
      "comp_code": "<uppercase letter, e.g. A>",
      "ht_code": "<number as string, e.g. 1>",
      "test_orientation": "<e.g. L-T, T-L, T-S, C-R, L-L>",
      "temp_K": <integer — parenthetical Kelvin value>,
      "yield_MPa": <number or null — parenthetical MN/m² value>,
      "kic_MPa_sqrt_m": <number or null — parenthetical MN m⁻³/² value>,
      "specimen_type": "<WOL, Bend, CT, NR, DEC, SEN, DCB, etc.>",
      "reference": <integer or null>
    }
  ],
  "composition_legend": {
    "<LETTER>": {
      "C": <float or null>, "Mn": <float or null>, "Si": <float or null>,
      "P": <float or null>, "S": <float or null>, "Ni": <float or null>,
      "Cr": <float or null>, "Mo": <float or null>, "V": <float or null>,
      "Co": <float or null>, "W": <float or null>, "Al": <float or null>,
      "Ti": <float or null>, "Cu": <float or null>
    }
  },
  "heat_treatment_legend": {
    "<number>": "<full heat treatment description text>"
  }
}

RULES:
1. Dual-unit cells like "191(1248)" — ALWAYS use the parenthetical SI value.
   - Yield "191(1248)"  → yield_MPa = 1248
   - KIC  "120(131)"   → kic_MPa_sqrt_m = 131
   - Temp "70(294)"    → temp_K = 294
2. KIC unit MN m⁻³/² equals MPa√m exactly — no conversion needed.
3. Blank cells, "---", "..." → null.
4. Composition values are wt%. If marked ppm, divide by 10000.
5. Include ALL data rows visible on this page, even continuation rows.
6. If the table spans multiple sheets, include whatever is on THIS page.
   Composition/HT legends may appear only on the last sheet — include them.
7. Normalize composition letter codes to uppercase single letters (A, B, C…).
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _det_id(prefix: str, *parts: Any) -> str:
    key = "_".join(str(p) for p in parts)
    h = hashlib.md5(key.encode()).hexdigest()[:10]
    return f"{prefix}_{h}"


def _K_to_C(k: float) -> float:
    return round(k - 273.15, 2)


# ---------------------------------------------------------------------------
# Heat treatment parsing
# ---------------------------------------------------------------------------

_AUS_K   = re.compile(r'[Aa]ustenitize?\b[^;(]*?\((\d+)\s*K?\)', re.IGNORECASE)
_TMP_K   = re.compile(r'[Tt]emper\b[^;(]*?\((\d+)\s*K?\)',       re.IGNORECASE)
_NRM_K   = re.compile(r'[Nn]ormali[sz]e?\b[^;(]*?\((\d+)\s*K?\)',re.IGNORECASE)
_HIGH_K  = re.compile(r'\((\d{4})\s*K?\)')   # 4-digit K ≥ 1000K → austenitize range
_QUENCH  = re.compile(
    r'\b(Oil|Water|Salt(?:\s+Bath)?|Polymer|Air(?:\s+Cool)?|Press(?:\s+Quench)?|Liquid)\b',
    re.IGNORECASE,
)
_QMAP = {
    "oil": "oil", "water": "water", "salt": "salt_bath",
    "polymer": "polymer", "air": "air",
    "press": "press_quench", "liquid": "other",
}


def _parse_ht(text: str) -> Dict[str, Any]:
    """Parse a heat treatment description string into structured fields.

    Handles the handbook's common shorthand where the austenitize temp is
    stated first without the word "Austenitize", e.g.:
      "1550F (1117K) Oil Quench; Temper 1050F (839K), 4 HR"
    """
    if not text:
        return {"route_type": "other"}

    result: Dict[str, Any] = {}
    tl = text.lower()

    # Quench medium — look in the segment before "Temper"
    pre_temper = re.split(r'[Tt]emper', text, maxsplit=1)[0]
    m = _QUENCH.search(pre_temper)
    if m:
        key = m.group(1).lower().split()[0]   # "salt bath" → "salt"
        result["quench_medium"] = _QMAP.get(key, "other")

    # Austenitize temp — explicit keyword first; fall back to the first
    # high-K value (≥900K) found before the quench keyword.
    m = _AUS_K.search(text)
    if m:
        result["austenitize_temp_C"] = _K_to_C(float(m.group(1)))
    else:
        quench_m = _QUENCH.search(text)
        pre_q = text[: quench_m.start()] if quench_m else pre_temper
        for km in _HIGH_K.finditer(pre_q):
            k = float(km.group(1))
            if k >= 900:   # plausible austenitize range (≥627°C)
                result["austenitize_temp_C"] = _K_to_C(k)
                break      # take the first (leftmost) qualifying value

    # Temper temp
    m = _TMP_K.search(text)
    if m:
        result["temper_temp_C"] = _K_to_C(float(m.group(1)))

    # Guard: temper must be below austenitize
    if (
        result.get("temper_temp_C") is not None
        and result.get("austenitize_temp_C") is not None
        and result["temper_temp_C"] >= result["austenitize_temp_C"]
    ):
        result.pop("temper_temp_C")

    # Route type
    # Most handbook entries use "TEMP Quench; Temper TEMP" without "Austenitize"
    # — detect QT by the presence of a quench medium + temper, not just the keyword.
    is_ausform  = "ausform" in tl
    has_aus_kw  = "austenitize" in tl or "austeniti" in tl
    has_aus     = has_aus_kw or "austenitize_temp_C" in result
    has_quench  = "quench_medium" in result
    has_tmp     = "temper" in tl
    has_nrm     = "normali" in tl
    has_ann     = "anneal" in tl

    if is_ausform:
        result["route_type"] = "other"
    elif has_aus and has_quench and has_tmp:
        result["route_type"] = "QT"
    elif has_aus and has_quench:
        result["route_type"] = "QT"
    elif has_nrm:
        result["route_type"] = "normalize"
    elif has_ann:
        result["route_type"] = "anneal"
    else:
        result["route_type"] = "other"

    # Schema validator: QT requires quench_medium
    if result["route_type"] == "QT" and "quench_medium" not in result:
        result["quench_medium"] = "other"

    return result


# ---------------------------------------------------------------------------
# Orientation mapping
# ---------------------------------------------------------------------------

_ORI: Dict[str, str] = {
    "LT": "LT", "L-T": "LT",
    "TL": "TL", "T-L": "TL",
    "LL": "L",  "L-L": "L", "L": "L",
    "TT": "T",  "T-T": "T", "T": "T",
    "S":  "S",
    "LS": "L",  "L-S": "L",
    "TS": "T",  "T-S": "T",
    "ST": "S",  "S-T": "S",
}


def _map_ori(raw: Optional[str]) -> str:
    if not raw:
        return "unknown"
    s = raw.strip().upper()
    return _ORI.get(s) or _ORI.get(s.replace("-", ""), "unknown")


# ---------------------------------------------------------------------------
# Steel family mapping
# ---------------------------------------------------------------------------

_FAM_KEYS: List[Tuple[str, str]] = [
    ("maraging",      "maraging"),
    ("stainless",     "stainless"),
    ("nickel steel",  "low-alloy"),
    ("low alloy",     "low-alloy"),
    ("high strength", "low-alloy"),
    ("intermediate",  "low-alloy"),
    ("low strength",  "carbon"),
]


def _map_family(category: str, grade: str) -> str:
    cat = category.lower()
    for key, fam in _FAM_KEYS:
        if key in cat:
            return fam
    gl = grade.lower()
    if any(x in gl for x in ("stainless", " ph", "am355", "afc", "fv5")):
        return "stainless"
    if any(x in gl for x in ("maraging", "18 ni", "18ni", "12 ni", "12ni")):
        return "maraging"
    if re.match(r"aisi\s*1[0-5]", gl) or "1045" in gl or "abs-c" in gl:
        return "carbon"
    return "low-alloy"


# ---------------------------------------------------------------------------
# VLM extraction (with disk cache)
# ---------------------------------------------------------------------------

def _page_to_b64(pdf_path: Path, page_num: int) -> str:
    images = pdf2image.convert_from_path(
        pdf_path, dpi=300, first_page=page_num, last_page=page_num
    )
    buf = BytesIO()
    images[0].save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode()


def _extract_page(
    pdf_path: Path,
    page_num: int,
    client: anthropic.Anthropic,
    sleep_sec: float = 1.0,
) -> Dict:
    """Extract table JSON from one PDF page. Caches result to CACHE_DIR."""
    cache = CACHE_DIR / f"page_{page_num:03d}.json"
    if cache.exists():
        logger.debug(f"Page {page_num}: cache hit")
        return json.loads(cache.read_text())

    logger.info(f"Page {page_num}: calling {_VISION_MODEL}...")
    b64 = _page_to_b64(pdf_path, page_num)

    resp = client.messages.create(
        model=_VISION_MODEL,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text",  "text": _EXTRACTION_PROMPT},
            ],
        }],
    )

    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\n?```$", "", raw)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(f"Page {page_num}: JSON parse error — {exc}")
        result = {"page_type": "parse_error", "raw_preview": raw[:300]}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, indent=2))
    time.sleep(sleep_sec)
    return result


# ---------------------------------------------------------------------------
# Bundle construction
# ---------------------------------------------------------------------------

def _table_to_bundles(table: Dict) -> List[Dict]:
    """Convert one merged table dict to SteelIngestBundle-compatible dicts."""
    grade    = table.get("steel_grade") or "Unknown"
    category = table.get("steel_category") or ""
    tnum     = table.get("table_number", 0)
    family   = _map_family(category, grade)
    comp_leg = table.get("composition_legend") or {}
    ht_leg   = table.get("heat_treatment_legend") or {}

    # Group rows by (comp_code, ht_code) → one steel + one processing per group
    groups: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for row in table.get("data_rows") or []:
        ck = str(row.get("comp_code") or "?").strip().upper()
        hk = str(row.get("ht_code")   or "?").strip()
        groups[(ck, hk)].append(row)

    bundles: List[Dict] = []
    for (comp_code, ht_code), rows in groups.items():
        steel_id = _det_id("ammrc",      str(tnum), comp_code, ht_code)
        proc_id  = _det_id("proc_ammrc", str(tnum), comp_code, ht_code)

        # --- Composition ---
        comp_entry = (
            comp_leg.get(comp_code)
            or comp_leg.get(comp_code.lower())
            or {}
        )
        # P capped at 0.1 wt% in schema; clamp rather than drop the whole record
        # (OCR errors occasionally produce 0.15 for 0.015)
        _P_LIMITS = {"P": 0.1, "S": 0.4, "C": 2.14, "B": 0.1}

        comp_data: Dict[str, Any] = {"steel_id": steel_id}
        for el in ("C","Mn","Si","P","S","Ni","Cr","Mo","V","Co","W","Al","Ti","Cu"):
            v = _safe_float(comp_entry.get(el))
            if v is not None:
                limit = _P_LIMITS.get(el)
                if limit and v > limit:
                    logger.warning(f"Table {tnum} comp {comp_code}: {el}={v} exceeds limit {limit} — set to null")
                    v = None
            if v is not None:
                comp_data[el] = v
        has_comp = len(comp_data) > 1

        # --- Processing ---
        ht_text   = ht_leg.get(ht_code) or ht_leg.get(str(ht_code)) or ""
        ht_fields = _parse_ht(ht_text)

        proc_data: Dict[str, Any] = {
            "processing_id": proc_id,
            "steel_id":      steel_id,
            "route_type":    ht_fields.get("route_type", "other"),
        }
        for f in ("austenitize_temp_C", "quench_medium", "temper_temp_C"):
            if f in ht_fields:
                proc_data[f] = ht_fields[f]
        if ht_text:
            proc_data["notes"] = ht_text[:500]

        # --- Properties ---
        props: List[Dict] = []
        for i, row in enumerate(rows):
            temp_K = _safe_float(row.get("temp_K"))
            temp_C = _K_to_C(temp_K) if temp_K is not None else 25.0
            temp_C = max(-200.0, min(800.0, temp_C))   # schema bounds

            ori       = _map_ori(row.get("test_orientation"))
            yield_mpa = _safe_float(row.get("yield_MPa"))
            kic       = _safe_float(row.get("kic_MPa_sqrt_m"))

            if yield_mpa is None and kic is None:
                continue

            props.append({
                "property_id": _det_id(
                    "prop_ammrc", str(tnum), comp_code, ht_code,
                    str(row.get("temp_K")), str(row.get("test_orientation")), str(i),
                ),
                "steel_id":                    steel_id,
                "processing_id":               proc_id,
                "test_standard":               "ASTM E399-72",
                "test_temp_C":                 temp_C,
                "specimen_orientation":        ori,
                "yield_strength_MPa":          yield_mpa,
                "fracture_tough_KIC_MPa_sqrt_m": kic,
            })

        if not props:
            continue

        bundles.append({
            "steel": {
                "steel_id":    steel_id,
                "grade":       grade,
                "steel_family": family,
                "source_id":   SOURCE_ID,
                "notes": (
                    f"AMMRC MS 73-6, Table {tnum} — {grade}. "
                    f"Category: {category}. "
                    f"Comp code {comp_code}, HT code {ht_code}. "
                    "Measured per ASTM E399-72, neutral lab environment."
                ),
            },
            "composition": comp_data if has_comp else None,
            "processing":  [proc_data],
            "properties":  props,
            "microstructure": [],
        })

    return bundles


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_ammrc_kic(
    pdf_path: Optional[Path] = None,
    first_page: int = FIRST_STEEL_PAGE,
    last_page: int = LAST_STEEL_PAGE,
    api_key: Optional[str] = None,
) -> List[Dict]:
    """
    Extract KIC data from the AMMRC 1973 handbook via Claude vision.

    On first run this makes ~50 API calls (one per PDF page). All responses
    are cached in data/AMMRC_KIC/raw/. Subsequent runs load from cache.

    Args:
        pdf_path: Path to the PDF. Defaults to literature_review/ location.
        first_page: First PDF page (1-indexed). Steel tables start at page 15.
        last_page: Upper bound; stops early when 3 consecutive non-steel pages appear.
        api_key: Anthropic API key. Defaults to ANTHROPIC_API_KEY env var.

    Returns:
        List of dicts conforming to SteelIngestBundle structure.

    Example:
        from data.parsers.ammrc_kic import parse_ammrc_kic, SOURCE_ID
        from data.ingest import ensure_source, ingest_bundles

        ensure_source(
            source_id=SOURCE_ID,
            source_type="literature",
            reliability=4,
            pub_year=1973,
            notes=(
                "William T. Matthews, 'Plane Strain Fracture Toughness (KIC) "
                "Data Handbook for Metals', AMMRC MS 73-6, Dec 1973. AD-773 673. "
                "50 steels, Tables 1-33. ASTM E399-72. Public domain U.S. Gov. work."
            ),
        )
        records = parse_ammrc_kic()
        result  = ingest_bundles(records)
        print(result)
    """
    p = pdf_path or PDF_PATH
    if not p.exists():
        raise FileNotFoundError(f"PDF not found: {p}")

    client = anthropic.Anthropic(api_key=api_key)

    # Phase 1: extract pages
    raw_pages: List[Dict] = []
    non_steel_run = 0
    for page_num in range(first_page, last_page + 1):
        try:
            page_data = _extract_page(p, page_num, client)
        except Exception as exc:
            logger.warning(f"Page {page_num}: skipped — {exc}")
            non_steel_run = 0
            continue

        ptype = page_data.get("page_type", "")

        if ptype == "non_steel":
            non_steel_run += 1
            logger.info(f"Page {page_num}: non-steel ({non_steel_run} consecutive)")
            if non_steel_run >= 3:
                logger.info("3 consecutive non-steel pages — stopping")
                break
            continue

        non_steel_run = 0

        if ptype == "data":
            page_data["_pdf_page"] = page_num
            raw_pages.append(page_data)

    logger.info(f"Collected {len(raw_pages)} steel table pages")

    # Phase 2: merge multi-sheet tables
    tables: Dict[int, Dict] = {}
    for page in raw_pages:
        tnum = int(page.get("table_number") or 0)
        if tnum == 0:
            continue
        if tnum not in tables:
            tables[tnum] = {
                "table_number":       tnum,
                "steel_grade":        page.get("steel_grade") or "",
                "steel_category":     page.get("steel_category") or "",
                "data_rows":          [],
                "composition_legend": {},
                "heat_treatment_legend": {},
            }
        t = tables[tnum]
        if page.get("steel_grade"):
            t["steel_grade"] = page["steel_grade"]
        t["data_rows"].extend(page.get("data_rows") or [])
        t["composition_legend"].update(page.get("composition_legend") or {})
        t["heat_treatment_legend"].update(page.get("heat_treatment_legend") or {})

    # Phase 3: build bundles
    records: List[Dict] = []
    for tnum, table in sorted(tables.items()):
        try:
            bundles = _table_to_bundles(table)
            records.extend(bundles)
            logger.debug(f"Table {tnum} ({table['steel_grade']}): {len(bundles)} bundles")
        except Exception as exc:
            logger.warning(f"Table {tnum} ({table.get('steel_grade')}): {exc}")

    logger.info(
        f"AMMRC KIC parse complete: {len(records)} bundles from {len(tables)} tables"
    )
    return records


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Test single-page extraction (Table 1, PDF page 15) from cache or API
    client = anthropic.Anthropic()
    page = _extract_page(PDF_PATH, 15, client)
    print(f"\npage_type : {page.get('page_type')}")
    print(f"table     : {page.get('table_number')} — {page.get('steel_grade')}")
    print(f"rows      : {len(page.get('data_rows') or [])}")
    print(f"comp codes: {list((page.get('composition_legend') or {}).keys())}")
    print(f"HT codes  : {list((page.get('heat_treatment_legend') or {}).keys())}")

    if "--ingest" in sys.argv:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from data.ingest import ensure_source, ingest_bundles
        ensure_source(
            source_id=SOURCE_ID,
            source_type="literature",
            reliability=RELIABILITY,
            pub_year=1973,
            notes=(
                "William T. Matthews, 'Plane Strain Fracture Toughness (KIC) "
                "Data Handbook for Metals', AMMRC MS 73-6, December 1973. "
                "AD-773 673. 50 steels (Tables 1-33), ASTM E399-72, neutral "
                "lab environment. Public domain U.S. Government work."
            ),
        )
        records = parse_ammrc_kic()
        result  = ingest_bundles(records)
        print(f"\nIngested: {result}")
