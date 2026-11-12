"""
Country grouping and scheduling for UN Comtrade rice data downloads.
Divides valid global countries into batches of 35 countries per day
to adhere strictly to the 500 requests/day Basic Individual quota.
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple
import pandas as pd

from .config import ROOT_DIR, get_output_dir

# 35 Top global rice trading countries (Group 1)
TOP_35_RICE_COUNTRIES: List[Tuple[str, str]] = [
    ("699", "India"),
    ("764", "Thailand"),
    ("704", "Viet Nam"),
    ("586", "Pakistan"),
    ("842", "USA"),
    ("104", "Myanmar"),
    ("116", "Cambodia"),
    ("156", "China"),
    ("76", "Brazil"),
    ("858", "Uruguay"),
    ("600", "Paraguay"),
    ("380", "Italy"),
    ("32", "Argentina"),
    ("724", "Spain"),
    ("36", "Australia"),
    ("328", "Guyana"),
    ("608", "Philippines"),
    ("360", "Indonesia"),
    ("566", "Nigeria"),
    ("50", "Bangladesh"),
    ("682", "Saudi Arabia"),
    ("368", "Iraq"),
    ("364", "Iran"),
    ("784", "United Arab Emirates"),
    ("458", "Malaysia"),
    ("392", "Japan"),
    ("410", "Rep. of Korea"),
    ("686", "Senegal"),
    ("384", "Côte d'Ivoire"),
    ("484", "Mexico"),
    ("710", "South Africa"),
    ("826", "United Kingdom"),
    ("251", "France"),
    ("276", "Germany"),
    ("124", "Canada"),
]


def load_all_country_groups(group_size: int = 35) -> Dict[int, List[Dict[str, str]]]:
    """
    Builds and returns all country groups.
    Group 1: Top 35 rice exporters & importers.
    Group 2..N: Remaining active reporting countries (35 per group).
    """
    meta_path = get_output_dir() / "metadata_countries.csv"
    if not meta_path.is_file():
        # Fallback to Group 1 only if metadata not found
        return {1: [{"code": c, "name": n} for c, n in TOP_35_RICE_COUNTRIES]}

    df = pd.read_csv(meta_path, dtype={"CountryCode": str})
    valid = df[df["entryExpiredDate"].isna() & (df["isGroup"] == False)].copy()

    # Normalize codes to strings
    valid["CountryCode"] = valid["CountryCode"].astype(str)
    
    # Extract Group 1 codes
    g1_codes = {c for c, _ in TOP_35_RICE_COUNTRIES}
    g1_list = [{"code": c, "name": n} for c, n in TOP_35_RICE_COUNTRIES]

    # Remaining countries sorted alphabetically
    remaining = valid[~valid["CountryCode"].isin(g1_codes)].sort_values("CountryName")
    rem_list = [{"code": r["CountryCode"], "name": r["CountryName"]} for _, r in remaining.iterrows()]

    groups: Dict[int, List[Dict[str, str]]] = {1: g1_list}
    current_group = 2
    for i in range(0, len(rem_list), group_size):
        chunk = rem_list[i : i + group_size]
        groups[current_group] = chunk
        current_group += 1

    return groups


def export_country_groups_files():
    """Generate country_groups.md and output/country_groups.json"""
    groups = load_all_country_groups()
    out_dir = get_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. JSON Export
    json_path = out_dir / "country_groups.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)

    # 2. Markdown Export
    md_path = ROOT_DIR / "country_groups.md"
    lines = [
        "# 🌍 แผนผังการแบ่งกลุ่มประเทศสำหรับดึงข้อมูลข้าว (Country Groups Schedule)",
        "",
        "ระบบแบ่งประเทศทั่วโลกออกเป็นกลุ่มละ **ไม่เกิน 35 ประเทศ** เพื่อให้อยู่ในโควต้า **500 Requests/วัน** (14 requests ต่อประเทศ)",
        "",
    ]
    for grp_num, countries in groups.items():
        lines.append(f"## 📅 Group {grp_num} ({len(countries)} ประเทศ)")
        if grp_num == 1:
            lines.append("> **หมายเหตุ:** กลุ่มประเทศผู้มีบทบาทหลักในตลาดข้าวโลก (Top Exporters & Importers)")
        lines.append("")
        lines.append("| ลำดับ | รหัส UN M49 | ชื่อประเทศ (Country Name) |")
        lines.append("| :---: | :---: | :--- |")
        for idx, c in enumerate(countries, 1):
            lines.append(f"| {idx} | `{c['code']}` | {c['name']} |")
        lines.append("")
        lines.append(f"**คำสั่งรันกลุ่มนี้:** `python run_pipeline.py --mode country-rice --group {grp_num}`")
        lines.append("")
        lines.append("---")
        lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return json_path, md_path

