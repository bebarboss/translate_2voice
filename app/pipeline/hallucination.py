"""ตัดประโยคที่ Whisper แต่งขึ้นเองตอนมีแต่เพลงหรือเสียงประกอบ (ไม่มีคนพูดจริง)

Whisper เรียนจากคลิปที่มีซับท้ายคลิป จึงมักพิมพ์ประโยคปิดท้ายคลิปออกมาเอง เช่น "ご視聴ありがとうございました"
ถ้าไม่ตัดทิ้ง ระบบจะแปลแล้วพากย์ประโยคที่ไม่มีใครพูด ตัดเฉพาะวลีนั้น ส่วนที่เหลือของท่อน (ถ้ามี) ยังเก็บไว้
"""
import logging
import re

from ..schemas import Utterance

log = logging.getLogger("dubbing.hallucination")

PHRASES = [
    # ญี่ปุ่น
    r"ご視聴ありがとうございました", r"ご視聴ありがとうございます", r"チャンネル登録(を)?お願いします",
    r"最後までご視聴いただきありがとうございました",
    # จีน
    r"请不吝点赞\s*订阅\s*转发\s*打赏支持明镜与点点栏目", r"字幕由\S{0,20}提供", r"字幕(志愿者|组)\S{0,20}",
    r"感谢(您的)?(观看|收看)", r"谢谢(大家|各位)?(观看|收看)", r"请(点赞|订阅)\S{0,10}",
    # เกาหลี
    r"시청(해\s*주셔서|해주셔서)\s*감사합니다", r"구독과\s*좋아요\s*부탁드립니다",
    # อังกฤษ
    r"thanks?\s+(you\s+)?for\s+watching[.!]?", r"please\s+subscribe[^.!?]*[.!?]?",
    r"subtitles?\s+by\s+\S+", r"amara\.org\S*",
    # ไทย
    r"ขอบคุณที่รับชม(ครับ|ค่ะ)?", r"(อย่าลืม)?กด(ติดตาม|subscribe)\S{0,20}",
]
_PATTERN = re.compile("|".join(f"(?:{p})" for p in PHRASES), re.IGNORECASE)
_LEFTOVER = re.compile(r"^[\s、。,.!?！？…・「」『』\-—]*$")


def clean(utts: list[Utterance]) -> list[Utterance]:
    """คืนรายการท่อนที่ตัดวลีที่แต่งเองออกแล้ว ท่อนที่เหลือแต่วลีนั้นถูกตัดทิ้งทั้งท่อน"""
    out = []
    for u in utts:
        text = _PATTERN.sub("", u.source)
        if text == u.source:
            out.append(u)
            continue
        if _LEFTOVER.match(text):
            log.info("drop hallucinated line %d: %s", u.id, u.source)
            continue
        log.info("strip hallucinated phrase from line %d: %s -> %s", u.id, u.source, text.strip())
        u.source = text.strip()
        out.append(u)
    return out
