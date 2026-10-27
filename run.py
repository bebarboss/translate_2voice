"""เปิดเซิร์ฟเวอร์: python run.py  (เอกสาร API อยู่ที่ http://localhost:8000/docs)"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        workers=1,  # ต้องเป็น 1 เพราะคิวงานและโมเดลอยู่ในโปรเซสเดียว
    )
