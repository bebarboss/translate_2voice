"""เปิดเซิร์ฟเวอร์: python run.py

เอกสาร API ที่ http://localhost:8000/docs เมื่อตั้ง API_DOCS_ENABLED=1
ค่าเริ่มต้นปิด — production ตอบ 404 ที่ /docs /redoc /openapi.json
"""
import os
import sys

import uvicorn

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    print(f"pakdee-api starting on {host}:{port}", flush=True)
    sys.stdout.flush()
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        workers=1,  # ต้องเป็น 1 เพราะคิวงานและโมเดลอยู่ในโปรเซสเดียว
    )
