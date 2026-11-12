"""Command-line interface for the UN Comtrade pipeline."""

import argparse
import logging
import sys
from typing import List, Optional

from .analysis import run_all_samples
from .config import ConfigError, get_api_key, get_output_dir, mask_key, setup_logging
from .country_groups import export_country_groups_files, load_all_country_groups
from .country_resolver import resolve_countries
from .country_rice import download_country_rice_group
from .live_updates import fetch_comtrade_releases, get_recently_updated_reporters, run_smart_incremental_update
from .metadata import download_metadata
from .rice_benchmark import run_rice_benchmark
from .tariffline import download_tariffline_imports, parse_country_args
from .usa_rice import download_usa_rice_monthly
from .world_import import download_import_world

logger = logging.getLogger("comtrade_pipeline")


def _csv_list(value: str) -> List[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def check_key(api_key: Optional[str] = None) -> int:
    try:
        key = get_api_key(api_key)
    except ConfigError as e:
        logger.error("%s", e)
        return 1
    logger.info("✅ พบ API Key: %s", mask_key(key))
    logger.info("📁 โฟลเดอร์ผลลัพธ์: %s", get_output_dir())
    return 0


def list_country_groups_cli() -> None:
    """Print summary of all country groups."""
    groups = load_all_country_groups()
    print("\n" + "=" * 65)
    print("🌍 แผนผังกลุ่มประเทศ (Country Groups Schedule - 35 ประเทศ/วัน)")
    print("=" * 65)
    for grp_num, countries in groups.items():
        tag = "⭐ (Top 35 Global Rice Players)" if grp_num == 1 else ""
        print(f"\n📅 Group {grp_num} ({len(countries)} ประเทศ) {tag}:")
        names = [f"{c['name']} ({c['code']})" for c in countries]
        preview = ", ".join(names[:6])
        if len(names) > 6:
            preview += f" ... และอีก {len(names) - 6} ประเทศ"
        print(f"   {preview}")
        print(f"   👉 คำสั่งรัน: python run_pipeline.py country-rice --group {grp_num}")
    print("\n" + "=" * 65)
    print("💡 รายละเอียดเต็มทุกประเทศสามารถดูได้ที่ไฟล์: country_groups.md")
    print("=" * 65)


def show_live_updates_cli(days_back: int = 30, api_key: Optional[str] = None) -> None:
    """Print recently updated countries from live releases."""
    print(f"\n🛰️ กำลังตรวจสอบ Live Data Releases จาก UN Comtrade ย้อนหลัง {days_back} วัน...")
    updated = get_recently_updated_reporters(days_back=days_back, api_key=api_key)
    if not updated:
        print("ℹ️ ไม่พบข้อมูลการปล่อยชุดข้อมูลใหม่ในช่วงเวลานี้ หรือยังไม่มีการประกาศ")
        return
    print(f"\n✅ พบ {len(updated)} ประเทศที่มีการอัปเดตข้อมูลการค้าล่าสุด:")
    print("-" * 65)
    for idx, c in enumerate(updated, 1):
        print(f"  {idx:2d}. {c['name']:<25} (M49: {c['code']})")
    print("-" * 65)
    print("💡 คุณสามารถรัน 'python run_pipeline.py smart-update' เพื่อดึงข้อมูลเฉพาะประเทศที่อัปเดตได้ทันที")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="UN Comtrade Data Pipeline")
    p.add_argument("--api-key", default=None, help="Override COMTRADE_API_KEY (prefer .env)")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("metadata", help="Download countries & HS code reference data")

    w = sub.add_parser("world-import", help="World imports at HS6 for a chapter")
    w.add_argument("--chapter", default="07")
    w.add_argument("--years", default="2022,2023,2024,2025")
    w.add_argument("--delay", type=float, default=2.0)
    w.add_argument("--no-cache", action="store_true", help="Ignore cached responses")

    t = sub.add_parser("tariffline", help="Tariff line data (8-11 digits, supports ISO3 e.g. USA,RUS,THA)")
    t.add_argument("--countries", default="USA,RUS", help="รายชื่อประเทศ หรือรหัส ISO3 (เช่น THA,USA,RUS)")
    t.add_argument("--chapter", default="07")
    t.add_argument("--period", default="2021,2022,2023,2024,2025")
    t.add_argument("--flow", choices=["M", "X"], default="M")

    r = sub.add_parser("usa-rice", help="Monthly USA rice (HS 1006)")
    r.add_argument("--start-year", type=int, default=2025)
    r.add_argument("--end-year", type=int, default=None)

    cr = sub.add_parser("country-rice", help="Monthly country rice (HS 1006) to output/by_country/<Country>.xlsx")
    cr.add_argument("--group", type=int, default=1, help="หมายเลขกลุ่มประเทศ (1-8, กลุ่มละ 35 ประเทศ)")
    cr.add_argument("--countries", default=None, help="ระบุประเทศเป้าหมาย (รองรับ ISO3 เช่น THA,VNM,IND,USA หรือชื่อประเทศ)")
    cr.add_argument("--start-year", type=int, default=2020, help="ปีเริ่มต้น (ค่าเริ่มต้น: 2020)")
    cr.add_argument("--end-year", type=int, default=2026, help="ปีสิ้นสุด (ค่าเริ่มต้น: 2026)")
    cr.add_argument(
        "--incremental",
        action="store_true",
        help="ดึงเฉพาะข้อมูลใหม่ (ปีปัจจุบัน) เพื่ออัปเดตต่อท้ายไฟล์เดิม ประหยัดโควต้า",
    )
    cr.add_argument("--force", action="store_true", help="ดึงทับใหม่ทั้งหมดแม้จะมีไฟล์อยู่แล้ว")
    cr.add_argument("--delay", type=float, default=1.0, help="ระยะเวลาหน่วงระหว่าง Request (วินาที)")

    bm = sub.add_parser("rice-benchmark", help="Compare rice unit prices (USD/kg, USD/ton) and competitiveness")
    bm.add_argument("--countries", default=None, help="ประเทศที่ต้องการเปรียบเทียบ (รองรับ ISO3 เช่น THA,VNM,IND,PAK,USA)")
    bm.add_argument("--flow", choices=["Export", "Import"], default="Export")
    bm.add_argument("--year", type=int, default=None, help="กรองเฉพาะปีที่ระบุ (เช่น 2025)")

    su = sub.add_parser("smart-update", help="Auto-detect recently updated countries and update them incrementally")
    su.add_argument("--days", type=int, default=30, help="ช่วงวันย้อนหลังที่เช็กการปล่อยข้อมูลใหม่ (ค่าเริ่มต้น: 30)")
    su.add_argument("--year", type=int, default=None, help="ปีเป้าหมายที่ต้องการอัปเดต (ค่าเริ่มต้น: ปีปัจจุบัน)")
    su.add_argument("--delay", type=float, default=1.0)

    lu = sub.add_parser("live-updates", help="Check recent dataset release announcements from UN Comtrade")
    lu.add_argument("--days", type=int, default=30)

    sub.add_parser("list-groups", help="Display all country groups")
    sub.add_parser("analysis", help="Final data / trade balance / mirror samples")
    sub.add_parser("check-key", help="Verify API key & output folder")
    sub.add_parser("menu", help="Interactive menu")
    return p


