# 🤖 AI Agent Guidelines for International Trade Center (UN Comtrade Pipeline)

เอกสารฉบับนี้กำหนดกฎเกณฑ์ บทบาท และแนวทางการทำงานสำหรับ AI Agent ทุกตัวที่เข้ามาร่วมพัฒนา ตรวจสอบ หรือปฏิบัติงานในโปรเจกต์นี้ เพื่อให้การทำงานสอดคล้องกับมาตรฐาน Antigravity และระบบฐานข้อมูล UN Comtrade

---

## 🎯 1. บริบทและเป้าหมายของโปรเจกต์ (Project Mission)
โปรเจกต์นี้เป็นระบบ **Data Pipeline และ Analytics สำหรับข้อมูลสถิติการค้าระหว่างประเทศ** โดยดึงข้อมูลจาก **UN Comtrade Database** ผ่านไลบรารีทางการ `comtradeapicall` (รองรับฟีเจอร์เวอร์ชัน 1.4.0) โดยมีเป้าหมายหลักคือ:
1. ดึงและจัดเก็บข้อมูลสถิติการค้าสินค้าข้าวทั่วโลก (HS Code 1006 และประเภทย่อย 6 หลักทั้งหมด) แบบรายเดือน (Monthly) ย้อนหลังปี 2020 ถึงปัจจุบัน
2. จัดเก็บข้อมูลแยกเป็นไฟล์ **Excel (.xlsx)** 1 ประเทศต่อ 1 ไฟล์ ที่ `output/by_country/<CountryName>.xlsx` โดยมี 2 Sheets คือ `Import` และ `Export`
3. รองรับการประมวลผลและการอัปเดตข้อมูลรายเดือนในอนาคตด้วยระบบ **Incremental Update**

---

## ⚠️ 2. กฎเหล็กด้านสิทธิ์และโควต้า API (License & Quota Constraints)

> [!IMPORTANT]
> ผู้ใช้งานใช้บัญชี **Basic Individual (Free)** ซึ่งมีข้อจำกัดที่ Agent ต้องปฏิบัติตามอย่างเคร่งครัด:

1. **เพดานโควต้า 500 Requests ต่อวัน:**
   - การดึงข้อมูล 1 ประเทศ ครอบคลุม 7 ปี (2020–2026) ทั้ง Import และ Export ใช้ **14 Requests**
   - **ห้าม** ยิงคำขอดึงข้อมูลเกิน 35 ประเทศในวันเดียวกัน เพราะจะชนเพดาน 500 Requests/วัน
   - ต้องใช้ระบบ **Country Groups (Group 1 ถึง 8)** โดยดึงวันละ 1 กลุ่ม (กลุ่มละ 35 ประเทศ)
   - โมดูล `QuotaTracker` จะตัดการทำงานอัตโนมัติที่ **485 Requests** เสมอเพื่อความปลอดภัย ห้ามปลดล็อกตัวนับนี้เด็ดขาด
2. **อัตราการส่งคำขอ (Rate Limit):**
   - API อนุญาตสูงสุด 5 Requests ต่อวินาที
   - ต้องมี `time.sleep(1.0)` ถึง `1.5` วินาที คั่นระหว่าง Request เสมอ
3. **ขีดจำกัดแถวข้อมูล:**
   - แพลนนี้รับข้อมูลได้สูงสุด 100,000 แถวต่อ 1 Request (ถ้าคำขอมีขนาดใหญ่ ต้องใช้กลไก Chunking)

---

## 🧱 3. กฎเชิงเทคนิคของ UN Comtrade API (API Protocol Rules)

1. **กฎ 12 ช่วงเวลา (The 12-Period Rule):**
   - การดึงข้อมูลรายเดือน (`freqCode='M'`) สามารถส่ง `period` ได้สูงสุด **12 เดือนต่อ 1 Request** เท่านั้น เช่น `period='202401,202402,...,202412'`
   - ห้ามส่งมากกว่า 12 เดือนในคำขอเดียวเด็ดขาด
