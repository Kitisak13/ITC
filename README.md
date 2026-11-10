# 🌍 International Trade Center - UN Comtrade Data Pipeline

ดึงและประมวลผลข้อมูลการค้าระหว่างประเทศจาก **UN Comtrade** ผ่านไลบรารีทางการ [`comtradeapicall`](https://pypi.org/project/comtradeapicall/) (ติดตั้งจาก PyPI)

## โครงสร้างโปรเจกต์

```text
comtrade_pipeline/   # โค้ดหลัก (config, api_utils, metadata, world_import, tariffline, usa_rice, analysis, cli)
run_pipeline.py      # entry point บาง ๆ -> comtrade_pipeline.cli
tests/               # pytest
output/              # ผลลัพธ์ CSV (gitignored; เปลี่ยนได้ด้วย COMTRADE_OUTPUT_DIR)
reference/           # สำเนา upstream comtradeapicall (ตัวอย่าง/เอกสารเท่านั้น ไม่ได้ถูก import)
```

## ติดตั้ง

```bash
python -m venv .venv && .venv\Scripts\activate      # แนะนำ
pip install -r requirements.txt
copy .env.example .env                              # แล้วใส่ COMTRADE_API_KEY
```

API Key อ่านจาก **`.env` / environment variable `COMTRADE_API_KEY`** เท่านั้น (หรือ `--api-key` ชั่วคราว) — ไม่รองรับ `api_key.txt` อีกต่อไป และ `.env` ถูก gitignore แล้ว
ขอ key ได้ที่ https://comtradedeveloper.un.org/

## การใช้งาน

```bash
python run_pipeline.py                 # เมนูอินเตอร์แอคทีฟ
python run_pipeline.py check-key
python run_pipeline.py metadata
python run_pipeline.py world-import --chapter 07 --years 2022,2023,2024,2025 [--no-cache]
python run_pipeline.py tariffline --countries "USA:842,Russia:643" --chapter 07 --period 2021,2022,2023
python run_pipeline.py usa-rice --start-year 2025
python run_pipeline.py analysis
python run_pipeline.py -h              # รายละเอียดทุกคำสั่ง
```

หรือใช้เป็นไลบรารี:

```python
from comtrade_pipeline import download_import_world, download_tariffline_imports
df = download_import_world(chapter="07", years=["2023", "2024"])
```

## คุณสมบัติด้าน production

- **Resume ได้:** ทุกคำขอ world-import ถูกแคชใน `output/.cache/` รันซ้ำเพื่อทำต่อจากจุดที่ค้าง (`--no-cache` เพื่อบังคับดึงใหม่)
- **ตรวจจับข้อมูลถูกตัด:** ถ้าผลลัพธ์ถึง 250,000 แถว จะแบ่งชุดรหัสครึ่งหนึ่งแล้วดึงใหม่อัตโนมัติ
- **Retry อย่างฉลาด:** retry เฉพาะ network/5xx/429; 400/401/403/404 ล้มเหลวทันที
- **บันทึกคำขอที่ล้มเหลว** เป็น `*_failed_requests.csv`
- Exit code ไม่เป็นศูนย์เมื่อตั้งค่าผิดพลาด; ไม่แสดง API key (mask เสมอ)

## ทดสอบ

```bash
pytest
```

## ไฟล์ผลลัพธ์ (`output/`)

| ไฟล์                                                                | คำอธิบาย                     |
| :------------------------------------------------------------------ | :--------------------------- |
| `metadata_countries.csv`, `metadata_hscodes.csv`                    | ตารางอ้างอิงประเทศ / รหัส HS |
| `import_<chapter>_world.csv`                                        | นำเข้าทั่วโลก HS6 รายหมวด    |
| `tariffline_<flow>_<chapter>.csv`                                   | Tariff line 8–11 หลัก        |
| `usa_import_1006_monthly_<ปี>.csv`, `usa_export_...`                | ข้าวสหรัฐฯ รายเดือน          |
| `trade_balance_*.csv`, `bilateral_mirror_*.csv`, `final_data_*.csv` | ผลจากฟังก์ชันวิเคราะห์       |

## เอกสารเพิ่มเติม

- [column.md](column.md) — Data dictionary
- [Tricks.md](Tricks.md) — เทคนิค/ข้อควรระวังของ API
