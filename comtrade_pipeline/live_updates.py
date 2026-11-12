"""
Smart Live Updates & Release Tracking:
Monitors live data releases from UN Comtrade using getLiveUpdate and getComtradeReleases.
Automatically discovers which countries have published new data and triggers
targeted incremental updates only for those countries, saving massive API quota.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
import pandas as pd

import comtradeapicall

from .api_utils import safe_api_call
from .config import get_api_key, get_output_dir
from .country_resolver import resolve_country
from .country_rice import QuotaTracker, process_country_rice_file

logger = logging.getLogger("comtrade_pipeline")


def fetch_comtrade_releases(api_key: Optional[str] = None, use_public: bool = False) -> pd.DataFrame:
    """
    Fetches the latest release log from UN Comtrade.
    Tries authenticated getLiveUpdate first, falls back to public getComtradeReleases.
    """
    df = None
    if not use_public:
        try:
            key = get_api_key(api_key)
            logger.info("กำลังเรียกตรวจสอบการปล่อยข้อมูลใหม่ผ่าน getLiveUpdate()...")
            df = safe_api_call(comtradeapicall.getLiveUpdate, subscription_key=key)
        except Exception as e:
            logger.warning("getLiveUpdate ไม่สำเร็จ (%s) สลับไปใช้ getComtradeReleases (Public)...", e)

    if df is None or df.empty:
        try:
            logger.info("กำลังเรียกตรวจสอบผ่าน getComtradeReleases (Public)...")
            # Note: getComtradeReleases might be in v1.4.0
            if hasattr(comtradeapicall, "getComtradeReleases"):
                df = safe_api_call(comtradeapicall.getComtradeReleases)
            elif hasattr(comtradeapicall, "DataAvailability") and hasattr(comtradeapicall.DataAvailability, "getComtradeReleases"):
                df = safe_api_call(comtradeapicall.DataAvailability.getComtradeReleases)
        except Exception as e:
            logger.error("❌ ไม่สามารถดึงข้อมูล Releases: %s", e)
            return pd.DataFrame()

    if df is not None and not df.empty:
        # Standardize reporterCode column
        if "reporterCode" in df.columns:
            df["reporterCode"] = df["reporterCode"].astype(str)
        return df
    return pd.DataFrame()


def get_recently_updated_reporters(
    days_back: int = 30,
    api_key: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    Returns a list of countries that published new commodity trade data within the last N days.
    """
    df = fetch_comtrade_releases(api_key=api_key)
    if df.empty:
        return []

    # Filter commodity data (typeCode == 'C')
    if "typeCode" in df.columns:
        df = df[df["typeCode"] == "C"]

    # Filter by publication date if available
    date_col = next((c for c in ["publicationDate", "publishedDate", "releaseDate"] if c in df.columns), None)
    if date_col:
        try:
            cutoff = datetime.now() - timedelta(days=days_back)
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df[df[date_col] >= cutoff]
        except Exception as e:
            logger.warning("กรองวันที่ไม่สำเร็จ (%s) จะใช้ข้อมูลทั้งหมดที่ส่งกลับมา", e)

    if "reporterCode" not in df.columns:
        return []

    unique_reporters: Set[str] = set(df["reporterCode"].dropna().unique())
    updated_countries = []

    for r_code in unique_reporters:
        res = resolve_country(r_code)
        if res:
            updated_countries.append({"code": res[0], "name": res[1]})
        else:
            updated_countries.append({"code": r_code, "name": f"Country_{r_code}"})

    return updated_countries


def run_smart_incremental_update(
    days_back: int = 30,
    end_year: Optional[int] = None,
    api_key: Optional[str] = None,
    delay: float = 1.0,
) -> None:
    """
    Smart Update:
    1. Checks getLiveUpdate to see which countries released data in the last N days.
    2. Filters only countries that exist in our target rice files / catalog.
    3. Triggers incremental update only for those specific countries!
    """
    target_year = end_year or datetime.now().year
    out_dir = get_output_dir() / "by_country"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 70)
    print("🛰️ เริ่มต้นระบบ Smart Incremental Update (ตรวจจับข้อมูลใหม่ก่อนยิง API)")
    print(f"📅 ย้อนหลัง: {days_back} วัน | ปีที่เป้าหมายอัปเดต: {target_year}")
    print("=" * 70)

    updated_reporters = get_recently_updated_reporters(days_back=days_back, api_key=api_key)
    if not updated_reporters:
        logger.info("ℹ️ ไม่พบประเทศที่มีการปล่อยข้อมูลใหม่ในรอบ %d วันที่ผ่านมา หรือบริการยังไม่อัปเดต", days_back)
        return

    print(f"\n✅ ตรวจพบ {len(updated_reporters)} ประเทศที่มีการอัปเดตข้อมูลในรอบ {days_back} วัน:")
    for c in updated_reporters[:10]:
        print(f"  • {c['name']} (Code: {c['code']})")
    if len(updated_reporters) > 10:
        print(f"  ... และอีก {len(updated_reporters) - 10} ประเทศ")

    # Match with countries we track in output/by_country
    tracked_files = {f.stem.lower(): f for f in out_dir.glob("*.xlsx")}
    matched_to_update = []
    for c in updated_reporters:
        if c["name"].lower() in tracked_files or c["code"] in tracked_files:
            matched_to_update.append(c)

    if not matched_to_update:
        logger.info("ℹ️ ประเทศที่อัปเดตใหม่ไม่มีในโฟลเดอร์ output/by_country/ (หรือคุณสามารถระบุประเทศเพื่อเพิ่มใหม่ได้)")
        return

    print(f"\n🎯 พบ {len(matched_to_update)} ประเทศในระบบของเราที่ต้องดึงข้อมูลใหม่:")
    for c in matched_to_update:
        print(f"  👉 จะอัปเดต: {c['name']} (Code: {c['code']})")

    quota_tracker = QuotaTracker(max_requests=485)
    for idx, c in enumerate(matched_to_update, 1):
        if not quota_tracker.can_proceed(2):
            logger.warning("🛑 โควต้าประจำวันใกล้เต็ม หยุดการอัปเดตชั่วคราว")
            break

        print(f"\n[{idx}/{len(matched_to_update)}] อัปเดตข้อมูลข้าว: {c['name']} (ปี {target_year})...")
        process_country_rice_file(
            country_code=c["code"],
            country_name=c["name"],
            years=[target_year],
            output_dir=out_dir,
            quota_tracker=quota_tracker,
            incremental=True,
            force_overwrite=False,
            api_key=api_key,
            delay=delay,
        )

    print("\n" + "=" * 70)
    print("🎉 Smart Incremental Update เสร็จสิ้นเรียบร้อย!")
    print(f"📊 ประหยัดโควต้า: ใช้ไปเพียง {quota_tracker.used_requests} Requests (ดึงเฉพาะประเทศที่มีของใหม่)")
    print("=" * 70)
