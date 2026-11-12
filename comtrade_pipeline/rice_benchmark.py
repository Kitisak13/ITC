"""
Rice Unit Price Benchmark & Competitiveness Analytics:
Calculates and compares Unit Values (USD/kg and USD/ton) for rice (HS 1006)
across major exporting and importing countries.
Implements statistical outlier removal (IQR log-scale) and breakdown by rice subheadings.
Outputs interactive CLI tables and an Excel dashboard in output/rice_unit_price_benchmark.xlsx.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Union
import numpy as np
import pandas as pd

from .config import get_output_dir
from .country_resolver import resolve_countries

logger = logging.getLogger("comtrade_pipeline")

COMMODITY_NAMES = {
    "1006": "Rice (All)",
    "100610": "Paddy (ข้าวเปลือก)",
    "100620": "Brown Rice (ข้าวกล้อง)",
    "100630": "White/Milled (ข้าวขาวขัดสี)",
    "100640": "Broken Rice (ปลายข้าว)",
}


def clean_unit_values(df: pd.DataFrame) -> pd.DataFrame:
    """Filters positive values and applies IQR outlier clipping on log(Unit Value)."""
    valid = df[(df["primaryValue"] > 0) & (df["netWgt"] > 0)].copy()
    if len(valid) < 5:
        valid["unit_price_usd_kg"] = valid["primaryValue"] / valid["netWgt"]
        valid["unit_price_usd_ton"] = valid["unit_price_usd_kg"] * 1000.0
        return valid

    uv = valid["primaryValue"] / valid["netWgt"]
    log_uv = np.log(uv)
    q1 = log_uv.quantile(0.15)
    q3 = log_uv.quantile(0.85)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr

    cleaned = valid[(log_uv >= lower_bound) & (log_uv <= upper_bound)].copy()
    cleaned["unit_price_usd_kg"] = cleaned["primaryValue"] / cleaned["netWgt"]
    cleaned["unit_price_usd_ton"] = cleaned["unit_price_usd_kg"] * 1000.0
    return cleaned


def analyze_country_rice_file(filepath: Path, flow: str = "Export", year: Optional[int] = None) -> Optional[pd.DataFrame]:
    """Reads a country Excel file and cleans its unit values."""
    if not filepath.is_file():
        return None
    try:
        with pd.ExcelFile(filepath) as xls:
            sheet_name = "Export" if flow.lower().startswith("exp") or flow.upper() == "X" else "Import"
            if sheet_name not in xls.sheet_names:
                return None
            df = pd.read_excel(xls, sheet_name)
    except Exception as e:
        logger.warning("อ่านไฟล์ %s ไม่สำเร็จ: %s", filepath.name, e)
        return None

    if df.empty:
        return None

    df["cmdCode"] = df["cmdCode"].astype(str).str.strip()
    df["period"] = df["period"].astype(str).str.strip()

    if year:
        df = df[df["period"].str.startswith(str(year))]

    return clean_unit_values(df)


def run_rice_benchmark(
    countries: Optional[Union[str, List[str]]] = None,
    flow: str = "Export",
    year: Optional[int] = None,
    output_excel: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Computes global rice unit price benchmark comparing selected or all available countries.
    Generates summary tables and exports an Excel report.
    """
    by_country_dir = get_output_dir() / "by_country"
    if not by_country_dir.is_dir():
        logger.error("❌ ไม่พบโฟลเดอร์ %s กรุณารันคำสั่ง country-rice ก่อน", by_country_dir)
        return pd.DataFrame()

    # Determine files to analyze
    target_files: List[Tuple[str, Path]] = []
    if countries:
        resolved = resolve_countries(countries)
        for c in resolved:
            f = by_country_dir / f"{c['name']}.xlsx"
            if f.is_file():
                target_files.append((c["name"], f))
            else:
                logger.warning("⚠️ ยังไม่มีไฟล์ของ [%s] ที่ %s", c["name"], f.name)
    else:
        for f in by_country_dir.glob("*.xlsx"):
            target_files.append((f.stem, f))

    if not target_files:
        logger.warning("⚠️ ไม่พบไฟล์ข้อมูลประเทศที่จะนำมาวิเคราะห์")
        return pd.DataFrame()

    summary_rows = []
    commodity_rows = []
    yearly_rows = []
    monthly_rows = []

    print("\n" + "=" * 70)
    print(f"📊 กำลังประมวลผลการวิเคราะห์ราคาข้าวโลก (Rice Unit Value Benchmark)")
    print(f"🌍 วิเคราะห์ทั้งหมด {len(target_files)} ประเทศ | ทิศทาง: {flow}")
    print("=" * 70)

    for country_name, file_path in target_files:
        df = analyze_country_rice_file(file_path, flow=flow, year=year)
        if df is None or df.empty:
            continue

        # Filter partner == World to avoid double counting for national aggregates if available,
        # otherwise use sum across all partners
        world_df = df[df["partnerDesc"] == "World"] if "World" in df["partnerDesc"].values else df

        total_value = world_df["primaryValue"].sum()
        total_kg = world_df["netWgt"].sum()
        total_tons = total_kg / 1000.0
        avg_price_ton = (total_value / total_kg * 1000.0) if total_kg > 0 else 0.0
        median_price_ton = world_df["unit_price_usd_ton"].median() if not world_df.empty else 0.0

        summary_rows.append({
            "Country": country_name,
            "Total_Value_USD": total_value,
            "Total_Volume_Tons": total_tons,
            "Avg_Price_USD_per_Ton": avg_price_ton,
            "Median_Price_USD_per_Ton": median_price_ton,
            "Total_Records": len(df),
        })

        # Breakdown by Commodity Subheadings (6 digits)
        sub_6 = df[df["cmdCode"].str.len() == 6]
        for cmd_code, grp in sub_6.groupby("cmdCode"):
            grp_val = grp["primaryValue"].sum()
            grp_kg = grp["netWgt"].sum()
            grp_tons = grp_kg / 1000.0
            avg_p = (grp_val / grp_kg * 1000.0) if grp_kg > 0 else 0.0
            commodity_rows.append({
                "Country": country_name,
                "Commodity_Code": cmd_code,
                "Commodity_Type": COMMODITY_NAMES.get(cmd_code, cmd_code),
                "Total_Value_USD": grp_val,
                "Total_Volume_Tons": grp_tons,
                "Avg_Price_USD_per_Ton": avg_p,
                "Median_Price_USD_per_Ton": grp["unit_price_usd_ton"].median(),
            })

        # Breakdown by Year
        df_copy = df.copy()
        df_copy["year"] = df_copy["period"].str.slice(0, 4)
        for yr, grp in df_copy.groupby("year"):
            y_val = grp["primaryValue"].sum()
            y_kg = grp["netWgt"].sum()
            avg_p = (y_val / y_kg * 1000.0) if y_kg > 0 else 0.0
            yearly_rows.append({
                "Country": country_name,
                "Year": yr,
                "Total_Value_USD": y_val,
                "Total_Volume_Tons": y_kg / 1000.0,
                "Avg_Price_USD_per_Ton": avg_p,
            })

        # Latest 12 Months
        for period_val, grp in df_copy.groupby("period"):
            m_val = grp["primaryValue"].sum()
            m_kg = grp["netWgt"].sum()
            avg_p = (m_val / m_kg * 1000.0) if m_kg > 0 else 0.0
            monthly_rows.append({
                "Country": country_name,
                "Period": period_val,
                "Total_Value_USD": m_val,
                "Total_Volume_Tons": m_kg / 1000.0,
                "Avg_Price_USD_per_Ton": avg_p,
            })

    if not summary_rows:
        logger.warning("ไม่มีข้อมูลเพียงพอสำหรับการทำ Benchmark")
        return pd.DataFrame()

    df_summary = pd.DataFrame(summary_rows).sort_values("Total_Value_USD", ascending=False)
    df_commodity = pd.DataFrame(commodity_rows).sort_values(["Commodity_Code", "Total_Value_USD"], ascending=[True, False])
    df_yearly = pd.DataFrame(yearly_rows).sort_values(["Country", "Year"])
    df_monthly = pd.DataFrame(monthly_rows).sort_values(["Country", "Period"])

    # Pretty-print CLI Table
    print("\n" + "=" * 80)
    print("🏆 ตารางเปรียบเทียบขีดความสามารถการค้าข้าว (Rice Benchmark Summary)")
    print("=" * 80)
    print(f"{'ประเทศ (Country)':<22} | {'มูลค่า (USD)':>18} | {'ปริมาณ (ตัน)':>16} | {'ราคาเฉลี่ย ($/ตัน)':>18}")
    print("-" * 80)
    for _, r in df_summary.head(15).iterrows():
        val_str = f"${r['Total_Value_USD']:,.0f}"
        vol_str = f"{r['Total_Volume_Tons']:,.0f}"
        price_str = f"${r['Avg_Price_USD_per_Ton']:,.1f}"
        print(f"{r['Country']:<22} | {val_str:>18} | {vol_str:>16} | {price_str:>18}")
    print("=" * 80)

    # White rice comparison (100630)
    white_rice = df_commodity[df_commodity["Commodity_Code"] == "100630"]
    if not white_rice.empty:
        print("\n🍚 ราคาข้าวขาวขัดสี (HS 100630) เทียบผู้ส่งออกหลัก:")
        print("-" * 65)
        for _, r in white_rice.head(8).iterrows():
            print(f"  • {r['Country']:<18}: ราคาเฉลี่ย ${r['Avg_Price_USD_per_Ton']:,.1f} / ตัน (ส่งออก {r['Total_Volume_Tons']:,.0f} ตัน)")
        print("-" * 65)

    # Save to Excel & CSV
    out_dir = get_output_dir()
    excel_path = output_excel or (out_dir / "rice_unit_price_benchmark.xlsx")
    csv_path = out_dir / "rice_unit_price_benchmark.csv"

    try:
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df_summary.to_excel(writer, sheet_name="Country_Benchmark", index=False)
            df_commodity.to_excel(writer, sheet_name="By_Rice_Type", index=False)
            df_yearly.to_excel(writer, sheet_name="Yearly_Trends", index=False)
            df_monthly.to_excel(writer, sheet_name="Monthly_Trends", index=False)

        df_summary.to_csv(csv_path, index=False, encoding="utf-8-sig")
        logger.info("💾 บันทึกรายงาน Benchmark เรียบร้อยแล้วที่:")
        logger.info("   1. Excel: %s", excel_path)
        logger.info("   2. CSV:   %s", csv_path)
    except Exception as e:
        logger.error("❌ บันทึกรายงาน Benchmark ล้มเหลว: %s", e)

    return df_summary
