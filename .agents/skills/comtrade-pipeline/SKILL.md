---
name: comtrade-pipeline
description: >-
  Executes, configures, and maintains the UN Comtrade data pipeline for international trade.
  Use when the user asks to download country trade data, run daily batches, execute
  incremental monthly updates, check API key status, or manage country groups.
---

# Comtrade Pipeline Runbook & Operational Skill

ทักษะสำหรับการควบคุม รัน และดูแลระบบ Pipeline ดึงข้อมูลสถิติการค้าของ UN Comtrade ในโปรเจกต์นี้

---

## 🚀 สรุปคำสั่งสำคัญ (Quick Commands)

```bash
# ตรวจสอบสถานะการเชื่อมต่อและ API Key
python run_pipeline.py check-key

# ดูรายชื่อกลุ่มประเทศทั้ง 8 กลุ่ม
python run_pipeline.py list-groups

# รันดึงข้อมูลข้าวรายประเทศตามกลุ่มประจำวัน (Group 1 ถึง 8)
python run_pipeline.py country-rice --group 1

# อัปเดตข้อมูลรายเดือนในอนาคต (Incremental Update เฉพาะปีปัจจุบัน)
python run_pipeline.py country-rice --group 1 --incremental

# บังคับดึงใหม่ทั้งหมดทับไฟล์เดิม (Force overwrite)
python run_pipeline.py country-rice --group 1 --force

# ดึงข้อมูลนำเข้าหมวด 07 พืชผักระดับโลก
python run_pipeline.py world-import --chapter 07 --years 2022,2023,2024,2025

# ดึงข้อมูลพิกัดศุลกากรระดับประเทศ 8-11 หลัก (Tariff Line)
python run_pipeline.py tariffline --countries "USA:842,Russia:643" --chapter 07
```

---

## 📋 ขั้นตอนการปฏิบัติงาน (Standard Operating Procedures)

### 1. การรันรอบประจำวัน (Daily Batch Execution)
1. ตรวจสอบตารางกลุ่มประเทศใน [country_groups.md](../../../country_groups.md)
2. รันคำสั่งตามกลุ่มของวันนั้น เช่น วันที่ 2 รัน Group 2:
   ```bash
   python run_pipeline.py country-rice --group 2
   ```
3. ระบบจะตรวจสอบไฟล์ใน `output/by_country/` อัตโนมัติ:
   - หากประเทศใดมีไฟล์ที่สมบูรณ์อยู่แล้ว ระบบจะข้าม (`Skip`) เพื่อประหยัดโควต้า
   - ระบบจะหยุดอัตโนมัติเมื่อจำนวน Request ในเซสชันถึง **485 Requests** (Quota Safety Valve)
4. ตรวจสอบไฟล์ผลลัพธ์ใน `output/by_country/<CountryName>.xlsx`

### 2. การอัปเดตรอบเดือนใหม่ (Monthly Incremental Update)
เมื่อขึ้นเดือนใหม่และต้องการอัปเดตตัวเลขล่าสุด:
```bash
python run_pipeline.py country-rice --group 1 --incremental
```
- ระบบจะโหลดไฟล์เดิมใน `output/by_country/<CountryName>.xlsx`
- ดึงเฉพาะข้อมูลปีปัจจุบัน (ใช้เพียง 2 Requests ต่อประเทศ)
- นำข้อมูลใหม่มารวมกับข้อมูลเดิมและทำ Deduplication อัตโนมัติ

---

## 🛡️ การจัดการข้อผิดพลาดและโควต้า (Troubleshooting)

1. **โควต้าเต็ม (HTTP 429 Too Many Requests):**
   - ตัวนับใน `QuotaTracker` จะดักจับไว้ที่ 485 requests
   - หากเกิด 429 ให้หยุดการรันทันที รอให้พ้นเวลา 00:00 UTC (รีเซ็ตโควต้ารายวันของ UN Comtrade) แล้วค่อยรันต่อ
2. **เครือข่ายกระตุก (Connection Flickers):**
   - `safe_api_call` มีระบบ Retry แบบ Exponential Backoff อัตโนมัติ 3 ครั้ง
   - ไฟล์คำขอที่ล้มเหลวอย่างถาวรจะถูกบันทึกไว้ใน `output/*_failed_requests.csv` สามารถตรวจสอบและดึงซ่อมได้

---

## 🧪 การทดสอบระบบ (Automated Tests)
รัน Unit Tests ของ Pipeline ทั้งหมด:
```bash
python -m pytest
```

