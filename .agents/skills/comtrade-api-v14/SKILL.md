---
name: comtrade-api-v14
description: >-
  Comprehensive guide and API reference for UN Comtrade Python SDK (comtradeapicall v1.4.0).
  Use when writing scripts, calling Comtrade endpoints, fetching world market share,
  checking live data releases, tracking trade matrices, or translating country ISO codes.
---

# UN Comtrade API v1.4.0 Master Skill & Reference

คู่มือและเอกสารอ้างอิงฟังก์ชันทั้งหมดของไลบรารีทางการ `comtradeapicall` (เวอร์ชัน 1.4.0) ครอบคลุมทั้ง **41 ฟังก์ชันหลัก** สำหรับให้นักพัฒนาและ AI Agent ใช้งานได้ทันที

---

## 📌 1. การดึงข้อมูลทั่วไปและข้อมูลทดลอง (Preview & Retrieval)

| ฟังก์ชัน | สิทธิ์ (Auth) | รูปแบบผลลัพธ์ | คำอธิบาย |
| :--- | :---: | :---: | :--- |
| **`getFinalData(...)`** | Required Key | `DataFrame` | ดึงข้อมูลมาตรฐานสากล (Final Data) ระดับ HS 2, 4, 6 หลัก |
| **`previewFinalData(...)`** | **Public (No Key)** | `DataFrame` | ดูตัวอย่างข้อมูล Final Data สูงสุด 500 แถวแรก |
| **`getTarifflineData(...)`** | Required Key | `DataFrame` | ดึงข้อมูลพิกัดระดับประเทศ 8–11 หลัก (National Tariff Line) |
| **`previewTarifflineData(...)`** | **Public (No Key)** | `DataFrame` | ดูตัวอย่างข้อมูล Tariff Line สูงสุด 500 แถวแรก |
| **`getCountFinalData(...)`** | Required Key | `DataFrame` | เช็กจำนวนแถวผลลัพธ์ที่จะได้ล่วงหน้า (ช่วยประหยัดเวลา) |
| **`getMBS(...)`** | Optional Key | `DataFrame` / `txt` | ดึงสถิติจาก Monthly Bulletin of Statistics ของ UN |

```python
import comtradeapicall

# ตัวอย่างการดึง Final Data ด้วย API Key
df = comtradeapicall.getFinalData(
    subscription_key="YOUR_KEY",
    typeCode="C", freqCode="M", clCode="HS",
    period="202501,202502", reporterCode="842",
    cmdCode="1006", flowCode="M", partnerCode=None,
    maxRecords=100000, format_output="JSON",
    breakdownMode="classic", includeDesc=True
)
```

---

## 📊 2. ฟังก์ชันวิเคราะห์เชิงลึก (Analytical Views & Market Share)

### `getWorldShare(...)` ⭐ **(ไม่ต้องใช้ API Key)**
ดึงสัดส่วนส่วนแบ่งตลาดโลกของสินค้าและประเทศเป้าหมาย:
```python
# ดูส่วนแบ่งตลาดโลกของการส่งออกข้าวไทย
df_share = comtradeapicall.getWorldShare(
    typeCode="C", freqCode="A", period="2023",
    reporterCode="764"  # Thailand
)
```

### `getTradeBalance(...)`
ดึงข้อมูลดุลการค้า (ยอดส่งออก FOB ลบด้วยยอดนำเข้า CIF) โดยระบบจะคำนวณคอลัมน์ `TradeBalance` ให้ทันที:
```python
df_balance = comtradeapicall.getTradeBalance(
    subscription_key="YOUR_KEY",
    typeCode="C", freqCode="A", clCode="HS",
    period="2023", reporterCode="764", cmdCode="TOTAL"
)
```

