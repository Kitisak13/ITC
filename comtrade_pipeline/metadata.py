"""Download base reference data (countries, HS codes) from UN Comtrade."""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from .config import get_output_dir

logger = logging.getLogger("comtrade_pipeline")

BASE_URL = "https://comtradeapi.un.org/files/v1/app/reference"


def _download_reference(name: str, out_file: Path, rename: dict, timeout: int) -> Path:
    url = f"{BASE_URL}/{name}.json"
    logger.info("กำลังดึงข้อมูลจาก %s ...", url)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json().get("results", []))
    if df.empty:
        raise RuntimeError(f"ไม่ได้รับข้อมูลจาก {url}")
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    out_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_file, index=False, encoding="utf-8-sig")
    logger.info("✅ บันทึก %s รายการ -> %s", f"{len(df):,}", out_file)
    return out_file


def download_countries_metadata(output_dir: Optional[Path] = None) -> Path:
    """Download all partner areas -> metadata_countries.csv"""
    out = Path(output_dir) if output_dir else get_output_dir()
    return _download_reference("partnerAreas", out / "metadata_countries.csv",
                               {"id": "CountryCode", "text": "CountryName"}, timeout=60)


def download_hscodes_metadata(output_dir: Optional[Path] = None) -> Path:
    """Download the HS code dictionary -> metadata_hscodes.csv"""
    out = Path(output_dir) if output_dir else get_output_dir()
    return _download_reference("HS", out / "metadata_hscodes.csv",
                               {"id": "HSCode", "text": "Description", "parent": "ParentCode"}, timeout=120)


def download_metadata(output_dir: Optional[Path] = None) -> None:
    """Download all reference metadata."""
    logger.info("🚀 เริ่มดาวน์โหลด Metadata พื้นฐานจาก UN Comtrade...")
    download_countries_metadata(output_dir)
    download_hscodes_metadata(output_dir)
    logger.info("🎉 ดาวน์โหลด Metadata ครบถ้วน")

