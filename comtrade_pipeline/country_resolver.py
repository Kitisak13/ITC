"""
Universal Country Resolver:
Resolves ISO-3 Alpha codes (e.g. THA, USA, VNM), country names (e.g. Thailand, Vietnam),
and UN M49 numeric codes (e.g. 764, 842) into standardized (CountryCode, CountryName) tuples.
Uses local metadata cache for zero-latency offline resolution with online fallback.
"""

import logging
from typing import Dict, List, Optional, Tuple, Union
import pandas as pd

from .config import get_output_dir

logger = logging.getLogger("comtrade_pipeline")

# In-memory lookup tables for microsecond lookups
_LOOKUP_ISO3: Dict[str, Tuple[str, str]] = {}
_LOOKUP_CODE: Dict[str, Tuple[str, str]] = {}
_LOOKUP_NAME: Dict[str, Tuple[str, str]] = {}
_IS_INITIALIZED: bool = False


def _init_lookups():
    global _IS_INITIALIZED
    if _IS_INITIALIZED:
        return

    meta_file = get_output_dir() / "metadata_countries.csv"
    if not meta_file.is_file():
        return

    try:
        df = pd.read_csv(meta_file, dtype={"CountryCode": str})
        # Prioritize active entries over expired historical records
        valid = df[df["entryExpiredDate"].isna() & (df["isGroup"] == False)].copy()

        # Handle specific common aliases
        aliases = {
            "USA": ("842", "USA"),
            "UNITED STATES": ("842", "USA"),
            "VIETNAM": ("704", "Viet Nam"),
            "VIET NAM": ("704", "Viet Nam"),
            "RUSSIA": ("643", "Russian Federation"),
            "SOUTH KOREA": ("410", "Rep. of Korea"),
            "KOREA": ("410", "Rep. of Korea"),
            "UK": ("826", "United Kingdom"),
            "UAE": ("784", "United Arab Emirates"),
        }

        for _, r in valid.iterrows():
            c_code = str(r["CountryCode"]).strip()
            c_name = str(r["CountryName"]).strip()
            iso3 = str(r.get("PartnerCodeIsoAlpha3", "")).strip().upper()

            entry = (c_code, c_name)
            _LOOKUP_CODE[c_code] = entry
            _LOOKUP_NAME[c_name.upper()] = entry
            if iso3 and iso3 != "NAN":
                _LOOKUP_ISO3[iso3] = entry

        # Apply specific high-priority aliases
        for alias_name, entry in aliases.items():
            _LOOKUP_NAME[alias_name] = entry

        _IS_INITIALIZED = True
    except Exception as e:
        logger.warning("ไม่สามารถโหลดตารางแปลงรหัสประเทศ: %s", e)


def resolve_country(identifier: str) -> Optional[Tuple[str, str]]:
    """
    Resolve a single identifier (ISO3, Name, or M49 Code) to (CountryCode, CountryName).
    Example:
        resolve_country('THA') -> ('764', 'Thailand')
        resolve_country('Vietnam') -> ('704', 'Viet Nam')
        resolve_country('842') -> ('842', 'USA')
    """
    _init_lookups()
    raw = str(identifier).strip()
    if not raw:
        return None

    # 1. Match UN M49 numeric code
    if raw.isdigit() and raw in _LOOKUP_CODE:
        return _LOOKUP_CODE[raw]

    # 2. Match ISO3 Alpha (3 letters)
    upper_raw = raw.upper()
    if len(upper_raw) == 3 and upper_raw in _LOOKUP_ISO3:
        return _LOOKUP_ISO3[upper_raw]

    # 3. Match Country Name exact
    if upper_raw in _LOOKUP_NAME:
        return _LOOKUP_NAME[upper_raw]

    # 4. Match Country Name contains (case-insensitive substring)
    for name_key, entry in _LOOKUP_NAME.items():
        if upper_raw in name_key or name_key in upper_raw:
            return entry

    # 5. Fallback online if comtradeapicall has convertCountryIso3ToCode
    if len(upper_raw) == 3:
        try:
            import comtradeapicall
            code = comtradeapicall.convertCountryIso3ToCode(upper_raw)
            if code and code.strip():
                return (code.strip(), raw)
        except Exception:
            pass

    return None


def resolve_countries(identifiers: Union[str, List[str]]) -> List[Dict[str, str]]:
    """
    Resolve multiple country identifiers from a comma-separated string or list.
    Example:
        resolve_countries("THA, VNM, USA, Japan")
        -> [{'code': '764', 'name': 'Thailand'}, {'code': '704', 'name': 'Viet Nam'}, ...]
    """
    if isinstance(identifiers, str):
        items = [i.strip() for i in identifiers.split(",") if i.strip()]
    else:
        items = [str(i).strip() for i in identifiers if str(i).strip()]

    resolved_list = []
    seen_codes = set()

    for item in items:
        # Check if user passed "Name:Code" format
        if ":" in item:
            name_part, code_part = item.split(":", 1)
            c_code = code_part.strip()
            c_name = name_part.strip()
            if c_code not in seen_codes:
                seen_codes.add(c_code)
                resolved_list.append({"code": c_code, "name": c_name})
            continue

        res = resolve_country(item)
        if res:
            c_code, c_name = res
            if c_code not in seen_codes:
                seen_codes.add(c_code)
                resolved_list.append({"code": c_code, "name": c_name})
        else:
            logger.warning("⚠️ ไม่พบข้อมูลประเทศสำหรับ '%s'", item)

    return resolved_list
