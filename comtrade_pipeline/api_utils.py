"""
Helpers for UN Comtrade API requests: retries, HS-code cache, chunking, CSV export,
truncation detection, failure tracking and a small per-request disk cache.
"""

import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional

import pandas as pd

from .config import get_output_dir

import comtradeapicall

logger = logging.getLogger("comtrade_pipeline")

MAX_RECORDS = 250000  # hard API cap per request
NON_RETRYABLE = ("400", "401", "403", "404")
CODE_COLUMNS = {c: str for c in ("period", "cmdCode", "reporterCode", "partnerCode", "partner2Code", "flowCode")}


def safe_api_call(func: Callable, *args, max_retries: int = 3, retry_delay: float = 3.0, **kwargs) -> Any:
    """
    Call ``func`` with retries and exponential backoff.
    Retries network errors, 5xx and 429 (longer wait); fails fast on 400/401/403/404.
    """
    delay = retry_delay
    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - library raises assorted exception types
            last_err = e
            msg = str(e)
            logger.warning("ความพยายามที่ %d/%d ล้มเหลว: %s", attempt, max_retries, msg)
            if "429" not in msg and any(code in msg for code in NON_RETRYABLE):
                logger.error("ข้อผิดพลาดที่ลองใหม่ไม่ได้ (ตรวจสอบ API Key/พารามิเตอร์)")
                raise
            if attempt < max_retries:
                wait = max(delay, 5.0) * 1.5 if ("429" in msg or "Too Many Requests" in msg) else delay
                logger.info("จะลองใหม่ใน %.1f วินาที...", wait)
                time.sleep(wait)
                delay = wait * 1.5
    logger.error("การเรียก API ล้มเหลวถาวรหลังพยายาม %d ครั้ง: %s", max_retries, last_err)
    raise last_err  # type: ignore[misc]


def warn_if_truncated(df: Optional[pd.DataFrame], max_records: int = MAX_RECORDS, label: str = "") -> bool:
    """Log a warning and return True if the response hit the maxRecords cap."""
    if df is not None and len(df) >= max_records:
        logger.warning("⚠️ ข้อมูลอาจถูกตัดทิ้ง (%s แถว = maxRecords) %s - ควรแบ่งคำขอให้เล็กลง", f"{len(df):,}", label)
        return True
    return False


def save_failures(failures: List[dict], output_path: Path) -> None:
    """Write failed requests to CSV so they can be retried."""
    if not failures:
        return
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(failures).to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.warning("มี %d คำขอที่ล้มเหลว บันทึกรายการไว้ที่: %s", len(failures), output_path)


def cached_fetch(cache_key: str, fetch: Callable[[], Optional[pd.DataFrame]], use_cache: bool = True) -> Optional[pd.DataFrame]:
    """
    Run ``fetch`` and persist non-empty results under ``<output>/.cache``; later runs reuse
    them, so an interrupted download resumes where it stopped.
    """
    cache_dir = get_output_dir() / ".cache"
    path = cache_dir / (hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:16] + ".csv.gz")
    if use_cache and path.is_file():
        try:
            logger.info("ใช้ข้อมูลจากแคช: %s", cache_key)
            return pd.read_csv(path, dtype=CODE_COLUMNS)
        except Exception as e:  # noqa: BLE001
            logger.warning("อ่านแคชไม่สำเร็จ (%s) ดึงใหม่", e)
    df = fetch()
    if df is not None and not df.empty:
        cache_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False, compression="gzip")
    return df


def get_hs_codes(chapter: str = "07", code_length: int = 6, force_refresh: bool = False) -> List[str]:
    """Return HS codes of ``code_length`` digits under ``chapter`` (cached in metadata_hscodes.csv)."""
    cache_path = get_output_dir() / "metadata_hscodes.csv"

    df_hs = None
    if cache_path.is_file() and not force_refresh:
        try:
            df_hs = pd.read_csv(cache_path, dtype=str)
        except Exception as e:  # noqa: BLE001
            logger.warning("อ่านแคชไม่สำเร็จ (%s) จะดึงใหม่จาก API...", e)

    if df_hs is None or df_hs.empty:
        logger.info("กำลังดาวน์โหลดพจนานุกรมรหัส HS จาก UN Comtrade API...")
        df_hs = safe_api_call(comtradeapicall.getReference, "cmd:HS")
        if df_hs is None or df_hs.empty:
            return []
        df_hs = df_hs.rename(columns={"id": "HSCode", "text": "Description", "parent": "ParentCode"})
        df_hs.to_csv(cache_path, index=False, encoding="utf-8-sig")

    codes = df_hs["HSCode"].astype(str)
    matched = codes[(codes.str.len() == code_length) & codes.str.startswith(chapter)].tolist()
    logger.info("พบรหัส HS %d หลัก หมวด %s ทั้งหมด %d รหัส", code_length, chapter, len(matched))
    return matched


def chunk_list(items: List[Any], chunk_size: int = 20) -> List[List[Any]]:
    """Split ``items`` into chunks of at most ``chunk_size``."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


def export_dataframe_to_csv(df: pd.DataFrame, output_path: Path, preferred_columns: Optional[Iterable[str]] = None) -> Path:
    """Save ``df`` as UTF-8-BOM CSV (Excel friendly), keeping only ``preferred_columns`` that exist."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if preferred_columns:
        cols = [c for c in preferred_columns if c in df.columns]
        if cols:
            df = df[cols]
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info("บันทึกข้อมูล %s แถว เรียบร้อยที่: %s", f"{len(df):,}", output_path)
    return output_path
