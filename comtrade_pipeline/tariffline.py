"""National tariff-line (8-11 digit) data for selected reporters."""

import logging
import time
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

import comtradeapicall

from .api_utils import (MAX_RECORDS, export_dataframe_to_csv, safe_api_call, save_failures, warn_if_truncated)
from .config import get_api_key, get_output_dir

logger = logging.getLogger("comtrade_pipeline")

from .country_resolver import resolve_countries

DEFAULT_COUNTRIES = {"USA": "842", "Russia": "643"}
DEFAULT_COLUMNS = ["period", "reporterDesc", "partnerDesc", "cmdCode", "cmdDesc",
                   "primaryValue", "netWgt", "qty", "qtyUnitAbbr"]


def parse_country_args(arg_str: str) -> Dict[str, str]:
    """Parse 'USA:842,Russia:643', ISO3 'USA,RUS,THA', or '842,643' into {name: code}."""
    resolved = resolve_countries(arg_str)
    if resolved:
        return {c["name"]: c["code"] for c in resolved}

    countries: Dict[str, str] = {}
    for item in arg_str.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            name, code = item.split(":", 1)
            countries[name.strip()] = code.strip()
        else:
            countries[f"Country_{item}"] = item
    return countries


def download_tariffline_imports(
    countries: Optional[Dict[str, str]] = None,
    cmd_code: str = "07",
    period: str = "2021,2022,2023,2024,2025",
    flow_code: str = "M",
    api_key: Optional[str] = None,
    output_file: Optional[Path] = None,
    delay_between_requests: float = 2.0,
) -> Optional[pd.DataFrame]:
    """Download tariff-line data (codes longer than 6 digits only) for each country."""
    countries = countries or DEFAULT_COUNTRIES
    output_file = Path(output_file) if output_file else get_output_dir() / f"tariffline_{flow_code}_{cmd_code}.csv"
    key = get_api_key(api_key)
    logger.info("🚀 Tariff line หมวด %s | %s | ช่วง %s", cmd_code,
                ", ".join(f"{k} ({v})" for k, v in countries.items()), period)

    frames, failures = [], []
    for idx, (name, code) in enumerate(countries.items(), 1):
        label = f"[{idx}/{len(countries)}] {name} ({code})"
        try:
            df = safe_api_call(
                comtradeapicall.getTarifflineData,
                subscription_key=key, typeCode="C", freqCode="A", clCode="HS", period=period,
                reporterCode=str(code), cmdCode=str(cmd_code), flowCode=flow_code, partnerCode=None,
                partner2Code=None, customsCode=None, motCode=None, maxRecords=MAX_RECORDS,
                format_output="JSON", countOnly=None, includeDesc=True,
            )
            if df is None or df.empty:
                logger.info("%s ⚠️ ไม่พบข้อมูล", label)
            else:
                warn_if_truncated(df, MAX_RECORDS, f"({name})")
                deep = df[df["cmdCode"].astype(str).str.len() > 6]
                if deep.empty:
                    logger.warning("%s ไม่มีรหัสเกิน 6 หลัก ข้ามประเทศนี้", label)
                else:
                    logger.info("%s ✅ %s รายการ (จากทั้งหมด %s)", label, f"{len(deep):,}", f"{len(df):,}")
                    frames.append(deep)
        except Exception as e:  # noqa: BLE001
            logger.error("%s ❌ %s", label, e)
            failures.append({"country": name, "code": code, "error": str(e)})
        time.sleep(delay_between_requests)

    save_failures(failures, output_file.with_name(output_file.stem + "_failed_requests.csv"))
    if not frames:
        logger.warning("ไม่มีข้อมูล Tariff line ถูกดึงมาได้เลย")
        return None
    final_df = pd.concat(frames, ignore_index=True)
    export_dataframe_to_csv(final_df, output_file, DEFAULT_COLUMNS)
    return final_df

