"""
Google Drive Synchronization & Automated Pipeline Module:
Manages authentication (OAuth 2.0 with Refresh Token or Service Account),
downloads/uploads master CSV files on Google Drive, and synchronizes
incremental rice updates from UN Comtrade automatically.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .config import ConfigError, get_output_dir
from .country_rice import QuotaTracker, fetch_country_rice_flow, process_country_rice_file
from .live_updates import get_recently_updated_reporters

logger = logging.getLogger("comtrade_pipeline")

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]

STATE_FILE = Path("sync_state.json")

STANDARD_COLUMNS = [
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
CODE_COLUMNS = {"period", "reporterCode", "partnerCode", "cmdCode", "flowCode"}
NUMERIC_COLUMNS = ("primaryValue", "netWgt", "qty")
TEXT_COLUMNS = [c for c in STANDARD_COLUMNS if c not in NUMERIC_COLUMNS]
DEDUP_COLS = ["period", "reporterCode", "partnerCode", "cmdCode", "flowCode"]
SORT_COLS = ["period", "reporterDesc", "cmdCode", "partnerDesc"]


def get_gdrive_service():
    """
    Builds Google Drive API client using credentials from Environment / Secrets or local files.
    Priority:
      1. Service Account JSON (via GDRIVE_SERVICE_ACCOUNT_JSON env or service_account.json)
      2. OAuth 2.0 Refresh Token (via GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN env)
      3. Local token.json / credentials.json
    """
    from googleapiclient.discovery import build
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials

    # 1. Service Account
    sa_json_str = os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON")
    if sa_json_str:
        try:
            info = json.loads(sa_json_str)
            creds = service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            logger.warning("โหลด Service Account จาก GDRIVE_SERVICE_ACCOUNT_JSON ไม่สำเร็จ: %s", e)

    sa_file = Path("service_account.json")
    if sa_file.is_file():
        try:
            creds = service_account.Credentials.from_service_account_file(str(sa_file), scopes=DRIVE_SCOPES)
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            logger.warning("โหลด Service Account จาก %s ไม่สำเร็จ: %s", sa_file, e)

    # 2. OAuth 2.0 Headless (GitHub Actions / Cloud) via Refresh Token
    client_id = os.getenv("GDRIVE_CLIENT_ID")
    client_secret = os.getenv("GDRIVE_CLIENT_SECRET")
    refresh_token = os.getenv("GDRIVE_REFRESH_TOKEN")

    if client_id and client_secret and refresh_token:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=DRIVE_SCOPES,
        )
        return build("drive", "v3", credentials=creds)

    # 3. Local token.json
    token_file = Path("token.json")
    if token_file.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), scopes=DRIVE_SCOPES)
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            logger.warning("โหลด token.json ไม่สำเร็จ: %s", e)

    raise RuntimeError(
        "❌ ไม่พบข้อมูลการยืนยันตัวตน Google Drive!\n"
        "กรุณาตั้งค่า Repository Secrets (GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN) "
        "หรือรันคำสั่ง 'python run_pipeline.py gdrive-auth' เพื่อสร้างโทเคนบนเครื่องนี้ก่อน"
    )


def authorize_local_oauth(credentials_path: str = "credentials.json") -> None:
    """
    Interactive OAuth 2.0 authorization for local developer.
    Opens a browser to log in and prints the exact values for GitHub Repository Secrets.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    cred_file = Path(credentials_path)
    if not cred_file.is_file():
        print(f"\n❌ ไม่พบไฟล์ {credentials_path}")
        print("กรุณาดาวน์โหลด OAuth Client ID (ประเภท Desktop App) จาก Google Cloud Console แล้ววางไว้ที่นี่")
        return

    print("\n🌐 กำลังเปิดเบราว์เซอร์เพื่อเข้าสู่ระบบ Google Account...")
    flow = InstalledAppFlow.from_client_secrets_file(str(cred_file), scopes=DRIVE_SCOPES)
    creds = flow.run_local_server(port=0)

    # Save token.json
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    Path("token.json").write_text(json.dumps(token_data, indent=2), encoding="utf-8")
    print("✅ บันทึกโทเคนลงไฟล์ token.json เรียบร้อยแล้ว")

    # Print GitHub Secrets Helper
    print("\n" + "=" * 70)
    print("🔑 ข้อมูลสำหรับนำไปกรอกใน GitHub Repository Secrets:")
    print("=" * 70)
    print(f"GDRIVE_CLIENT_ID      : {creds.client_id}")
    print(f"GDRIVE_CLIENT_SECRET  : {creds.client_secret}")
    print(f"GDRIVE_REFRESH_TOKEN  : {creds.refresh_token}")
    print("=" * 70 + "\n")


