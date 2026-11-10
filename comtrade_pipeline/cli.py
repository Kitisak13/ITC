"""Command-line interface for the UN Comtrade pipeline."""

import argparse
import logging
import sys
from typing import List, Optional

from .analysis import run_all_samples
from .config import ConfigError, get_api_key, get_output_dir, mask_key, setup_logging
from .metadata import download_metadata
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

    t = sub.add_parser("tariffline", help="Tariff line data (8-11 digits)")
    t.add_argument("--countries", default="USA:842,Russia:643")
    t.add_argument("--chapter", default="07")
    t.add_argument("--period", default="2021,2022,2023,2024,2025")
    t.add_argument("--flow", choices=["M", "X"], default="M")

    r = sub.add_parser("usa-rice", help="Monthly USA rice (HS 1006)")
    r.add_argument("--start-year", type=int, default=2025)
    r.add_argument("--end-year", type=int, default=None)

    sub.add_parser("analysis", help="Final data / trade balance / mirror samples")
    sub.add_parser("check-key", help="Verify API key & output folder")
    sub.add_parser("menu", help="Interactive menu")
    return p


def interactive_menu(api_key: Optional[str] = None) -> None:
    actions = {
        "1": ("ดาวน์โหลด Metadata", lambda: download_metadata()),
        "2": ("นำเข้าทั่วโลก HS6 รายหมวด", lambda: download_import_world(
            chapter=input("หมวด 2 หลัก [07]: ").strip() or "07",
            years=_csv_list(input("ปี [2022,2023,2024,2025]: ").strip() or "2022,2023,2024,2025"),
            api_key=api_key)),
        "3": ("Tariff line (USA & Russia)", lambda: download_tariffline_imports(api_key=api_key)),
        "4": ("ข้าวสหรัฐฯ HS 1006 รายเดือน", lambda: download_usa_rice_monthly(api_key=api_key)),
        "5": ("วิเคราะห์ตัวอย่าง", lambda: run_all_samples(api_key=api_key)),
        "6": ("ตรวจสอบ API Key", lambda: check_key(api_key)),
    }
    while True:
        print("\n" + "=" * 60 + "\n🌍 UN Comtrade Data Pipeline\n" + "=" * 60)
        for k, (name, _) in actions.items():
            print(f"  {k}. {name}")
        print("  0. ออก")
        choice = input("เลือกเมนู [0-6]: ").strip().lower()
        if choice in ("0", "q", "quit", "exit"):
            return
        if choice not in actions:
            print("⚠️ กรุณาระบุตัวเลข 0 ถึง 6")
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
            download_import_world(chapter=args.chapter, years=_csv_list(args.years), api_key=args.api_key,
                                  delay_between_requests=args.delay, use_cache=not args.no_cache)
        elif cmd == "tariffline":
            download_tariffline_imports(countries=parse_country_args(args.countries), cmd_code=args.chapter,
                                        period=args.period, flow_code=args.flow, api_key=args.api_key)
        elif cmd == "usa-rice":
            download_usa_rice_monthly(args.start_year, args.end_year, args.api_key)
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
        logger.warning("ยกเลิกโดยผู้ใช้ (ข้อมูลที่ดึงแล้วถูกแคชไว้ รันซ้ำเพื่อทำต่อ)")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())

