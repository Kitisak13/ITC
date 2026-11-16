"""
Google Drive Synchronization & Automated Pipeline Module:
Manages authentication (OAuth 2.0 with Refresh Token or Service Account),
downloads/uploads master CSV files on Google Drive, and synchronizes
incremental rice updates from UN Comtrade automatically.
"""

import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .config import get_api_key, get_output_dir
from .country_rice import QuotaTracker, fetch_country_rice_flow, process_country_rice_file
from .country_resolver import resolve_countries
from .live_updates import get_recently_updated_reporters

logger = logging.getLogger("comtrade_pipeline")

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]

STATE_FILE = Path("sync_state.json")


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
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_sync_time": None, "last_updated_countries": []}


def save_sync_state(state: Dict) -> None:
    """Saves sync state metadata."""
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


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
    3. If updates found, downloads master files, appends new data, and uploads back to Drive
    """
    imp_id = os.getenv("GDRIVE_IMPORT_CSV_ID")
    exp_id = os.getenv("GDRIVE_EXPORT_CSV_ID")
    imp_pq_id = os.getenv("GDRIVE_IMPORT_PARQUET_ID")
    exp_pq_id = os.getenv("GDRIVE_EXPORT_PARQUET_ID")

    if not imp_id or not exp_id:
        print("\n❌ ข้อผิดพลาด: ไม่พบตัวแปรสภาพแวดล้อม GDRIVE_IMPORT_CSV_ID หรือ GDRIVE_EXPORT_CSV_ID")
        print("กรุณาระบุ File ID ของ master_rice_import.csv และ master_rice_export.csv ใน GitHub Secrets / .env")
        return

    print("\n" + "=" * 70)
    print("🛰️ เริ่มต้นระบบ Auto-Sync: UN Comtrade ➔ Master CSV บน Google Drive")
    print("=" * 70)

    # 1. Google Drive Service
    try:
        drive_service = get_gdrive_service()
        print("✅ เชื่อมต่อ Google Drive API สำเร็จ")
    except Exception as e:
        print(f"❌ ไม่สามารถเชื่อมต่อ Google Drive: {e}")
        return

    # 2. Check Comtrade Releases
    print(f"\n🔎 ตรวจสอบข้อมูลที่เพิ่งปล่อยย้อนหลัง {days_back} วัน...")
    updated_reporters = get_recently_updated_reporters(days_back=days_back, api_key=api_key)

    state = load_sync_state()

    if not updated_reporters and not force:
        msg = f"✨ ฐานข้อมูลเป็นปัจจุบันแล้ว ไม่พบประเทศที่ปล่อยข้อมูลใหม่ในช่วง {days_back} วันที่ผ่านมา"
        print(msg)
        write_github_step_summary("UN Comtrade Rice Sync Summary", msg)
        return

    print(f"📌 พบ {len(updated_reporters)} ประเทศที่มีการปล่อยข้อมูลใหม่:")
    for idx, c in enumerate(updated_reporters, 1):
        print(f"   {idx}. {c['name']} (M49: {c['code']})")

    # 3. Download current master CSV files
    out_dir = get_output_dir()
    local_imp_csv = out_dir / "master_rice_import.csv"
    local_exp_csv = out_dir / "master_rice_export.csv"

    print("\n📥 ตรวจสอบและดึงไฟล์ Master CSV จาก Google Drive...")
    if not local_imp_csv.is_file() or force:
        download_gdrive_file(drive_service, imp_id, local_imp_csv)
    if not local_exp_csv.is_file() or force:
        download_gdrive_file(drive_service, exp_id, local_exp_csv)

    # Load existing master DataFrames
    print("\n📖 กำลังอ่านฐานข้อมูล Master ปัจจุบัน...")
    df_import = pd.read_csv(local_imp_csv, dtype=str)
    df_export = pd.read_csv(local_exp_csv, dtype=str)

    init_imp_rows = len(df_import)
    init_exp_rows = len(df_export)
    print(f"  • Master Import: {init_imp_rows:,} แถว")
    print(f"  • Master Export: {init_exp_rows:,} แถว")

    # 4. Fetch incremental data for updated countries
    current_year = 2026
    new_import_dfs = []
    new_export_dfs = []
    tracker = QuotaTracker()

    print(f"\n🚀 ดึงข้อมูลสถิติข้าวรายเดือนปี {current_year} สำหรับประเทศที่มีการอัปเดต...")
    for idx, c in enumerate(updated_reporters, 1):
        print(f"  [{idx}/{len(updated_reporters)}] กำลังดึง: {c['name']} (รหัส {c['code']})...")

        try:
            # 1. Fetch Import (M)
            df_imp = fetch_country_rice_flow(
                country_code=c["code"],
                country_name=c["name"],
                flow_code="M",
                years=[current_year],
                quota_tracker=tracker,
                api_key=api_key,
                delay=1.2,
            )
            if df_imp is not None and not df_imp.empty:
                new_import_dfs.append(df_imp)
                print(f"     ➔ นำเข้า: +{len(df_imp):,} แถว")

            # 2. Fetch Export (X)
            df_exp = fetch_country_rice_flow(
                country_code=c["code"],
                country_name=c["name"],
                flow_code="X",
                years=[current_year],
                quota_tracker=tracker,
                api_key=api_key,
                delay=1.2,
            )
            if df_exp is not None and not df_exp.empty:
                new_export_dfs.append(df_exp)
                print(f"     ➔ ส่งออก: +{len(df_exp):,} แถว")

            # Also update local country Excel if output/by_country exists
            country_dir = out_dir / "by_country"
            if country_dir.is_dir():
                process_country_rice_file(
                    country_code=c["code"],
                    country_name=c["name"],
                    years=[current_year],
                    output_dir=out_dir,
                    quota_tracker=tracker,
                    incremental=True,
                    api_key=api_key,
                )

        except Exception as e:
            logger.warning("ไม่สามารถดึงข้อมูลประเทศ %s: %s", c["name"], e)

    # 5. Merge, Deduplicate, Sort
    dedup_cols = ["period", "reporterCode", "partnerCode", "cmdCode", "flowCode"]

    if new_import_dfs:
        combined_imp = pd.concat([df_import] + new_import_dfs, ignore_index=True)
        for col in ["primaryValue", "netWgt", "qty"]:
            if col in combined_imp.columns:
                combined_imp[col] = pd.to_numeric(combined_imp[col], errors="coerce").fillna(0.0)
        combined_imp = combined_imp.drop_duplicates(subset=dedup_cols, keep="last")
        combined_imp = combined_imp.sort_values(by=["period", "reporterDesc", "cmdCode", "partnerDesc"])
        combined_imp.to_csv(local_imp_csv, index=False, encoding="utf-8-sig")
        print(f"\n💾 บันทึก Master Import ใหม่: {len(combined_imp):,} แถว (+{len(combined_imp) - init_imp_rows:,} แถว)")

        upload_update_gdrive_file(drive_service, imp_id, local_imp_csv, "text/csv")

        if imp_pq_id:
            local_imp_pq = out_dir / "master_rice_import.parquet"
            combined_imp.to_parquet(local_imp_pq, index=False)
            upload_update_gdrive_file(drive_service, imp_pq_id, local_imp_pq, "application/octet-stream")

    if new_export_dfs:
        combined_exp = pd.concat([df_export] + new_export_dfs, ignore_index=True)
        for col in ["primaryValue", "netWgt", "qty"]:
            if col in combined_exp.columns:
                combined_exp[col] = pd.to_numeric(combined_exp[col], errors="coerce").fillna(0.0)
        combined_exp = combined_exp.drop_duplicates(subset=dedup_cols, keep="last")
        combined_exp = combined_exp.sort_values(by=["period", "reporterDesc", "cmdCode", "partnerDesc"])
        combined_exp.to_csv(local_exp_csv, index=False, encoding="utf-8-sig")
        print(f"\n💾 บันทึก Master Export ใหม่: {len(combined_exp):,} แถว (+{len(combined_exp) - init_exp_rows:,} แถว)")

        upload_update_gdrive_file(drive_service, exp_id, local_exp_csv, "text/csv")

        if exp_pq_id:
            local_exp_pq = out_dir / "master_rice_export.parquet"
            combined_exp.to_parquet(local_exp_pq, index=False)
            upload_update_gdrive_file(drive_service, exp_pq_id, local_exp_pq, "application/octet-stream")

    # 6. Save Sync State & Step Summary
    state["last_sync_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state["last_updated_countries"] = [c["name"] for c in updated_reporters]
    save_sync_state(state)

    summary_md = (
        f"### ✅ อัปเดตฐานข้อมูลข้าวโลกสำเร็จ\n\n"
        f"- **เวลาที่ซิงค์:** `{state['last_sync_time']}`\n"
        f"- **ประเทศที่มีข้อมูลใหม่ ({len(updated_reporters)} ประเทศ):** "
        f"{', '.join([c['name'] for c in updated_reporters])}\n"
        f"- **ผลลัพธ์การอัปเดต:**\n"
        f"  - 📥 **Master Import:** อัปเดตบน Google Drive เรียบร้อย (ID: `{imp_id}`)\n"
        f"  - 📤 **Master Export:** อัปเดตบน Google Drive เรียบร้อย (ID: `{exp_id}`)\n"
    )
    write_github_step_summary("UN Comtrade Rice Sync Summary", summary_md)
    print("\n" + "=" * 70)
    print("🎉 กระบวนการซิงค์ข้อมูลกับ Google Drive เสร็จสมบูรณ์ทุกขั้นตอน!")
    print("=" * 70 + "\n")
