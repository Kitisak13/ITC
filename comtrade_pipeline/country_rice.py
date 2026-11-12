"""
Monthly country-by-country rice (HS 1006) imports and exports downloader.
Saves data into Excel files (output/by_country/<CountryName>.xlsx)
with two sheets: 'Import' and 'Export'.
Supports batch execution by group, custom ISO3/Country lists, quota limits,
and incremental monthly updates.
"""

import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

import comtradeapicall

from .api_utils import MAX_RECORDS, safe_api_call
from .config import get_api_key, get_output_dir
from .country_groups import TOP_35_RICE_COUNTRIES, load_all_country_groups
from .country_resolver import resolve_countries

logger = logging.getLogger("comtrade_pipeline")

CMD_CODES = "1006,100610,100620,100630,100640"
COLUMNS_TO_KEEP = [
    "period",
    "reporterCode",
    "reporterDesc",
    "partnerCode",
    "partnerDesc",
    "cmdCode",
    "cmdDesc",
    "flowCode",
    "flowDesc",
    "primaryValue",
    "netWgt",
    "qty",
    "qtyUnitAbbr",
]


def sanitize_filename(name: str) -> str:
    """Sanitize country name for safe cross-platform filesystem filenames."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", name).strip()
    return cleaned or "Unknown_Country"


def generate_monthly_periods(year: int) -> str:
    """'YYYY01,...,YYYY12' (12 monthly periods per request)."""
    return ",".join(f"{year}{m:02d}" for m in range(1, 13))


class QuotaTracker:
    """Tracks API requests across the session to prevent exceeding daily limits."""

    def __init__(self, max_requests: int = 485):
        self.max_requests = max_requests
        self.used_requests = 0

    def can_proceed(self, needed: int = 1) -> bool:
        return (self.used_requests + needed) <= self.max_requests

    def increment(self, count: int = 1):
        self.used_requests += count


def fetch_country_rice_flow(
    country_code: str,
    country_name: str,
    flow_code: str,
    years: List[int],
    quota_tracker: QuotaTracker,
    api_key: Optional[str] = None,
    delay: float = 1.0,
) -> pd.DataFrame:
    """Fetches rice data for one flow (M or X) for a country across given years."""
    key = get_api_key(api_key)
    frames = []

    for year in years:
        if not quota_tracker.can_proceed(1):
            logger.warning(
                "🛑 โควต้าประจำวันใกล้เต็ม (%d/%d) หยุดการเรียก API ชั่วคราวเพื่อความปลอดภัย",
                quota_tracker.used_requests,
                quota_tracker.max_requests,
            )
            break

        try:
            df = safe_api_call(
                comtradeapicall.getFinalData,
                subscription_key=key,
                typeCode="C",
                freqCode="M",
                clCode="HS",
                period=generate_monthly_periods(year),
                reporterCode=str(country_code),
                cmdCode=CMD_CODES,
                flowCode=flow_code,
                partnerCode=None,
                partner2Code=None,
                customsCode=None,
                motCode=None,
                maxRecords=MAX_RECORDS,
                format_output="JSON",
                aggregateBy=None,
                breakdownMode="classic",
                countOnly=None,
                includeDesc=True,
            )
            quota_tracker.increment(1)

            if df is not None and not df.empty:
                logger.info(
                    "    -> [%s] ปี %s flow=%s: ✅ %s แถว",
                    country_name,
                    year,
                    flow_code,
                    f"{len(df):,}",
                )
                frames.append(df)
            else:
                logger.info("    -> [%s] ปี %s flow=%s: (ไม่มีข้อมูล)", country_name, year, flow_code)

        except Exception as e:
            quota_tracker.increment(1)
            logger.error("    -> [%s] ปี %s flow=%s: ❌ %s", country_name, year, flow_code, e)

        time.sleep(delay)

    if not frames:
        return pd.DataFrame(columns=COLUMNS_TO_KEEP)

    combined = pd.concat(frames, ignore_index=True)
    existing_cols = [c for c in COLUMNS_TO_KEEP if c in combined.columns]
    combined = combined[existing_cols]
    sort_cols = [c for c in ("period", "cmdCode", "partnerDesc") if c in combined.columns]
    return combined.sort_values(sort_cols) if sort_cols else combined


def process_country_rice_file(
    country_code: str,
    country_name: str,
    years: List[int],
    output_dir: Path,
    quota_tracker: QuotaTracker,
    incremental: bool = False,
    force_overwrite: bool = False,
    api_key: Optional[str] = None,
    delay: float = 1.0,
) -> bool:
    """
    Downloads or incrementally updates an Excel file for a single country.
    Creates 2 sheets: 'Import' and 'Export'.
    """
    safe_name = sanitize_filename(country_name)
    excel_path = output_dir / f"{safe_name}.xlsx"

    # Check if already complete and not force/incremental
    if excel_path.is_file() and not force_overwrite and not incremental:
        logger.info("⏩ [%s] มีไฟล์อยู่แล้ว ข้ามเพื่อประหยัดโควต้า: %s", country_name, excel_path.name)
        return True

    # If incremental, load existing data
    old_imports = pd.DataFrame()
    old_exports = pd.DataFrame()
    if incremental and excel_path.is_file():
        try:
            with pd.ExcelFile(excel_path) as xls:
                if "Import" in xls.sheet_names:
                    old_imports = pd.read_excel(xls, "Import")
                if "Export" in xls.sheet_names:
                    old_exports = pd.read_excel(xls, "Export")
            logger.info("📂 [%s] โหลดข้อมูลเดิมสำเร็จเพื่อเตรียมต่อข้อมูลใหม่ (Incremental)", country_name)
        except Exception as e:
            logger.warning("⚠️ ไม่สามารถอ่านไฟล์เดิมของ [%s] (%s) จะดึงใหม่ทั้งหมด", country_name, e)

    # Fetch new data
    logger.info("🌍 กำลังประมวลผล: [%s] (Code: %s)...", country_name, country_code)
    new_imports = fetch_country_rice_flow(country_code, country_name, "M", years, quota_tracker, api_key, delay)
    new_exports = fetch_country_rice_flow(country_code, country_name, "X", years, quota_tracker, api_key, delay)

    # Merge if incremental
    def merge_frames(old_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
        if old_df.empty:
            return new_df
        if new_df.empty:
            return old_df
        merged = pd.concat([old_df, new_df], ignore_index=True)
        dedup_keys = [c for c in ("period", "partnerCode", "cmdCode", "flowCode") if c in merged.columns]
        if dedup_keys:
            merged = merged.drop_duplicates(subset=dedup_keys, keep="last")
        sort_cols = [c for c in ("period", "cmdCode", "partnerDesc") if c in merged.columns]
        return merged.sort_values(sort_cols) if sort_cols else merged

    final_imports = merge_frames(old_imports, new_imports)
    final_exports = merge_frames(old_exports, new_exports)

    # Save to Excel with 2 sheets
    try:
        excel_path.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            final_imports.to_excel(writer, sheet_name="Import", index=False)
            final_exports.to_excel(writer, sheet_name="Export", index=False)
        logger.info(
            "💾 บันทึกไฟล์สำเร็จ: %s (Import: %s แถว | Export: %s แถว)",
            excel_path.name,
            f"{len(final_imports):,}",
            f"{len(final_exports):,}",
        )
        return True
    except Exception as e:
        logger.error("❌ บันทึกไฟล์ Excel ของ [%s] ล้มเหลว: %s", country_name, e)
        return False


def download_country_rice_group(
    group_number: int = 1,
    start_year: int = 2020,
    end_year: int = 2026,
    incremental: bool = False,
    force_overwrite: bool = False,
    countries: Optional[Union[str, List[str]]] = None,
    api_key: Optional[str] = None,
    delay: float = 1.0,
) -> None:
    """
    Downloads rice data for a specific group OR a custom country list (supports ISO3 e.g. THA,VNM,USA).
    Saves to output/by_country/<CountryName>.xlsx
    """
    out_dir = get_output_dir() / "by_country"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Determine countries
    if countries:
        country_list = resolve_countries(countries)
        if not country_list:
            logger.error("❌ ไม่สามารถแปลงรหัสประเทศจาก '%s'", countries)
            return
        target_title = f"ประเทศเฉพาะเจาะจง ({len(country_list)} ประเทศ: {', '.join([c['name'] for c in country_list])})"
    else:
        groups = load_all_country_groups()
        if group_number not in groups:
            logger.error("❌ ไม่พบ Group %d (กลุ่มที่สามารถเลือกได้: 1 ถึง %d)", group_number, max(groups.keys()))
            return
        country_list = groups[group_number]
        target_title = f"Group {group_number} ({len(country_list)} ประเทศ)"

    # If incremental, only fetch the current/latest year to minimize requests
    years = [end_year] if incremental else list(range(start_year, end_year + 1))

    logger.info("=" * 65)
    logger.info("🚀 เริ่มการดึงข้อมูลข้าวรายประเทศ (Country Rice Pipeline)")
    logger.info("📦 กลุ่มเป้าหมาย: %s", target_title)
    logger.info("📅 ช่วงปี: %s (รายเดือน) | โหมด: %s", years, "Incremental" if incremental else "Full")
    logger.info("📁 บันทึกไฟล์ที่: %s", out_dir)
    logger.info("=" * 65)

    quota_tracker = QuotaTracker(max_requests=485)

    for idx, c in enumerate(country_list, 1):
        if not quota_tracker.can_proceed(2):
            logger.warning("🛑 โควต้าประจำวันใกล้เต็มแล้ว (%d requests) หยุดการดึงชั่วคราว", quota_tracker.used_requests)
            break

        print(f"\n[{idx}/{len(country_list)}] กำลังจัดการประเทศ: {c['name']} (Code: {c['code']})...")
        process_country_rice_file(
            country_code=c["code"],
            country_name=c["name"],
            years=years,
            output_dir=out_dir,
            quota_tracker=quota_tracker,
            incremental=incremental,
            force_overwrite=force_overwrite,
            api_key=api_key,
            delay=delay,
        )

    logger.info("\n" + "=" * 65)
    logger.info("🎉 สรุปการทำงานเสร็จสิ้น!")
    logger.info("📊 ใช้โควต้าคำขอ API ไปทั้งสิ้น: %d Requests", quota_tracker.used_requests)
    logger.info("📁 ดูผลลัพธ์ไฟล์ Excel ได้ที่: %s", out_dir)
    logger.info("=" * 65)
