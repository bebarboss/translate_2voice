import sys

# Windows ใช้ cp1252 กับหน้าจอ console เป็นค่าเริ่มต้น พอไลบรารี (เช่น f5-tts-th) print ข้อความไทยจะล้มทั้งงาน
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