2. **กฎการแบ่งชุดรหัสสินค้า (Max 20 Commodity Codes):**
   - ส่ง `cmdCode` ได้สูงสุด 20 รหัสต่อ Request (สินค้าข้าวของเรามี 5 รหัส `1006,100610,100620,100630,100640` จึงส่งใน Request เดียวได้)
3. **พารามิเตอร์ที่ไม่ได้ใช้ของ `getTarifflineData`:**
   - ต้องส่ง `partner2Code=None, customsCode=None, motCode=None, countOnly=None` เป็น `None` เสมอ ห้ามละเว้นเพื่อป้องกันบั๊กใน SDK

---

## 🔄 4. กลยุทธ์การอัปเดตข้อมูลรายเดือน (Monthly Update Strategy)

เมื่อถึงรอบเดือนใหม่และต้องการอัปเดตข้อมูล:
- **ห้าม** สั่งดึงข้อมูลใหม่ทั้งหมด (2020–2026) เพราะจะเปลืองโควต้า 14 requests/ประเทศ
- **ต้อง** ใช้โหมด **Incremental Update** (`--incremental`) ซึ่งจะดึงเฉพาะข้อมูลปีปัจจุบัน (ใช้เพียง **2 Requests ต่อประเทศ**)
- ระบบจะอ่านไฟล์ Excel เดิมใน `output/by_country/` นำข้อมูลเดือนใหม่มารวม และใช้ `drop_duplicates(subset=['period', 'partnerCode', 'cmdCode', 'flowCode'], keep='last')` เพื่อ Upsert ข้อมูลอัตโนมัติ

---

## 📂 5. มาตรฐานโครงสร้างโค้ดและข้อมูล (Code & Data Standards)

1. **ความปลอดภัยของ Credentials:**
   - ห้าม Hardcode API Key ลงในซอร์สโค้ดเด็ดขาด
   - เรียกผ่าน `comtrade_pipeline.config.get_api_key()` ซึ่งจะอ่านจาก `.env` หรือ Environment Variable `COMTRADE_API_KEY`
   - ห้ามนำไฟล์ `.env` เข้า Version Control
2. **คอลัมน์มาตรฐานของตาราง:**
   - ข้อมูลทุกตารางต้องจัดเรียงและเก็บคอลัมน์มาตรฐาน:
     `['period', 'reporterCode', 'reporterDesc', 'partnerCode', 'partnerDesc', 'cmdCode', 'cmdDesc', 'flowCode', 'flowDesc', 'primaryValue', 'netWgt', 'qty', 'qtyUnitAbbr']`
   - เรียงลำดับแถวด้วย: `['period', 'cmdCode', 'partnerDesc']`
3. **การบันทึกไฟล์ Excel และ CSV:**
   - บันทึกไฟล์ Excel ด้วย `openpyxl`
   - บันทึกไฟล์ CSV ด้วยการเข้ารหัส `utf-8-sig` (UTF-8 BOM) เสมอ เพื่อให้เปิดใน Microsoft Excel ภาษาไทยได้โดยสระไม่เพี้ยน
4. **การรันคำสั่งที่ต้องต่อเน็ตเวิร์ก:**
   - บนสภาพแวดล้อม Sandboxed Terminal ของ Windows คำสั่งที่เรียก API ไปยัง `comtradeapi.un.org` ต้องได้รับอนุญาตให้รันนอก Sandbox (`BypassSandbox: true`)

---

## 🛠️ 6. รายการทักษะเสริม (Skills Suite) สำหรับ Agent

Agent สามารถเปิดใช้งาน Workspace Skills เพิ่มเติมใน `.agents/skills/` ได้ดังนี้:
- **`comtrade-pipeline`**: คู่มือการรัน Pipeline, จัดการกลุ่มประเทศ, รัน Incremental Update และจัดการระบบ
- **`comtrade-api-v14`**: สารบัญและเอกสารอ้างอิง API ทั้ง 41 ฟังก์ชันของ `comtradeapicall` เวอร์ชัน 1.4.0
- **`trade-data-analytics`**: คู่มือและสูตรการวิเคราะห์ข้อมูลการค้า (Unit Value, Outlier Removal, Bilateral Mirror CIF vs FOB, Market Share)