### `getBilateralData(...)`
เปรียบเทียบตัวเลขการค้าระหว่าง 2 ประเทศ (Mirror Data) เพื่อตรวจสอบความสอดคล้องหรือส่วนต่าง (Discrepancy):
```python
df_mirror = comtradeapicall.getBilateralData(
    subscription_key="YOUR_KEY",
    typeCode="C", freqCode="A", clCode="HS",
    period="2023", reporterCode="764", partnerCode="842",
    cmdCode="1006", flowCode="X"
)
```

### `getTradeMatrix(...)` & `getTradeMatrixGroup(...)`
ดึงตารางเมทริกซ์การค้า และสามารถจัดกลุ่มรวมยอดประเทศด้วยเครื่องหมาย `+` ได้โดยตรงจากระดับ API:
```python
# รวมยอดส่งออกของไทยและเวียดนามเป็นก้อนเดียว
df_grouped = comtradeapicall.getTradeMatrixGroup(
    subscription_key="YOUR_KEY",
    typeCode="C", freqCode="A",
    period="2022+2023",
    reporterCode="764+704",  # ไทย + เวียดนาม
    cmdCode="TOTAL", flowCode="X", partnerCode="0"
)
```

---

## 🔍 3. ตรวจสอบข้อมูลก่อนดึงจริง (Availability & Release Tracking)

| ฟังก์ชัน | สิทธิ์ (Auth) | ประโยชน์สำคัญ |
| :--- | :---: | :--- |
| **`getLiveUpdate(...)`** | Required Key | ตรวจสอบว่าในรอบสัปดาห์/เดือน มีประเทศไหนเพิ่งส่งข้อมูลใหม่เข้ามาบ้าง |
| **`getComtradeReleases(...)`** | **Public (No Key)** | ดูปฏิทินการเผยแพร่ข้อมูลอย่างเป็นทางการของ UN Comtrade |
| **`getFinalDataAvailability(...)`** | Optional Key | เช็กว่าประเทศและปีเป้าหมายมีข้อมูลในฐานข้อมูลหรือไม่ ก่อนเริ่มยิงดึงจริง |

```python
# ตรวจสอบว่ามีข้อมูลอัปเดตใหม่หรือไม่
updates = comtradeapicall.getLiveUpdate(subscription_key="YOUR_KEY")
print(updates.head())
```

---

## 🛠️ 4. ตัวแปลงรหัสและฐานข้อมูลอ้างอิง (Metadata & Helpers)

### `convertCountryIso3ToCode(...)` ⭐
แปลงรหัสประเทศ ISO3 เช่น `"THA,VNM,USA"` เป็นรหัส UN M49 เช่น `"764,704,842"`:
```python
m49_codes = comtradeapicall.convertCountryIso3ToCode("THA,VNM,USA,IND")
# ได้ผลลัพธ์: '764,704,842,699'
```

### `getSUV(...)`
ดึงราคาต่อหน่วยมาตรฐานโลก (Standard Unit Values) เพื่อใช้ตรวจสอบราคาผิดปกติ (Outlier Detection):
```python
suv = comtradeapicall.getSUV(
    subscription_key="YOUR_KEY",
    period="2023", cmdCode="1006", flowCode="M"
)
```

### `listReference(...)` & `getReference(...)`
ค้นหาและดึงตาราง Master Data ของระบบ Comtrade:
```python
refs = comtradeapicall.listReference()
reporters = comtradeapicall.getReference("reporter")
```

---

## 📦 5. การดาวน์โหลดข้อมูลชุดใหญ่ (Bulk & Async - แพลนพรีเมียม)

*(หมายเหตุ: แพลน Basic Individual ไม่รองรับหมวดนี้ แต่เตรียมไว้สำหรับกรณีอัปเกรดสิทธิ์ในอนาคต)*
- **Bulk Download:** `bulkDownloadFinalFile(...)`, `bulkDownloadTarifflineFile(...)`, `bulkDownloadTradeMatrixFile(...)`
- **Asynchronous Processing:** `submitAsyncFinalDataRequest(...)`, `checkAsyncDataRequest(...)`, `downloadAsyncFinalDataRequest(...)`

