"""World imports at HS 6-digit level (all reporters, partner = World) for a chapter."""

import logging
import time
from pathlib import Path
from typing import List, Optional

import pandas as pd

import comtradeapicall

from .api_utils import (MAX_RECORDS, cached_fetch, chunk_list, export_dataframe_to_csv, get_hs_codes,
                        safe_api_call, save_failures, warn_if_truncated)
from .config import get_api_key, get_output_dir

logger = logging.getLogger("comtrade_pipeline")

DEFAULT_YEARS = ["2022", "2023", "2024", "2025"]
DEFAULT_COLUMNS = ["period", "reporterCode", "reporterDesc", "partnerDesc", "cmdCode", "cmdDesc",
                   "primaryValue", "netWgt", "qty", "qtyUnitAbbr"]


def _fetch_codes(key: str, year: str, codes: List[str], delay: float) -> Optional[pd.DataFrame]:
    """Fetch one set of HS codes; if the cap is hit, split the set in half and retry recursively."""
    df = safe_api_call(
        comtradeapicall.getFinalData,
        subscription_key=key, typeCode="C", freqCode="A", clCode="HS", period=str(year),
        reporterCode=None, cmdCode=",".join(codes), flowCode="M", partnerCode="0",
        partner2Code=None, customsCode=None, motCode=None, maxRecords=MAX_RECORDS,
        format_output="JSON", aggregateBy=None, breakdownMode="classic", countOnly=None, includeDesc=True,
    )
    if df is not None and len(df) >= MAX_RECORDS:
        if len(codes) > 1:
            mid = len(codes) // 2
            logger.warning("ผลลัพธ์ถึงขีดจำกัด %s แถว แบ่งชุดรหัสครึ่งหนึ่งแล้วดึงใหม่", f"{MAX_RECORDS:,}")
            time.sleep(delay)
            parts = [_fetch_codes(key, year, codes[:mid], delay), _fetch_codes(key, year, codes[mid:], delay)]
            parts = [p for p in parts if p is not None and not p.empty]
            return pd.concat(parts, ignore_index=True) if parts else None
        warn_if_truncated(df, MAX_RECORDS, f"(ปี {year}, รหัส {codes[0]})")
    return df


def download_import_world(
    chapter: str = "07",
    years: Optional[List[str]] = None,
    api_key: Optional[str] = None,
    output_file: Optional[Path] = None,
    delay_between_requests: float = 2.0,
    chunk_size: int = 20,
    use_cache: bool = True,
) -> Optional[pd.DataFrame]:
    """Download world imports for every HS6 code in ``chapter``; resumable via the request cache."""
    years = [str(y) for y in (years or DEFAULT_YEARS)]
    output_file = Path(output_file) if output_file else get_output_dir() / f"import_{chapter}_world.csv"
    key = get_api_key(api_key)

    hs_codes = get_hs_codes(chapter=chapter, code_length=6)
    if not hs_codes:
        logger.error("ไม่พบรหัส HS 6 หลักสำหรับหมวด '%s'", chapter)
        return None

    chunks = chunk_list(hs_codes, chunk_size)
    total = len(years) * len(chunks)
    logger.info("🚀 หมวด %s | ปี %s | %d รหัส | %d คำขอ | -> %s",
                chapter, ",".join(years), len(hs_codes), total, output_file)

    frames, failures, n = [], [], 0
    for year in years:
        for i, chunk in enumerate(chunks, 1):
            n += 1
            label = f"[{n}/{total}] ปี {year} ชุด {i}/{len(chunks)} ({chunk[0]}-{chunk[-1]})"
            fetched_remote = []

            def fetch(year=year, chunk=chunk):
                fetched_remote.append(True)
                return _fetch_codes(key, year, chunk, delay_between_requests)

            try:
                df = cached_fetch(f"world_import|{chapter}|{year}|{','.join(chunk)}", fetch, use_cache)
                if df is not None and not df.empty:
                    frames.append(df)
                    logger.info("%s ✅ %s แถว", label, f"{len(df):,}")
                else:
                    logger.info("%s ⚠️ ไม่มีข้อมูล", label)
            except Exception as e:  # noqa: BLE001
                logger.error("%s ❌ %s", label, e)
                failures.append({"year": year, "cmdCodes": ",".join(chunk), "error": str(e)})
            if fetched_remote:  # throttle only after real network calls
                time.sleep(delay_between_requests)

    save_failures(failures, output_file.with_name(output_file.stem + "_failed_requests.csv"))
    if not frames:
        logger.warning("ไม่มีข้อมูลถูกดึงมาได้เลย กรุณาตรวจสอบ API Key หรือช่วงปีที่เลือก")
        return None
    final_df = pd.concat(frames, ignore_index=True)
    export_dataframe_to_csv(final_df, output_file, DEFAULT_COLUMNS)
    logger.info("🎉 เสร็จสมบูรณ์ รวม %s แถว", f"{len(final_df):,}")
    return final_df

