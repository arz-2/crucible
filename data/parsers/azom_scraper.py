"""
Scraper/parser for targeted AZoM.com steel grade pages.

SOURCE
------
AZoM.com — Materials Science & Engineering Database
URL: https://www.azom.com
License: Free to read (public web pages). Data originally sourced from
published standards, academic literature, and supplier documentation.

NOTE ON USE
-----------
This scraper fetches individual grade pages via direct HTTP. AZoM article
pages (article.aspx?ArticleID=XXXX) are publicly accessible without bot
protection. We scrape a targeted list of ~30 specific grade pages, not
a bulk crawl.

Reliability: 3 (secondary aggregation from published standards/literature,
one step removed from primary sources). Treat as comparable to Jalalian
Zenodo dataset.

COVERAGE
--------
Target grades (fill specific gaps in the DB):

  HSLA / Structural:
    ASTM A36             (ID=6117) — carbon structural
    ASTM A514            (ID=6111) — Q&T high-strength plate
    ASTM A588 Gr A       (ID=6110) — weathering structural
    ASTM A572 Gr 42      (ID=6108) — HSLA structural
    ASTM A572 Gr 50      (ID=6109) — HSLA structural
    ASTM A572 Gr 65      (ID=6113) — HSLA structural

  Alloy steel (supplement ASM Vol.4 normalized-condition gap):
    AISI 4130            (ID=6742)
    AISI 4340            (ID=6772)
    AISI 8620            (ID=6754) — case hardening
    AISI 8630            (ID=6755) — case hardening

  Tool steels (completely absent from DB):
    AISI D2              (ID=6214) — cold work
    AISI M2              (ID=6174) — high speed
    AISI H13             (ID=9107) — hot work
    AISI O1              (ID=6229) — oil hardening cold work
    AISI A2              (ID=6224) — air hardening cold work

  Maraging (present but 0% processing):
    Maraging 200         (ID=6727)
    Maraging 250         (ID=6728)
    Maraging 300         (ID=6751)
    Maraging 350         (ID=6735)

DATA QUALITY NOTES
------------------
- AZoM typically shows ONE condition per grade page (annealed, normalized, or
  hardened depending on the grade's typical use state).
- Composition values are given as ranges (spec limits); parser uses midpoints.
- HRC marked "(converted from Brinell hardness)" or similar qualifiers are
  excluded — these are not measured values.
- HRC ranges (e.g. "34-64" for O1) are excluded (condition-dependent).
- UTS/YS shown as ranges: midpoint is used for training.
- Maraging properties shown at test temperature (not room temperature) on
  some pages — flagged and stored with test_temp_C extracted from text.
- HSLA (A36, A572): as-rolled, no heat treatment parameters.
- Tool steels: hardened condition (quenched + tempered).
- Maraging: aged condition.

SOURCE_ID: src_azom_scraper
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SOURCE_ID   = "src_azom_scraper"
RELIABILITY = 3
SOURCE_URL  = "https://www.azom.com"
SOURCE_YEAR = 2024

# ---------------------------------------------------------------------------
# Grade catalogue — (article_id, grade_label, steel_family, route_hint, notes)
# route_hint: preferred route_type if parseable from page, else hardcoded
# ---------------------------------------------------------------------------

GRADE_ARTICLES: List[Dict[str, Any]] = [
    # HSLA / Structural — AZoM only has individual pages for A36; other HSLA grades
    # (A572 Gr50, A514, A588) are handled by the astm_hsla_specs.py hand-curated parser.
    {"id": 6117, "grade": "ASTM A36",        "family": "HSLA",      "route": "as_rolled", "austen": None, "quench": None},
    # Alloy steels (complement ASM Vol.4 single-condition data)
    {"id": 6742, "grade": "AISI 4130",        "family": "low-alloy", "route": "QT",        "austen": 871,  "quench": "oil"},
    {"id": 6772, "grade": "AISI 4340",        "family": "low-alloy", "route": "QT",        "austen": 830,  "quench": "oil"},
    {"id": 6754, "grade": "AISI 8620",        "family": "low-alloy", "route": "case_harden","austen": None, "quench": None},
    # 6755 = AISI 8822 — AZoM page has no mechanical properties table; skipped.
    # {"id": 6755, "grade": "AISI 8822", ...},
    # Tool steels (completely absent from DB — this is the main value-add)
    {"id": 6214, "grade": "AISI D2",          "family": "tool",      "route": "QT",        "austen": 1010, "quench": "air"},
    {"id": 6174, "grade": "AISI M2",          "family": "tool",      "route": "QT",        "austen": 1230, "quench": "oil"},
    {"id": 9107, "grade": "AISI H13",         "family": "tool",      "route": "QT",        "austen": 1010, "quench": "air"},
    {"id": 6229, "grade": "AISI O1",          "family": "tool",      "route": "QT",        "austen":  800, "quench": "oil"},
    # Maraging — NOTE: AZoM maraging pages only show elevated-temperature properties
    # (@538°C test temp), not room-temperature properties. Room-temp properties are
    # already in the DB via Figshare. Excluded here to avoid bad data.
    # {"id": 6727, "grade": "Maraging 18Ni-200", ...},  # elevated temp only
    # {"id": 6728, "grade": "Maraging 18Ni-250", ...},  # elevated temp only
    # {"id": 6751, "grade": "Maraging 18Ni-300", ...},  # elevated temp only
    # {"id": 6735, "grade": "Maraging 18Ni-350", ...},  # elevated temp only
]

# ---------------------------------------------------------------------------
# Element name normalisation
# ---------------------------------------------------------------------------

_ELEM_MAP: Dict[str, str] = {
    "carbon":      "C",
    "manganese":   "Mn",
    "silicon":     "Si",
    "chromium":    "Cr",
    "nickel":      "Ni",
    "molybdenum":  "Mo",
    "vanadium":    "V",
    "niobium":     "Nb",
    "columbium":   "Nb",
    "titanium":    "Ti",
    "aluminum":    "Al",
    "aluminium":   "Al",
    "copper":      "Cu",
    "nitrogen":    "N",
    "phosphor":    "P",   # "phosphorous", "phosphorus"
    "sulfur":      "S",
    "sulphur":     "S",
    "cobalt":      "Co",
    "tungsten":    "W",
}

_SCHEMA_ELEMENTS = {"C","Mn","Si","Cr","Ni","Mo","V","Nb","Ti","Al","Cu","N","P","S","Co","W"}

def _norm_element(raw: str) -> Optional[str]:
    """Map an element name cell to a schema field key. Returns None if irrelevant."""
    # Some pages use bare symbols ("C", "Mn", "Cr") instead of full names
    stripped = raw.strip()
    if stripped in _SCHEMA_ELEMENTS:
        return stripped
    # Also catch "Fe" (balance) — return None so it is skipped
    if stripped.lower() in ("fe", "iron"):
        return None

    raw = raw.lower()
    # Strip symbol in parentheses or after comma: "Chromium, Cr" → "chromium"
    name_part = re.split(r",|\(", raw)[0].strip()
    for key, sym in _ELEM_MAP.items():
        if name_part.startswith(key):
            return sym if sym in _SCHEMA_ELEMENTS else None
    return None


# ---------------------------------------------------------------------------
# Value parsing helpers
# ---------------------------------------------------------------------------

def _parse_range_midpoint(val: str) -> Optional[float]:
    """
    Parse a value string like "0.80 - 1.10", "0.040", "≤ 0.05".
    Returns midpoint for ranges, single value otherwise. Returns None
    for 'balance', 'bal', empty, or unparseable strings.
    """
    val = val.strip().lower()
    # Skip non-numeric content
    if not val or val in ("balance", "bal", "-", "n/a", ""):
        return None
    # Remove unit suffixes and special chars
    val = re.sub(r"[%°cmgks/³²]", "", val, flags=re.IGNORECASE)
    val = re.sub(r"\b(mpa|gpa|psi|ksi|hb|hrc|hv|w|j)\b", "", val, flags=re.IGNORECASE)
    val = val.strip()
    # Handle ≤ / ≥ / max / min prefixes (treat as single value)
    val = re.sub(r"^[≤≥<>~±]", "", val).strip()
    val = re.sub(r"^(max|min|approx\.?|typical)", "", val).strip()
    # Range: "0.80 - 1.10" or "400 - 550"
    range_m = re.match(r"([\d.]+)\s*[-–]\s*([\d.]+)", val)
    if range_m:
        lo, hi = float(range_m.group(1)), float(range_m.group(2))
        return (lo + hi) / 2.0
    # Single number
    single_m = re.match(r"^([\d.]+)", val)
    if single_m:
        return float(single_m.group(1))
    return None


def _extract_mpa(cell: str) -> Optional[float]:
    """
    Parse a metric property cell that contains an MPa value.
    Handles: "655 MPa", "400 - 550 MPa", "1200 - 1590 MPa".
    Returns None if no MPa value found or value is unreasonably small.
    """
    cell = cell.strip()
    # Match MPa value
    m = re.search(r"([\d.]+)\s*-\s*([\d.]+)\s*[Mm][Pp][Aa]", cell)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2.0
    m = re.search(r"([\d.]+)\s*[Mm][Pp][Aa]", cell)
    if m:
        return float(m.group(1))
    return None


def _extract_pct(cell: str) -> Optional[float]:
    """Parse a percentage value from a cell string."""
    cell = cell.strip()
    m = re.search(r"([\d.]+)\s*%", cell)
    if m:
        return float(m.group(1))
    return None


def _extract_hardness(label: str, metric_val: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Returns (HB, HRC) extracted from a mechanical property row.
    Returns (None, None) if not a hardness row or value is bad.

    Rules:
    - Excludes rows with "converted" in label (derived values, not measured).
    - Excludes HRC if value is a range string (condition-dependent).
    - Excludes HRC < 20 (meaningless for this field; suggests conversion artefact).
    """
    label_l = label.lower()

    is_converted = "converted" in label_l

    # Brinell
    if "brinell" in label_l and not is_converted:
        v = _parse_range_midpoint(re.sub(r"[^\d.\-–]", " ", metric_val).strip())
        if v and 50 < v < 700:
            return v, None

    # Rockwell C
    if ("rockwell c" in label_l or "rockwell  c" in label_l) and not is_converted:
        raw = re.sub(r"[^\d.\-–]", " ", metric_val).strip()
        # Reject ranges like "34.0-64.0" (too wide to be a single condition)
        if re.match(r"[\d.]+\s*[-–]\s*[\d.]+", raw):
            return None, None
        v = _parse_range_midpoint(raw)
        if v and v >= 20:
            return None, v

    return None, None


