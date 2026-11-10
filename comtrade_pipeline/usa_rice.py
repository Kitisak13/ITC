"""Monthly USA rice (HS 1006) imports and exports."""

import logging
import time
from datetime import date
from typing import List, Optional

import pandas as pd

import comtradeapicall

from .api_utils import MAX_RECORDS, export_dataframe_to_csv, safe_api_call, save_failures
from .config import get_api_key, get_output_dir

logger = logging.getLogger("comtrade_pipeline")

REPORTER_USA = "842"
CMD_CODES = "1006,100610,100620,100630,100640"
COLUMNS_TO_KEEP = ["period", "reporterCode", "reporterDesc", "partnerCode", "partnerDesc", "cmdCode", "cmdDesc",
                   "flowCode", "flowDesc", "primaryValue", "netWgt", "qty", "qtyUnitAbbr"]


def generate_monthly_periods(year: int) -> str:
    """'YYYY01,...,YYYY12' (API allows 12 periods per request)."""
    return ",".join(f"{year}{m:02d}" for m in range(1, 13))


def fetch_usa_rice_data(flow_code: str, years: List[int], api_key: Optional[str] = None,
                        delay: float = 2.0) -> pd.DataFrame:
    """Fetch monthly rice data for one flow ('M' or 'X'); failures are logged to a CSV."""
    key = get_api_key(api_key)
    frames, failures = [], []
    for year in years:
        try:
            df = safe_api_call(
                comtradeapicall.getFinalData,
                subscription_key=key, typeCode="C", freqCode="M", clCode="HS",
                period=generate_monthly_periods(year), reporterCode=REPORTER_USA, cmdCode=CMD_CODES,
                flowCode=flow_code, partnerCode=None, partner2Code=None, customsCode=None, motCode=None,
                maxRecords=MAX_RECORDS, format_output="JSON", aggregateBy=None, breakdownMode="classic",
                countOnly=None, includeDesc=True,
            )
            if df is not None and not df.empty:
                logger.info("flow=%s ปี %s ✅ %s แถว", flow_code, year, f"{len(df):,}")
                frames.append(df)
            else:
                logger.info("flow=%s ปี %s ⚠️ ไม่มีข้อมูล", flow_code, year)
        except Exception as e:  # noqa: BLE001
            logger.error("flow=%s ปี %s ❌ %s", flow_code, year, e)
            failures.append({"flow": flow_code, "year": year, "error": str(e)})
        time.sleep(delay)

    save_failures(failures, get_output_dir() / f"usa_rice_{flow_code}_failed_requests.csv")
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df[[c for c in COLUMNS_TO_KEEP if c in df.columns]]
    sort_cols = [c for c in ("period", "cmdCode", "partnerDesc") if c in df.columns]
    return df.sort_values(sort_cols) if sort_cols else df


def download_usa_rice_monthly(start_year: int = 2025, end_year: Optional[int] = None,
                              api_key: Optional[str] = None) -> None:
    """Download USA rice imports and exports (monthly) to two CSV files."""
    end_year = end_year or date.today().year
    years = list(range(start_year, end_year + 1))
    tag = f"{years[0]}_{years[-1]}"
    for flow, name in (("M", "import"), ("X", "export")):
        df = fetch_usa_rice_data(flow, years, api_key)
        if df.empty:
            logger.warning("⚠️ ไม่สามารถดึงข้อมูล %s ได้", name)
            continue
        export_dataframe_to_csv(df, get_output_dir() / f"usa_{name}_1006_monthly_{tag}.csv")