def download_gdrive_file(service, file_id: str, destination_path: Path) -> Path:
    """Downloads a file from Google Drive by its fileId."""
    import io
    from googleapiclient.http import MediaIoBaseDownload

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)

    with open(destination_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024 * 5)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"  📥 กำลังดาวน์โหลด {destination_path.name}... {int(status.progress() * 100)}%", end="\r")

    print(f"  ✅ ดาวน์โหลดสำเร็จ: {destination_path.name} ({destination_path.stat().st_size / (1024*1024):.2f} MB)")
    return destination_path


def upload_update_gdrive_file(service, file_id: str, source_path: Path, mime_type: str = "text/csv") -> None:
    """Updates an existing Google Drive file in-place, preserving its File ID and URL."""
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(str(source_path), mimetype=mime_type, resumable=True)
    file_size_mb = source_path.stat().st_size / (1024 * 1024)

    print(f"  📤 กำลังอัปเดตไฟล์บน Google Drive ({source_path.name}, {file_size_mb:.2f} MB)...")
    updated = (
        service.files()
        .update(
            fileId=file_id,
            media_body=media,
            fields="id, name, modifiedTime",
            supportsAllDrives=True,
        )
        .execute()
    )
    print(f"  ✅ อัปเดตไฟล์บน Google Drive เรียบร้อย! (ID: {updated.get('id')})")


def load_sync_state() -> Dict:
    """Loads sync state metadata."""
    default_state: Dict = {
        "last_sync_time": None,
        "last_updated_countries": [],
        "country_releases": {},
    }
    if STATE_FILE.is_file():
        try:
            loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                default_state.update(loaded)
                if not isinstance(default_state.get("country_releases"), dict):
                    default_state["country_releases"] = {}
                return default_state
        except Exception:
            pass
    return default_state


