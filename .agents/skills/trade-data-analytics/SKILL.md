---
name: trade-data-analytics
description: >-
  Advanced trade data analytics playbooks and statistical methods for UN Comtrade datasets.
  Use when analyzing rice or commodity trade data, calculating unit values ($/kg),
  detecting price outliers, analyzing market share, or diagnosing bilateral mirror discrepancies (CIF vs FOB).
---

# International Trade Analytics Playbook & Skill

คู่มือและระเบียบวิธีทางสถิติสำหรับการวิเคราะห์ข้อมูลการค้าระหว่างประเทศตามมาตรฐาน UN Comtrade

---

## 📈 1. การวิเคราะห์ราคาต่อหน่วยและการตัดค่าผิดปกติ (Unit Value & Outlier Removal)

### สูตรคำนวณราคาเฉลี่ยต่อหน่วย (Unit Value):
$$\text{Unit Value (USD/kg)} = \frac{\text{primaryValue}}{\text{netWgt}}$$
*(หรือแปลงเป็นราคาต่อตัน: $\text{Unit Value (USD/ton)} = \text{Unit Value (USD/kg)} \times 1,000$)*

### ทำไมต้องตัด Outliers ในข้อมูลการค้า?
ข้อมูลศุลกากรโลกมักมีข้อผิดพลาดจากการกรอกน้ำหนักผิด (เช่น ใส่หน่วยกรัมแทนกิโลกรัม) ทำให้ราคาเบี่ยงเบนจากความเป็นจริงหลายเท่า
- ราคาการค้าสากลจะมีการกระจายตัวแบบ **Log-normal Distribution** (เบ้ขวามาก)
- **ขั้นตอนการคลีนข้อมูล (Best Practice):**
  1. กรองเฉพาะแถวที่มี `primaryValue > 0` และ `netWgt > 0`
  2. คำนวณ `log_uv = np.log(df['primaryValue'] / df['netWgt'])`
  3. คำนวณเกณฑ์ IQR:
     $$\text{Q1} = 25\text{th percentile}, \quad \text{Q3} = 75\text{th percentile}, \quad \text{IQR} = \text{Q3} - \text{Q1}$$
     $$\text{Lower Bound} = \text{Q1} - 1.5 \times \text{IQR}, \quad \text{Upper Bound} = \text{Q3} + 1.5 \times \text{IQR}$$
  4. กรองเอาเฉพาะข้อมูลที่อยู่ในช่วงขอบเขต
  5. ใช้ค่า **Median** แทน Mean เมื่อต้องการสรุปแนวโน้มราคารายเดือน

```python
import pandas as pd
import numpy as np

def clean_unit_values(df: pd.DataFrame) -> pd.DataFrame:
    valid = df[(df['primaryValue'] > 0) & (df['netWgt'] > 0)].copy()
    valid['uv'] = valid['primaryValue'] / valid['netWgt']
    log_uv = np.log(valid['uv'])
    q1 = log_uv.quantile(0.25)
    q3 = log_uv.quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return valid[(log_uv >= lower) & (log_uv <= upper)]
```

---

## 🪞 2. การวิเคราะห์ข้อมูลกระจกสะท้อน (Bilateral Mirror: CIF vs FOB)

### หลักการ:
- **ผู้ส่งออก (Exporter):** รายงานมูลค่าแบบ **FOB (Free on Board)** คือราคาสินค้าหน้าท่าเรือต้นทาง
- **ผู้นำเข้า (Importer):** รายงานมูลค่าแบบ **CIF (Cost, Insurance, Freight)** คือราคาสินค้าที่บวกค่าขนส่งและประกันภัยแล้ว

### การวินิจฉัยความคลาดเคลื่อน (Discrepancy Diagnosis):
$$\text{Margin} = \frac{\text{ImportValue (CIF)} - \text{ExportValue (FOB)}}{\text{ExportValue (FOB)}}$$
- **ปกติ (Normal Range):** ส่วนต่างควรอยู่ที่ **+5% ถึง +15%** (ค่าระวางเรือและประกันภัย)
- **ผิดปกติกรณี 1 (Margin สูงเกิน 30%):** อาจเกิดจากเส้นทางขนส่งที่ซับซ้อน หรือความล่าช้าในการบันทึกข้อมูลคนละช่วงเวลา (Time Lag)
- **ผิดปกติกรณี 2 (Margin ติดลบ คือฝั่งนำเข้ารายงานยอดต่ำกว่าส่งออก):** มีความเสี่ยงเรื่องการสำแดงราคาต่ำเพื่อเลี่ยงภาษีนำเข้า (Under-invoicing) หรือการลักลอบนำเข้า (Smuggling)

---

## 🌐 3. การคำนวณส่วนแบ่งตลาดและการแข่งขัน (Market Share Benchmarking)

สำหรับการเปรียบเทียบขีดความสามารถในการแข่งขันของประเทศ (เช่น ข้าวไทย vs ข้าวเวียดนาม vs ข้าวอินเดีย):

```python
# อ่านข้อมูลจากไฟล์ Excel ใน output/by_country/
import pandas as pd
from pathlib import Path

def compare_rice_exporters(country_files: list, year: int) -> pd.DataFrame:
    rows = []
    for filepath in country_files:
        c_name = Path(filepath).stem
        with pd.ExcelFile(filepath) as xls:
            df = pd.read_excel(xls, "Export")
            # กรองเฉพาะ World หรือยอดรวม
            df_year = df[(df['period'].astype(str).str.startswith(str(year))) & (df['partnerDesc'] == 'World')]
            tot_val = df_year['primaryValue'].sum()
            tot_wgt = df_year['netWgt'].sum()
            avg_price = tot_val / tot_wgt if tot_wgt > 0 else 0
            rows.append({"Country": c_name, "Export_USD": tot_val, "Export_kg": tot_wgt, "Avg_Price_USD_per_kg": avg_price})
    return pd.DataFrame(rows).sort_values("Export_USD", ascending=False)
```

---

## 💡 4. กฎการใช้งานตารางข้อมูล (Data Table Rules)
1. **ป้องกัน Double Counting:** เมื่อต้องการดูยอดรวมระดับประเทศ ให้กรองเฉพาะ `partnerDesc == 'World'` เสมอ หากต้องการดูคู่ค้ารายประเทศ ให้กรอง `partnerDesc != 'World'`
2. **เลือกระดับรหัส HS ให้เหมาะสม:**
   - รหัส `1006` = ยอดรวมทั้งหมวดข้าว
   - รหัส 6 หลัก (`100610`, `100620`, `100630`, `100640`) = จำแนกชนิดข้าว
   - อย่ารวมยอดรหัส 4 หลักกับ 6 หลักเข้าด้วยกัน เพราะจะเกิดยอดเบิ้ล 2 เท่า

