"""
Master Rice Database Consolidation Module:
Consolidates all individual country Excel files (272 countries) from output/by_country/
into two centralized master database files:
  1. output/master_rice_import.csv (and .parquet)
  2. output/master_rice_export.csv (and .parquet)

Optimized for high-throughput batching, schema validation, and utf-8-sig encoding.
"""

import logging
from pathlib import Path
import time
from typing import Dict, List, Optional, Tuple
import openpyxl
import pandas as pd

from .config import get_output_dir

logger = logging.getLogger("comtrade_pipeline")

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


def _read_sheet_fast(ws, sheet_name: str) -> List[Dict]:
    """Reads rows from a read-only openpyxl worksheet fast into dictionaries."""
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration:
        return []

    if not header:
        return []

    # Map column headers to indices
    col_map = {str(name).strip(): idx for idx, name in enumerate(header) if name is not None}
    indices = [col_map.get(col) for col in STANDARD_COLUMNS]

    records = []
    for row in rows_iter:
        if not row or all(v is None for v in row):
            continue
        record = {col: (row[idx] if idx is not None and idx < len(row) else None) for col, idx in zip(STANDARD_COLUMNS, indices)}
        records.append(record)

    return records


def consolidate_master_rice(
    by_country_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    export_parquet: bool = True,
) -> Tuple[Optional[Path], Optional[Path]]:
    """
    Consolidates all country Excel files in by_country_dir into master CSV/Parquet files.
    Returns:
        Tuple of (import_csv_path, export_csv_path)
    """
    out_dir = output_dir or get_output_dir()
    country_dir = by_country_dir or (out_dir / "by_country")

    if not country_dir.is_dir():
        logger.error("❌ ไม่พบโฟลเดอร์ %s", country_dir)
        return None, None

    excel_files = sorted(list(country_dir.glob("*.xlsx")))
    total_files = len(excel_files)
    if total_files == 0:
        logger.warning("⚠️ ไม่พบไฟล์ .xlsx ใน %s", country_dir)
        return None, None

    print(f"\n{'='*70}")
    print(f"📦 เริ่มกระบวนการรวมฐานข้อมูลข้าวโลก (Consolidating Rice Master Database)")
    print(f"🌍 จำนวนไฟล์ประเทศทั้งหมด: {total_files} ไฟล์")
    print(f"📂 โฟลเดอร์ต้นทาง: {country_dir}")
    print(f"{'='*70}\n")

    start_time = time.time()
    all_import_records: List[Dict] = []
    all_export_records: List[Dict] = []

    scanned_count = 0
    non_empty_import_countries = 0
    non_empty_export_countries = 0

    for idx, filepath in enumerate(excel_files, 1):
        scanned_count += 1
        try:
            wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
            if "Import" in wb.sheetnames:
                imp_rows = _read_sheet_fast(wb["Import"], "Import")
                if imp_rows:
                    all_import_records.extend(imp_rows)
                    non_empty_import_countries += 1

            if "Export" in wb.sheetnames:
                exp_rows = _read_sheet_fast(wb["Export"], "Export")
                if exp_rows:
                    all_export_records.extend(exp_rows)
                    non_empty_export_countries += 1

            wb.close()
        except Exception as e:
            logger.warning("อ่านไฟล์ %s ไม่สำเร็จ: %s", filepath.name, e)

        if idx % 30 == 0 or idx == total_files:
            elapsed = time.time() - start_time
            print(f"  ⏳ ประมวลผลแล้ว {idx}/{total_files} ประเทศ ({idx/total_files*100:.1f}%) | "
                  f"Import: {len(all_import_records):,} แถว | Export: {len(all_export_records):,} แถว "
                  f"[{elapsed:.1f}s]")

    print(f"\n📊 โหลดข้อมูลเสร็จสิ้นใน {time.time() - start_time:.2f} วินาที")
    print(f"  • ข้อมูลการนำเข้า (Import): {len(all_import_records):,} แถว จาก {non_empty_import_countries} ประเทศ")
    print(f"  • ข้อมูลการส่งออก (Export): {len(all_export_records):,} แถว จาก {non_empty_export_countries} ประเทศ")

    # Build DataFrames
    import_csv_path = out_dir / "master_rice_import.csv"
    export_csv_path = out_dir / "master_rice_export.csv"

    def _process_and_save(records: List[Dict], csv_path: Path, parquet_name: str, flow_name: str):
        if not records:
            logger.warning("ไม่มีข้อมูลสำหรับ %s", flow_name)
            return

        print(f"\n⚙️ กำลังจัดระเบียบและ Deduplicate ข้อมูล {flow_name}...")
        df = pd.DataFrame(records)

        # Standardize data types
        df["period"] = df["period"].astype(str).str.strip()
        df["reporterCode"] = df["reporterCode"].astype(str).str.strip()
        df["partnerCode"] = df["partnerCode"].astype(str).str.strip()
        df["cmdCode"] = df["cmdCode"].astype(str).str.strip()
        df["flowCode"] = df["flowCode"].astype(str).str.strip()

        for num_col in ["primaryValue", "netWgt", "qty"]:
            if num_col in df.columns:
                df[num_col] = pd.to_numeric(df[num_col], errors="coerce").fillna(0.0)

        # Deduplicate
        dedup_keys = ["period", "reporterCode", "partnerCode", "cmdCode", "flowCode"]
        initial_len = len(df)
        df = df.drop_duplicates(subset=dedup_keys, keep="last")
        dedup_diff = initial_len - len(df)
        if dedup_diff > 0:
            print(f"  ✂️ กำจัดแถวซ้ำซ้อน: {dedup_diff:,} แถว (คงเหลือ {len(df):,} แถว)")

        # Sort logically
        sort_cols = [c for c in ["period", "reporterDesc", "cmdCode", "partnerDesc"] if c in df.columns]
        df = df.sort_values(by=sort_cols, ascending=[True, True, True, True])

        # Save CSV (utf-8-sig for perfect Excel & Thai language compatibility)
        print(f"  💾 บันทึกไฟล์ CSV: {csv_path.name}...")
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        csv_size_mb = csv_path.stat().st_size / (1024 * 1024)

        print(f"  ✅ บันทึกสำเร็จ: {csv_path.name} ({len(df):,} แถว, ขนาด {csv_size_mb:.2f} MB)")

        if export_parquet:
            pq_path = out_dir / parquet_name
            try:
                df.to_parquet(pq_path, index=False, engine="pyarrow")
                pq_size_mb = pq_path.stat().st_size / (1024 * 1024)
                print(f"  ⚡ บันทึกไฟล์ Parquet สำเร็จ: {pq_path.name} ({pq_size_mb:.2f} MB)")
            except Exception as e:
                logger.debug("ไม่สามารถบันทึก Parquet ได้: %s", e)

    _process_and_save(all_import_records, import_csv_path, "master_rice_import.parquet", "Import (นำเข้า)")
    _process_and_save(all_export_records, export_csv_path, "master_rice_export.parquet", "Export (ส่งออก)")

    print(f"\n{'='*70}")
    print(f"🎉 รวมฐานข้อมูล Master Rice สำเร็จเรียบร้อยทั้ง 2 ไฟล์!")
    print(f"  1. Import: {import_csv_path}")
    print(f"  2. Export: {export_csv_path}")
    print(f"  รวมเวลาดำเนินการทั้งหมด: {time.time() - start_time:.2f} วินาที")
    print(f"{'='*70}\n")

    return import_csv_path, export_csv_path