def save_sync_state(state: Dict) -> None:
    """Saves sync state metadata."""
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _normalize_master_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize text/code and numeric columns so CSV/API frames merge and serialize cleanly to Parquet."""
    out = df.copy()
    for col in TEXT_COLUMNS:
        if col not in out.columns:
            out[col] = ""
        series = out[col].fillna("").astype(str).str.strip()
        series = series.replace({"nan": "", "None": "", "<NA>": "", "NaT": ""})
        if col in CODE_COLUMNS:
            series = series.str.replace(r"\.0$", "", regex=True)
        # Ensure plain Python strings in object dtype for consistent pyarrow Parquet serialization
        out[col] = pd.Series(series.tolist(), index=out.index, dtype=object)

    for col in NUMERIC_COLUMNS:
        if col not in out.columns:
            out[col] = 0.0
        else:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0).astype(float)

    ordered_cols = [c for c in STANDARD_COLUMNS if c in out.columns]
    extra_cols = [c for c in out.columns if c not in ordered_cols]
    return out[ordered_cols + extra_cols]


def _prepare_master_outputs(
    existing_df: pd.DataFrame,
    new_dfs: List[pd.DataFrame],
    csv_path: Path,
    parquet_path: Path,
    write_parquet: bool,
    flow_label: str,
) -> Tuple[pd.DataFrame, int]:
    """Merge existing master DataFrame with new API frames, deduplicate, sort, and write CSV/Parquet."""
    normalized_frames = [_normalize_master_frame(existing_df)] + [
        _normalize_master_frame(frame) for frame in new_dfs if frame is not None and not frame.empty
    ]
    combined = pd.concat(normalized_frames, ignore_index=True)
    combined = _normalize_master_frame(combined)

    dedup_subset = [c for c in DEDUP_COLS if c in combined.columns]
    if dedup_subset:
        combined = combined.drop_duplicates(subset=dedup_subset, keep="last")

    sort_subset = [c for c in SORT_COLS if c in combined.columns]
    if sort_subset:
        combined = combined.sort_values(by=sort_subset).reset_index(drop=True)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(csv_path, index=False, encoding="utf-8-sig")

    if write_parquet:
        combined.to_parquet(parquet_path, index=False, engine="pyarrow")

    added_rows = len(combined) - len(existing_df)
    print(f"\n💾 บันทึก Master {flow_label} ใหม่: {len(combined):,} แถว ({added_rows:+,} แถว)")
    return combined, added_rows


def _determine_target_years(reporter_entry: Dict, now_utc: Optional[datetime] = None) -> List[int]:
    """Determine which year(s) to fetch incrementally without hardcoding a single calendar year."""
    now = now_utc or datetime.now(timezone.utc)
    years = {now.year}
    if now.month <= 3:
        years.add(now.year - 1)

    min_recent_year = max(2020, now.year - 1)
    for yr in reporter_entry.get("years") or []:
        if isinstance(yr, int) and min_recent_year <= yr <= now.year:
            years.add(yr)
    return sorted(years)


def write_github_step_summary(title: str, text: str) -> None:
    """Appends markdown content to GitHub Step Summary if running in CI/CD."""
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(f"\n## {title}\n\n{text}\n")
        except Exception as e:
            logger.debug("ไม่สามารถเขียน Step Summary: %s", e)


def run_gdrive_sync(
    days_back: int = 7,
    force: bool = False,
    api_key: Optional[str] = None,
) -> None:
    """
    Main Sync Engine:
    1. Authenticates with Google Drive
    2. Checks UN Comtrade Live Releases for new country data
    3. Skips releases already recorded in sync_state.json (unless force=True)
    4. Downloads master files, merges/normalizes new data, writes CSV/Parquet locally,
       then uploads back to Drive and updates sync_state.json
    """
    imp_id = os.getenv("GDRIVE_IMPORT_CSV_ID")
    exp_id = os.getenv("GDRIVE_EXPORT_CSV_ID")
    imp_pq_id = os.getenv("GDRIVE_IMPORT_PARQUET_ID")
    exp_pq_id = os.getenv("GDRIVE_EXPORT_PARQUET_ID")

    if not imp_id or not exp_id:
        raise ConfigError(
            "ไม่พบตัวแปรสภาพแวดล้อม GDRIVE_IMPORT_CSV_ID หรือ GDRIVE_EXPORT_CSV_ID "
            "(กรุณาระบุใน GitHub Secrets หรือ .env)"
        )

    print("\n" + "=" * 70)
    print("🛰️ เริ่มต้นระบบ Auto-Sync: UN Comtrade ➔ Master CSV บน Google Drive")
    print("=" * 70)

    # 1. Google Drive Service
    drive_service = get_gdrive_service()
    print("✅ เชื่อมต่อ Google Drive API สำเร็จ")

    # 2. Check Comtrade Releases
    print(f"\n🔎 ตรวจสอบข้อมูลที่เพิ่งปล่อยย้อนหลัง {days_back} วัน...")
    updated_reporters = get_recently_updated_reporters(days_back=days_back, api_key=api_key)
    state = load_sync_state()
    synced_releases: Dict[str, str] = state.get("country_releases", {})

    if not updated_reporters:
        msg = f"✨ ฐานข้อมูลเป็นปัจจุบันแล้ว ไม่พบประเทศที่ปล่อยข้อมูลใหม่ในช่วง {days_back} วันที่ผ่านมา"
        print(msg)
        write_github_step_summary("UN Comtrade Rice Sync Summary", msg)
        return

    if force:
        pending_reporters = list(updated_reporters)
        skipped_count = 0
    else:
        pending_reporters = []
        skipped_count = 0
        for c in updated_reporters:
            r_code = str(c["code"])
            r_token = str(c.get("release_token") or "")
            if r_token and synced_releases.get(r_code) == r_token:
                skipped_count += 1
            else:
                pending_reporters.append(c)

    print(f"📌 พบ {len(updated_reporters)} ประเทศที่ปล่อยข้อมูลในรอบ {days_back} วัน (ข้ามที่ซิงค์แล้ว {skipped_count} ประเทศ)")
    if not pending_reporters:
        msg = (
            f"✨ ฐานข้อมูลเป็นปัจจุบันแล้ว (ประเทศที่ปล่อยข้อมูลล่าสุดทั้ง {len(updated_reporters)} ประเทศ"
            "ถูกซิงค์ครบในรอบก่อนหน้าแล้ว)"
        )
        print(msg)
        write_github_step_summary("UN Comtrade Rice Sync Summary", msg)
        return

    for idx, c in enumerate(pending_reporters, 1):
        print(f"   {idx}. {c['name']} (M49: {c['code']})")

    # 3. Download current master CSV files
    out_dir = get_output_dir()
    local_imp_csv = out_dir / "master_rice_import.csv"
    local_exp_csv = out_dir / "master_rice_export.csv"
    local_imp_pq = out_dir / "master_rice_import.parquet"
    local_exp_pq = out_dir / "master_rice_export.parquet"

    print("\n📥 ตรวจสอบและดึงไฟล์ Master CSV จาก Google Drive...")
    if not local_imp_csv.is_file() or force:
        download_gdrive_file(drive_service, imp_id, local_imp_csv)
    if not local_exp_csv.is_file() or force:
        download_gdrive_file(drive_service, exp_id, local_exp_csv)

    # Load existing master DataFrames
    print("\n📖 กำลังอ่านฐานข้อมูล Master ปัจจุบัน...")
    df_import = pd.read_csv(local_imp_csv, dtype=str)
    df_export = pd.read_csv(local_exp_csv, dtype=str)

    print(f"  • Master Import: {len(df_import):,} แถว")
    print(f"  • Master Export: {len(df_export):,} แถว")

    # 4. Fetch incremental data for pending countries
    now_utc = datetime.now(timezone.utc)
    new_import_dfs: List[pd.DataFrame] = []
    new_export_dfs: List[pd.DataFrame] = []
    succeeded_reporters: List[Dict] = []
    failed_reporters: List[str] = []
    tracker = QuotaTracker()

    print(f"\n🚀 ดึงข้อมูลสถิติข้าวรายเดือนสำหรับ {len(pending_reporters)} ประเทศที่ยังไม่ได้ซิงค์...")
    for idx, c in enumerate(pending_reporters, 1):
        target_years = _determine_target_years(c, now_utc=now_utc)
        print(f"  [{idx}/{len(pending_reporters)}] กำลังดึง: {c['name']} (รหัส {c['code']}, ปี {target_years})...")

        if not tracker.can_proceed(2 * len(target_years)):
            logger.warning(
                "🛑 โควต้าประจำวันใกล้เต็ม (%d/%d) หยุดการดึงประเทศที่เหลือไว้รอบถัดไป",
                tracker.used_requests,
                tracker.max_requests,
            )
            break

        try:
            df_imp = fetch_country_rice_flow(
                country_code=str(c["code"]),
                country_name=str(c["name"]),
                flow_code="M",
                years=target_years,
                quota_tracker=tracker,
                api_key=api_key,
                delay=1.2,
                raise_on_error=True,
            )
            df_exp = fetch_country_rice_flow(
                country_code=str(c["code"]),
                country_name=str(c["name"]),
                flow_code="X",
                years=target_years,
                quota_tracker=tracker,
                api_key=api_key,
                delay=1.2,
                raise_on_error=True,
            )

            if df_imp is not None and not df_imp.empty:
                new_import_dfs.append(df_imp)
                print(f"     ➔ นำเข้า: +{len(df_imp):,} แถว")
            if df_exp is not None and not df_exp.empty:
                new_export_dfs.append(df_exp)
                print(f"     ➔ ส่งออก: +{len(df_exp):,} แถว")

            # Also update local country Excel if output/by_country exists
            country_dir = out_dir / "by_country"
            if country_dir.is_dir():
                process_country_rice_file(
                    country_code=str(c["code"]),
                    country_name=str(c["name"]),
                    years=target_years,
                    output_dir=country_dir,
                    quota_tracker=tracker,
                    incremental=True,
                    api_key=api_key,
                )

            succeeded_reporters.append(c)

        except ConfigError:
            raise
        except Exception as e:
            logger.warning("ไม่สามารถดึงข้อมูลประเทศ %s: %s", c["name"], e)
            failed_reporters.append(f"{c['name']} ({e})")

    if not succeeded_reporters and failed_reporters:
        raise RuntimeError(
            f"ไม่สามารถดึงข้อมูลได้เลยทุกประเทศ ({len(failed_reporters)} ประเทศล้มเหลว): "
            + "; ".join(failed_reporters[:5])
        )

    # 5. Build all local files FIRST so any serialization error fails before mutating Google Drive
    upload_jobs: List[Tuple[str, Path, str, str]] = []
    imp_status = "ไม่มีข้อมูลนำเข้าใหม่ (ไม่ได้อัปโหลด)"
    exp_status = "ไม่มีข้อมูลส่งออกใหม่ (ไม่ได้อัปโหลด)"

    if new_import_dfs:
        combined_imp, imp_diff = _prepare_master_outputs(
            df_import,
            new_import_dfs,
            local_imp_csv,
            local_imp_pq,
            write_parquet=bool(imp_pq_id),
            flow_label="Import",
        )
        upload_jobs.append((imp_id, local_imp_csv, "text/csv", "Master Import CSV"))
        if imp_pq_id:
            upload_jobs.append((imp_pq_id, local_imp_pq, "application/octet-stream", "Master Import Parquet"))
        imp_status = f"อัปเดตสำเร็จ ({len(combined_imp):,} แถว, {imp_diff:+,} แถว)"

    if new_export_dfs:
        combined_exp, exp_diff = _prepare_master_outputs(
            df_export,
            new_export_dfs,
            local_exp_csv,
            local_exp_pq,
            write_parquet=bool(exp_pq_id),
            flow_label="Export",
        )
        upload_jobs.append((exp_id, local_exp_csv, "text/csv", "Master Export CSV"))
        if exp_pq_id:
            upload_jobs.append((exp_pq_id, local_exp_pq, "application/octet-stream", "Master Export Parquet"))
        exp_status = f"อัปเดตสำเร็จ ({len(combined_exp):,} แถว, {exp_diff:+,} แถว)"

    for file_id, file_path, mime_type, _label in upload_jobs:
        upload_update_gdrive_file(drive_service, file_id, file_path, mime_type)

    # 6. Save Sync State ONLY for countries that succeeded
    state["last_sync_time"] = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    state["last_updated_countries"] = [str(c["name"]) for c in succeeded_reporters]
    country_releases = dict(state.get("country_releases") or {})
    for c in succeeded_reporters:
        r_token = str(c.get("release_token") or "")
        if r_token:
            country_releases[str(c["code"])] = r_token
    state["country_releases"] = country_releases
    save_sync_state(state)

    summary_lines = [
        "### ✅ อัปเดตฐานข้อมูลข้าวโลกสำเร็จ\n",
        f"- **เวลาที่ซิงค์:** `{state['last_sync_time']}`",
        f"- **ประเทศที่ซิงค์สำเร็จ ({len(succeeded_reporters)} ประเทศ):** "
        f"{', '.join([str(c['name']) for c in succeeded_reporters]) or '-'}",
        f"- **ประเทศที่ข้าม (ซิงค์รอบนี้ไปแล้ว):** {skipped_count} ประเทศ",
        f"- **โควต้า API ที่ใช้ในรอบนี้:** {tracker.used_requests} Requests",
        f"- **Master Import:** {imp_status}",
        f"- **Master Export:** {exp_status}",
    ]
    if failed_reporters:
        summary_lines.append(f"- **⚠️ ประเทศที่ดึงไม่สำเร็จ ({len(failed_reporters)}):** {', '.join(failed_reporters)}")

    write_github_step_summary("UN Comtrade Rice Sync Summary", "\n".join(summary_lines))
    print("\n" + "=" * 70)
    print("🎉 กระบวนการซิงค์ข้อมูลกับ Google Drive เสร็จสมบูรณ์ทุกขั้นตอน!")
    print("=" * 70 + "\n")