# ---------------------------------------------------------------------------
# Heat treatment text parsing
# ---------------------------------------------------------------------------

_TEMP_C_RE = re.compile(r"(\d{3,4})\s*°?\s*[Cc]")

def _parse_heat_treatment(text: str, grade_cfg: Dict) -> Dict[str, Any]:
    """
    Extract processing parameters from the heat treatment prose section.
    Falls back to grade_cfg hardcoded values where text parsing fails.
    """
    result: Dict[str, Any] = {}

    text_l = text.lower()

    # Austenitize / hardening temperature
    austen_temp: Optional[float] = grade_cfg.get("austen")
    for phrase in ["heated at", "austenitiz", "hardening temperature", "heat treat"]:
        m = re.search(phrase + r".{0,60}", text_l)
        if m:
            temps = _TEMP_C_RE.findall(text[m.start():m.start()+80])
            if temps:
                austen_temp = float(temps[0])
                break

    if austen_temp:
        result["austenitize_temp_C"] = austen_temp

    # Quench medium
    qm: Optional[str] = grade_cfg.get("quench")
    if "oil quench" in text_l or "quench in oil" in text_l or "quenching in oil" in text_l:
        qm = "oil"
    elif "water quench" in text_l or "quench in water" in text_l:
        qm = "water"
    elif "air cool" in text_l or "air quench" in text_l or "air-hardening" in text_l:
        qm = "air"
    elif "polymer" in text_l:
        qm = "polymer"
    if qm and qm not in ("water_or_oil",):
        result["quench_medium"] = qm

    # Temper temperature — first temperature after "temper"
    m = re.search(r"temper.{0,100}", text_l)
    if m:
        temps = _TEMP_C_RE.findall(text[m.start():m.start()+120])
        if temps:
            result["temper_temp_C"] = float(temps[0])

    return result


