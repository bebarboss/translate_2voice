"""ตอบไฟล์ให้ <video> / <audio> บนมือถือเล่นได้

iOS Safari และ Android Chrome ไม่เล่นคำตอบที่เป็นไฟล์ดาวน์โหลด
(Content-Disposition: attachment) — เดสก์ท็อปยังเล่นได้ จึงดูเหมือนเสียเฉพาะมือถือ
iOS ยังไม่เล่นเมื่อ Cache-Control เป็น no-store (แถบเวลาค้างที่ 0:00)
ทั้งคู่ต้องได้ 206 Partial Content เมื่อขอ Range — FileResponse ของ Starlette ตัดช่วงให้
"""
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse


def media_file_response(path: Path, media_type: str, filename: str, *, inline: bool) -> FileResponse:
    if not path.exists():
        raise HTTPException(404, "ยังไม่มีไฟล์นี้ งานอาจยังไม่เสร็จ")
    # private ไม่ใช่ no-store: WebKit ปฏิเสธสื่อที่ห้ามเก็บแคช
    headers = {"Cache-Control": "private"} if inline else None
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="inline" if inline else "attachment",
        headers=headers,
    )
