# 🌍 International Trade Center - UN Comtrade Data Pipeline

ดึงและประมวลผลข้อมูลการค้าระหว่างประเทศจาก **UN Comtrade** ผ่านไลบรารีทางการ [`comtradeapicall`](https://pypi.org/project/comtradeapicall/)

## โครงสร้างโปรเจกต์

```text
comtrade_pipeline/   # โค้ดหลัก (config, api_utils, metadata, country_groups, country_rice, world_import, tariffline, usa_rice, analysis, cli)
run_pipeline.py      # Entry point หลัก -> comtrade_pipeline.cli
tests/               # pytest suite
output/              # ผลลัพธ์ข้อมูล CSV / Excel (gitignored; เปลี่ยนได้ด้วย COMTRADE_OUTPUT_DIR)
  ├── by_country/    # โฟลเดอร์เก็บไฟล์ Excel (.xlsx) แยกรายประเทศ (Sheet: Import, Export)
  └── country_groups.json # แผนผังกลุ่มประเทศ 8 กลุ่ม
country_groups.md    # ตารางอธิบายการแบ่งกลุ่มประเทศทั้ง 8 กลุ่ม
reference/           # เอกสารอ้างอิงและคู่มือ
```

## ติดตั้ง

```bash
python -m venv .venv && .venv\Scripts\activate      # แนะนำ
pip install -r requirements.txt
copy .env.example .env                              # แล้วใส่ COMTRADE_API_KEY
```

API Key อ่านจาก **`.env` / environment variable `COMTRADE_API_KEY`** (หรือ `--api-key` ชั่วคราว)
ขอ Key ฟรีได้ที่ https://comtradedeveloper.un.org/ (แพลน Basic Individual จำกัด 500 Requests/วัน)

---

## 🌾 การดึงข้อมูลข้าวรายประเทศ (Country Rice Pipeline)

ข้อมูลสินค้าข้าว **HS 1006** (รวม 100610, 100620, 100630, 100640) รายเดือน (Monthly) ตั้งแต่ปี **2020 – 2026**

- **ไฟล์ผลลัพธ์:** บันทึกเป็นไฟล์ Excel แยก 1 ประเทศต่อ 1 ไฟล์ ที่ `output/by_country/<CountryName>.xlsx`
- **โครงสร้างไฟล์:** ภายในมี 2 Sheets คือ **`Import`** และ **`Export`**
- **การแบ่งกลุ่ม (Quota Adherence):** ข้อมูล 1 ประเทศใช้ 14 Requests เพื่อไม่ให้เกินโควต้า 500 Requests/วัน จึงแบ่งประเทศทั่วโลกออกเป็นกลุ่มละ **35 ประเทศ (Group 1 ถึง Group 8)**

### คำสั่งใช้งาน

```bash
# 1. ดูรายชื่อประเทศและหมายเลขกลุ่มทั้งหมด
python run_pipeline.py list-groups

# 2. ดึงข้อมูล Group 1 (35 ประเทศหลักที่มีบทบาทต่อตลาดข้าวโลก)
python run_pipeline.py country-rice --group 1

# 3. ดึงกลุ่มถัดไปในวันรุ่งขึ้น (Group 2 ถึง 8)
python run_pipeline.py country-rice --group 2

# 4. บังคับดึงใหม่ทั้งหมดทับไฟล์เดิม (Overwrite)
python run_pipeline.py country-rice --group 1 --force
```

### ⚡ โซลูชั่นการอัปเดตข้อมูลรายเดือนในอนาคต (Incremental Monthly Update)

> **ถาม:** เดือนถัดไปต้องดึงใหม่ทั้งหมด 2020–2026 หรือดึงเฉพาะข้อมูลใหม่มาต่อได้เลย?
> **ตอบ:** **ดึงเฉพาะข้อมูลปีปัจจุบันมาต่อได้เลยครับ!** ไม่จำเป็นต้องดึงข้อมูลปีก่อนหน้าซ้ำให้เปลืองโควต้า

เมื่อรันด้วยคำสั่ง `--incremental`:

```bash
python run_pipeline.py country-rice --group 1 --incremental
```

**กลไกการทำงาน:**

1. ระบบจะโหลดไฟล์ Excel เดิมของประเทศนั้น ๆ ขึ้นมา
2. ส่งคำขอดึงเฉพาะข้อมูลปีปัจจุบัน (เช่น ปี 2026 ใช้เพียง 2 Requests ต่อประเทศ แทนที่จะเป็น 14 Requests)
3. นำข้อมูลใหม่มารวมกับข้อมูลเดิม และ Deduplicate ตัวเลขอัตโนมัติ (`drop_duplicates` บนคีย์ `period`, `partnerCode`, `cmdCode`, `flowCode` โดยเก็บค่าล่าสุด) หาก Comtrade มีการแก้ไขตัวเลขย้อนหลังในเดือนล่าสุดก็จะถูกอัปเดตให้ถูกต้อง
4. บันทึกกลับลง Sheet `Import` และ `Export` ในไฟล์เดิมทันที
5. **ความคุ้มค่า:** การใช้ Incremental Mode ทำให้โควต้า 500 Requests/วัน สามารถอัปเดตได้ถึง **200+ ประเทศในวันเดียว**!

---

## 💻 คำสั่งอื่น ๆ ของระบบ

```bash
python run_pipeline.py                 # เมนูอินเตอร์แอคทีฟ (Interactive Menu)
python run_pipeline.py check-key       # ตรวจสอบสถานะ API Key และโฟลเดอร์ผลลัพธ์
python run_pipeline.py metadata        # ดาวน์โหลดฐานข้อมูลประเทศ และรหัส HS Code
python run_pipeline.py world-import --chapter 07 --years 2022,2023,2024,2025 # นำเข้าทั่วโลก HS6
python run_pipeline.py tariffline --countries "USA:842,Russia:643" --chapter 07 # Tariff line
python run_pipeline.py usa-rice --start-year 2025 # ข้าวสหรัฐฯ 2025-2026 CSV
python run_pipeline.py analysis        # ตัวอย่าง Trade Balance และ Mirror Data
python run_pipeline.py -h              # ดูคำอธิบายทุกคำสั่ง
```

---

## 🚀 ฟีเจอร์ใหม่ (Upgraded Capabilities v2.2.0)

### 1. 🌐 Universal ISO-3 Country Resolver
ระบบรองรับการระบุประเทศด้วยรหัส ISO-3 Alpha (เช่น `THA`, `USA`, `VNM`, `IND`, `PAK`), ชื่อประเทศ (เช่น `Thailand`, `United States`), หรือรหัส UN M49 ตัวเลข (`764`, `842`) ได้อย่างอิสระในทุกคำสั่ง โดยใช้ In-memory lookup ร่วมกับ Local Metadata Cache ทำให้แปลงรหัสได้ในระดับไมโครวินาทีโดยไม่เสียโควต้าเน็ตเวิร์ก

```bash
# ดึงข้อมูลข้าวเฉพาะกลุ่มประเทศที่สนใจผ่าน ISO3
python run_pipeline.py country-rice --countries THA,VNM,IND,USA,PAK

# ดึง Tariff line โดยระบุรหัส ISO3
python run_pipeline.py tariffline --countries "THA,USA" --chapter 10
```

---

### 2. 📊 ระบบวิเคราะห์ราคาข้าวโลก (Rice Unit Price Benchmark)
วิเคราะห์และเปรียบเทียบ Unit Value (USD/kg และ USD/ตัน) ของข้าว (HS 1006) พร้อมคัดกรองตัวเลขผิดปกติด้วยสถิติ **IQR Outlier Removal (Log Scale)** และเจาะลึกตามชนิดข้าวย่อย:
- `100610`: ข้าวเปลือก (Paddy)
- `100620`: ข้าวกล้อง (Brown Rice)
- `100630`: ข้าวขาวขัดสี (Milled/Semi-milled Rice)
- `100640`: ปลายข้าว (Broken Rice)

```bash
# เปรียบเทียบผู้ส่งออกข้าวหลักของโลก ปี 2025
python run_pipeline.py rice-benchmark --countries THA,VNM,IND,PAK,USA --flow Export --year 2025

# วิเคราะห์ทุกประเทศที่มีไฟล์ข้อมูลใน output/by_country/
python run_pipeline.py rice-benchmark --flow Export
```
ผลลัพธ์จะแสดงตารางสรุปบน CLI และส่งออกเป็น Dashboard ที่ `output/rice_unit_price_benchmark.xlsx` (Sheet: `Country_Summary`, `Subheading_Breakdown`, `Monthly_Trend`) และไฟล์ CSV

---

### 3. 📡 การอัปเดตอัจฉริยะผ่าน Comtrade Live Releases (Smart Update)
ตรวจสอบรอบการเผยแพร่ข้อมูลล่าสุดของ UN Comtrade API ด้วย `getLiveUpdate` / `getComtradeReleases` เพื่อตรวจจับว่าประเทศใดบ้างที่มีข้อมูลเดือนใหม่เข้ามาในช่วง N วันที่ผ่านมา แล้วทำการอัปเดตเฉพาะประเทศเหล่านั้นโดยอัตโนมัติ ช่วยประหยัดโควต้าได้มากกว่า 90%

```bash
# ตรวจสอบว่า Comtrade เพิ่งปล่อยข้อมูลประเทศใดบ้างใน 14 วันล่าสุด
python run_pipeline.py live-updates --days 14

# สั่ง Smart Update เฉพาะประเทศที่มีข้อมูลใหม่ปล่อยออกมาใน 30 วันล่าสุด
python run_pipeline.py smart-update --days 30
```

---

## 🤖 สถาปัตยกรรม AI Agent & Skills (Antigravity Standard)

โปรเจกต์นี้ได้รับการออกแบบตามมาตรฐาน **Google Deepmind Antigravity System**:
- [AGENTS.md](AGENTS.md) — กฎเหล็กด้านโควต้า API, ข้อกำหนดการจัดการข้อมูล, และแนวทางการทำงานของ AI Agent
- `.agents/skills/comtrade-pipeline/` — ทักษะการรัน Pipeline, จัดการกลุ่มประเทศ และ Incremental Update
- `.agents/skills/comtrade-api-v14/` — ดัชนีอ้างอิง API ทั้ง 41 ฟังก์ชันของ `comtradeapicall` v1.4.0
- `.agents/skills/trade-data-analytics/` — คู่มือการคำนวณ Unit Values, Outlier Detection และ Bilateral Discrepancy

---

## 📁 ไฟล์ผลลัพธ์ (`output/`)

| พาธ / ไฟล์                                           | คำอธิบาย                                                                 |
| :--------------------------------------------------- | :----------------------------------------------------------------------- |
| `output/by_country/<CountryName>.xlsx`               | ไฟล์ Excel สถิติข้าวรายเดือน 2020–2026 รายประเทศ (Sheet: Import, Export) |
| `output/country_groups.json`                         | แผนผังรายชื่อประเทศแบ่งกลุ่ม 1–8 ในรูปแบบ JSON                           |
| `country_groups.md`                                  | เอกสารตารางอธิบายรายละเอียดของทั้ง 8 กลุ่มประเทศ                         |
| `metadata_countries.csv`, `metadata_hscodes.csv`     | ตารางอ้างอิงประเทศ / รหัส HS                                             |
| `import_<chapter>_world.csv`                         | นำเข้าทั่วโลก HS6 รายหมวด                                                |
| `tariffline_<flow>_<chapter>.csv`                    | Tariff line 8–11 หลัก                                                    |
| `usa_import_1006_monthly_<ปี>.csv`, `usa_export_...` | ข้าวสหรัฐฯ รายเดือน                                                      |
| `trade_balance_*.csv`, `bilateral_mirror_*.csv`      | ผลจากฟังก์ชันวิเคราะห์ดุลการค้าและ Mirror Data                           |

---

## 📖 เอกสารเพิ่มเติม

- [country_groups.md](country_groups.md) — แผนผังรายชื่อประเทศทั้ง 8 กลุ่ม
- [column.md](column.md) — Data dictionary อธิบายความหมายของแต่ละคอลัมน์
- [Tricks.md](Tricks.md) — เทคนิคและข้อควรระวังในการใช้งาน UN Comtrade API
- [my_license.md](my_license.md) — ข้อมูลขีดจำกัดสิทธิ์แพลน Basic Individual