def interactive_menu(api_key: Optional[str] = None) -> None:
    actions = {
        "1": ("ดาวน์โหลด Metadata พื้นฐาน (ประเทศ & HS Codes)", lambda: download_metadata()),
        "2": (
            "ดึงข้อมูลนำเข้าทั่วโลก HS 6 หลัก (หมวด 07 พืชผัก)",
            lambda: download_import_world(
                chapter=input("หมวด 2 หลัก [07]: ").strip() or "07",
                years=_csv_list(input("ปี [2022,2023,2024,2025]: ").strip() or "2022,2023,2024,2025"),
                api_key=api_key,
            ),
        ),
        "3": (
            "ดึงข้อมูล Tariff line 8-11 หลัก (รองรับ ISO3 เช่น USA,RUS)",
            lambda: download_tariffline_imports(
                countries=parse_country_args(input("ระบุประเทศ/ISO3 [USA,RUS]: ").strip() or "USA,RUS"),
                api_key=api_key,
            ),
        ),
        "4": ("ดึงข้อมูลข้าวสหรัฐฯ HS 1006 รายเดือน", lambda: download_usa_rice_monthly(api_key=api_key)),
        "5": (
            "🌾 ดึงข้อมูลข้าวรายประเทศ (เลือก Group 35 ประเทศ หรือระบุ ISO3 เช่น THA,VNM,USA)",
            lambda: download_country_rice_group(
                group_number=int(input("ระบุหมายเลข Group [1-8]: ").strip() or "1") if not input("ต้องการระบุประเทศเองด้วยรหัส ISO3 ไหม? (กด Enter เพื่อเลือกตาม Group / หรือพิมพ์ ISO3): ").strip() else 1,
                countries=input("ระบุรหัสประเทศ ISO3 (เว้นว่างเพื่อใช้ตาม Group): ").strip() or None,
                start_year=int(input("ปีเริ่มต้น [2020]: ").strip() or "2020"),
                end_year=int(input("ปีสิ้นสุด [2026]: ").strip() or "2026"),
                incremental=False,
                api_key=api_key,
            ),
        ),
        "6": (
            "⚡ อัปเดตข้อมูลข้าวรายเดือน (Incremental Update ต่อข้อมูลเฉพาะปีปัจจุบัน)",
            lambda: download_country_rice_group(
                group_number=int(input("ระบุหมายเลข Group ที่ต้องการอัปเดต [1-8]: ").strip() or "1"),
                incremental=True,
                api_key=api_key,
            ),
        ),
        "7": (
            "📊 เปรียบเทียบราคาข้าวโลก (Rice Unit Price Benchmark: THA vs VNM vs IND ฯลฯ)",
            lambda: run_rice_benchmark(
                countries=input("ระบุประเทศ (เช่น THA,VNM,IND,PAK,USA หรือกด Enter เพื่อดูทั้งหมด): ").strip() or None,
                flow=input("ทิศทาง [Export/Import]: ").strip() or "Export",
            ),
        ),
        "8": (
            "🛰️ ตรวจจับการปล่อยข้อมูลใหม่ (Live Releases & Smart Incremental Update)",
            lambda: run_smart_incremental_update(
                days_back=int(input("จำนวนวันย้อนหลังที่เช็ก [30]: ").strip() or "30"),
                api_key=api_key,
            ),
        ),
        "9": ("📋 แสดงรายชื่อกลุ่มประเทศทั้งหมด (List Groups)", lambda: list_country_groups_cli()),
        "10": ("วิเคราะห์ตัวอย่าง (Trade Balance / Mirror Data)", lambda: run_all_samples(api_key=api_key)),
        "11": ("ตรวจสอบสถานะ API Key และโฟลเดอร์ผลลัพธ์", lambda: check_key(api_key)),
    }
    while True:
        print("\n" + "=" * 65 + "\n🌍 UN Comtrade Data Pipeline (ระบบข้อมูลการค้าระหว่างประเทศ)\n" + "=" * 65)
        for k, (name, _) in actions.items():
            print(f"  {k:>2s}. {name}")
        print("   0. ออกจากโปรแกรม (Exit)")
        choice = input("\nกรุณาเลือกเมนู [0-11]: ").strip().lower()
        if choice in ("0", "q", "quit", "exit"):
            return
        if choice not in actions:
            print("⚠️ กรุณาระบุตัวเลข 0 ถึง 11")
            continue
        try:
            actions[choice][1]()
        except (ConfigError, Exception) as e:  # noqa: BLE001 - keep the menu alive
            logger.error("%s", e)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    cmd = args.command or "menu"
    try:
        if cmd == "metadata":
            download_metadata()
        elif cmd == "world-import":
            download_import_world(
                chapter=args.chapter,
                years=_csv_list(args.years),
                api_key=args.api_key,
                delay_between_requests=args.delay,
                use_cache=not args.no_cache,
            )
        elif cmd == "tariffline":
            download_tariffline_imports(
                countries=parse_country_args(args.countries),
                cmd_code=args.chapter,
                period=args.period,
                flow_code=args.flow,
                api_key=args.api_key,
            )
        elif cmd == "usa-rice":
            download_usa_rice_monthly(args.start_year, args.end_year, args.api_key)
        elif cmd == "country-rice":
            download_country_rice_group(
                group_number=args.group,
                start_year=args.start_year,
                end_year=args.end_year,
                incremental=args.incremental,
                force_overwrite=args.force,
                countries=args.countries,
                api_key=args.api_key,
                delay=args.delay,
            )
        elif cmd == "rice-benchmark":
            run_rice_benchmark(
                countries=args.countries,
                flow=args.flow,
                year=args.year,
            )
        elif cmd == "smart-update":
            run_smart_incremental_update(
                days_back=args.days,
                end_year=args.year,
                api_key=args.api_key,
                delay=args.delay,
            )
        elif cmd == "live-updates":
            show_live_updates_cli(days_back=args.days, api_key=args.api_key)
        elif cmd == "list-groups":
            list_country_groups_cli()
        elif cmd == "analysis":
            run_all_samples(args.api_key)
        elif cmd == "check-key":
            return check_key(args.api_key)
        else:
            interactive_menu(args.api_key)
    except ConfigError as e:
        logger.error("%s", e)
        return 1
    except KeyboardInterrupt:
        logger.warning("ยกเลิกโดยผู้ใช้")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