# ---------------------------------------------------------------------------
# Page fetch + parse
# ---------------------------------------------------------------------------

def _fetch_page(article_id: int) -> Optional[str]:
    """Fetch an AZoM article page. Returns HTML string or None on failure."""
    try:
        import requests
        url = f"https://www.azom.com/article.aspx?ArticleID={article_id}"
        r = requests.get(
            url,
            headers={"User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )},
            timeout=20,
        )
        r.raise_for_status()
        return r.text
    except Exception as e:
        logger.warning(f"AZoM fetch failed for ArticleID={article_id}: {e}")
        return None


def _parse_page(html: str, grade_cfg: Dict) -> Optional[Dict]:
    """
    Parse one AZoM article page. Returns a raw data dict or None.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise ImportError("beautifulsoup4 required: pip install beautifulsoup4 lxml")

    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    full_text = soup.get_text(" ", strip=True)

    # --- Composition (Table 0) ---
    comp: Dict[str, float] = {}
    if tables:
        for row in tables[0].find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            elem = _norm_element(cells[0])
            if elem is None:
                continue
            mid = _parse_range_midpoint(cells[1])
            if mid is not None and mid > 0:
                comp[elem] = round(mid, 4)

    if not comp:
        logger.warning(f"No composition parsed for {grade_cfg['grade']}")
        return None

    # Schema cap on P
    if "P" in comp and comp["P"] > 0.1:
        comp["P"] = 0.1

    # --- Mechanical properties (Table 2, sometimes Table 3) ---
    uts = ys = elong = hb = hrc = None
    elong_50mm: Optional[float] = None
    elong_200mm: Optional[float] = None

    for t in tables[1:4]:
        for row in t.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            label = cells[0]
            metric = cells[1] if len(cells) > 1 else ""
            label_l = label.lower()

            # Skip rows with elevated-temperature conditions (not room temp).
            # @25°C / @20°C / @RT are room temp — keep those.
            # @100°C and above are elevated — skip.
            temp_match = re.search(r"@\s*(\d+)\s*°", label)
            if temp_match and int(temp_match.group(1)) > 50:
                continue
            if re.search(r"temperature\s+[1-9]\d{2,}", label_l):
                continue

            # UTS — AZoM uses "Tensile Strength, Ultimate" or plain "Tensile Strength"
            if ("tensile strength" in label_l
                    and "yield" not in label_l
                    and "shear" not in label_l):
                if uts is None:
                    uts = _extract_mpa(metric)

            # YS
            elif ("tensile strength, yield" in label_l
                  or "yield strength" in label_l
                  and "compressive" not in label_l):
                if ys is None and "compressive" not in label_l:
                    ys = _extract_mpa(metric)

            # Elongation — prefer 50mm gauge
            elif "elongation" in label_l and "break" in label_l:
                pct = _extract_pct(metric)
                if pct is not None:
                    if "50 mm" in label_l or "50mm" in label_l or "2 in" in label_l:
                        elong_50mm = pct
                    elif "200 mm" in label_l or "200mm" in label_l or "8 in" in label_l:
                        elong_200mm = pct
                    elif elong is None:
                        elong = pct

            # Hardness
            elif "hardness" in label_l:
                hb_v, hrc_v = _extract_hardness(label, metric)
                if hb_v and hb is None:
                    hb = hb_v
                if hrc_v and hrc is None:
                    hrc = hrc_v

    # Prefer 50mm elongation
    if elong_50mm is not None:
        elong = elong_50mm
    elif elong_200mm is not None:
        elong = elong_200mm

    # Validate we have at least one property
    if not any(v is not None for v in [uts, ys, elong, hb, hrc]):
        logger.warning(f"No properties parsed for {grade_cfg['grade']}")
        return None

    # --- Heat treatment text ---
    # Find the heat treatment section
    ht_section = ""
    ht_m = re.search(r"[Hh]eat [Tt]reatment.{0,2000}", full_text)
    if ht_m:
        ht_section = ht_m.group(0)
    proc_data = _parse_heat_treatment(ht_section or full_text[:3000], grade_cfg)

    return {
        "comp":      comp,
        "uts":       uts,
        "ys":        ys,
        "elong":     elong,
        "hb":        hb,
        "hrc":       hrc,
        "proc_data": proc_data,
    }


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def _det_id(prefix: str, *parts: Any) -> str:
    key = "_".join(str(p) for p in parts)
    h = hashlib.md5(key.encode()).hexdigest()[:10]
    return f"{prefix}_{h}"


# ---------------------------------------------------------------------------
# Public parser
# ---------------------------------------------------------------------------

def parse_azom_grades(
    article_ids: Optional[List[int]] = None,
    delay_s: float = 1.5,
) -> List[Dict]:
    """
    Scrape AZoM grade pages and return SteelIngestBundle-compatible dicts.

    Args:
        article_ids: If provided, only scrape these article IDs (subset of
                     GRADE_ARTICLES). Default: scrape all.
        delay_s:     Seconds to wait between requests (be polite).

    Returns:
        List of dicts matching SteelIngestBundle structure.

    Usage:
        from data.parsers.azom_scraper import parse_azom_grades, SOURCE_ID
        from data.ingest import ensure_source, ingest_bundles

        ensure_source(
            source_id=SOURCE_ID,
            source_type="literature",
            reliability=RELIABILITY,
            pub_year=SOURCE_YEAR,
            notes=(
                "AZoM.com steel grade pages. Targeted scrape of ~20 grades "
                "to fill HSLA, tool steel, and maraging gaps. "
                "Composition midpoints from spec ranges; single-condition "
                "properties. CC-0 / public web."
            ),
        )
        records = parse_azom_grades()
        print(ingest_bundles(records))
    """
    target_ids = set(article_ids) if article_ids else None
    grades = [g for g in GRADE_ARTICLES if target_ids is None or g["id"] in target_ids]

    records: List[Dict] = []

    for cfg in grades:
        aid = cfg["id"]
        grade = cfg["grade"]
        logger.info(f"Fetching AZoM ArticleID={aid} ({grade}) ...")

        html = _fetch_page(aid)
        if html is None:
            continue

        parsed = _parse_page(html, cfg)
        if parsed is None:
            continue

        steel_id = _det_id("v_azom", str(aid))
        comp_id  = _det_id("v_azom_comp", str(aid))
        proc_id  = _det_id("v_azom_proc", str(aid))
        prop_id  = _det_id("v_azom_prop", str(aid))

        route = cfg["route"]
        proc_data = parsed["proc_data"]

        processing: List[Dict] = []
        if route:
            proc_rec: Dict[str, Any] = {
                "processing_id": proc_id,
                "steel_id":      steel_id,
                "route_type":    route,
                "notes":         f"AZoM ArticleID={aid}. {grade}.",
            }
            if "austenitize_temp_C" in proc_data:
                proc_rec["austenitize_temp_C"] = proc_data["austenitize_temp_C"]
            if "quench_medium" in proc_data:
                proc_rec["quench_medium"] = proc_data["quench_medium"]
            elif route == "QT":
                proc_rec["quench_medium"] = "other"
            if "temper_temp_C" in proc_data:
                proc_rec["temper_temp_C"] = proc_data["temper_temp_C"]
            processing.append(proc_rec)

        prop: Dict[str, Any] = {
            "property_id":  prop_id,
            "steel_id":     steel_id,
            "processing_id": proc_id if processing else None,
            "test_temp_C":  25.0,
        }
        if parsed["uts"]   is not None: prop["uts_MPa"]             = parsed["uts"]
        if parsed["ys"]    is not None: prop["yield_strength_MPa"]  = parsed["ys"]
        if parsed["elong"] is not None: prop["elongation_pct"]      = parsed["elong"]
        if parsed["hb"]    is not None: prop["hardness_HB"]         = parsed["hb"]
        if parsed["hrc"]   is not None: prop["hardness_HRC"]        = parsed["hrc"]

        comp_record: Dict[str, Any] = {
            "steel_id":      steel_id,
            "composition_id": comp_id,
        }
        comp_record.update(parsed["comp"])

        records.append({
            "steel": {
                "steel_id":     steel_id,
                "grade":        grade,
                "steel_family": cfg["family"],
                "source_id":    SOURCE_ID,
                "notes":        f"AZoM ArticleID={aid}. URL: {SOURCE_URL}/article.aspx?ArticleID={aid}.",
            },
            "composition":   comp_record,
            "processing":    processing,
            "properties":    [prop],
            "microstructure": [],
        })

        if delay_s > 0:
            time.sleep(delay_s)

    logger.info(f"AZoM scraper: {len(records)} records parsed")
    return records
