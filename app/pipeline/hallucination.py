"""ตัดประโยคที่ Whisper แต่งขึ้นเองตอนมีแต่เพลงหรือเสียงประกอบ (ไม่มีคนพูดจริง)

Whisper เรียนจากคลิปที่มีซับท้ายคลิป จึงมักพิมพ์ประโยคปิดท้ายคลิปออกมาเอง เช่น "ご視聴ありがとうございました"
การ์ตูนญี่ปุ่นยังได้เศษ ED / สระยืด / SFX สั้น ๆ ที่ไม่ควรแปลหรือพากย์
ถ้าไม่ตัดทิ้ง ระบบจะแปลแล้วพากย์ประโยคที่ไม่มีใครพูด ตัดเฉพาะวลีนั้น ส่วนที่เหลือของท่อน (ถ้ามี) ยังเก็บไว้
"""
from __future__ import annotations

import logging
import re
import unicodedata

from ..schemas import Utterance

log = logging.getLogger("dubbing.hallucination")

PHRASES = [
    # ญี่ปุ่น (มี/ไม่มี ご)
    r"ご?視聴ありがとうございました", r"ご?視聴ありがとうございます",
    r"チャンネル登録(を)?お願いします",
    r"最後までご視聴いただきありがとうございました",
    r"エンディング", r"オープニング", r"次回予告",
    # จีน
    r"请不吝点赞\s*订阅\s*转发\s*打赏支持明镜与点点栏目", r"字幕由\S{0,20}提供", r"字幕(志愿者|组)\S{0,20}",
    r"感谢(您的)?(观看|收看)", r"谢谢(大家|各位)?(观看|收看)", r"请(点赞|订阅)\S{0,10}",
    # เกาหล이
    r"시청(해\s*주셔서|해주셔서)\s*감사합니다", r"구독과\s*좋아요\s*부탁드립니다",
    # อังกฤษ
    r"thanks?\s+(you\s+)?for\s+watching[.!]?", r"please\s+subscribe[^.!?]*[.!?]?",
    r"subtitles?\s+by\s+\S+", r"amara\.org\S*",
    r"ending[.!]?", r"opening[.!]?",
    # ไทย
    r"ขอบคุณที่รับชม(ครับ|ค่ะ)?", r"(อย่าลืม)?กด(ติดตาม|subscribe)\S{0,20}",
    r"ขอบคุณมาก(มาก)+",
]
_PATTERN = re.compile("|".join(f"(?:{p})" for p in PHRASES), re.IGNORECASE)
# สระ/ตัวอักษรซ้ำยาวเกินจริง (เพลง ED, ตะโกน) — เหลือตัวเดียว
_ELONGATE = re.compile(
    r"([ぁ-んァ-ンー])\1{2,}"  # คานะตัวเดียวกัน ≥3
    r"|ー{2,}"
    r"|([ๆาา])\2{2,}"  # ไทยซ้ำ
    r"|([a-zA-Z])\1{3,}"
    r"|([一-龥])\1{2,}"
)
_LEFTOVER = re.compile(r"^[\s、。,.!?！？…・「」『』\-—/·]*$")
# ท่อนสั้นมาก + เนื้อหาน้อย → มักเป็น SFX / เศษ ASR
MIN_KEEP_SEC = 0.5
MIN_LETTERS = 2

# เสียงพากย์ล้มแล้ว Whisper ถอดเป็นประโยคทักทายตายตัว (ไม่เกี่ยวกับบท)
DEAD_HEARD = re.compile(
    r"^(สวัสดี(ครับ|ค่ะ)?\s*ทุกคน|hello\s*everyone|hi\s*everyone|ทุกคน(ครับ|ค่ะ)?)$",
    re.IGNORECASE,
)


def _letters(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    return "".join(ch for ch in text if unicodedata.category(ch)[0] in "LMN")


def scrub_source(text: str) -> str:
    """ตัดวลีปิดคลิปและสระยืดออกจากต้นฉบับ"""
    text = _PATTERN.sub("", text or "")
    # แทนที่กลุ่มซ้ำด้วยตัวอักษรตัวแรกของกลุ่ม (คงความหมายสั้น ๆ ไว้)
    def _one(m: re.Match) -> str:
        g = m.group(0)
        return g[0] if g else ""

    text = _ELONGATE.sub(_one, text)
    return re.sub(r"\s{2,}", " ", text).strip()


def is_noise_line(source: str, duration: float) -> bool:
    """ท่อนที่ไม่น่ามีคนพูดจริง — SFX / เศษ / ว่างหลัง scrub"""
    cleaned = scrub_source(source)
    if _LEFTOVER.match(cleaned) or not cleaned:
        return True
    letters = _letters(cleaned)
    if len(letters) < MIN_LETTERS:
        return True
    # ท่อนสั้นมาก + ตัวอักษรน้อย (เช่น ンディング ちゅー)
    if duration < MIN_KEEP_SEC and len(letters) < 6:
        return True
    # เศษคานะล้วนสั้น ๆ (ンユセ) ไม่มีคันจิ/คำยาว — มักเป็นชื่อเรียกเพี้ยนจากเพลง
    kana_only = bool(re.fullmatch(r"[ぁ-んァ-ンーゝゞ]+", cleaned))
    if kana_only and len(letters) <= 4 and duration < 1.5:
        return True
    # มีแต่เครื่องหมาย / คานะเศษสั้น ๆ ไม่มีคำจริงพอ
    if duration < 1.0 and len(letters) <= 3 and not re.search(r"[一-龥ぁ-んァ-ン]{2,}", cleaned):
        if not re.search(r"[\u0E00-\u0E7Fa-zA-Z]{4,}", cleaned):
            return True
    return False


def dead_heard_score(expected: str, got: str) -> float | None:
    """ถ้าเสียงพากย์ถอดเป็นประโยคทักทายตายตัวที่ไม่ใช่บท → คืน 0.0; ไม่เข้าเงื่อนไขคืน None"""
    g = re.sub(r"\s+", "", (got or "").strip())
    e = re.sub(r"\s+", "", (expected or "").strip())
    if not g or not DEAD_HEARD.match(g):
        return None
    # บทตั้งใจทักทายจริง → ไม่บังคับตก
    if DEAD_HEARD.match(e) or "สวัสดี" in e or "hello" in e.lower():
        return None
    return 0.0


def clean(utts: list[Utterance]) -> list[Utterance]:
    """คืนรายการท่อนที่ตัดวลีที่แต่งเอง / เศษ SFX ออกแล้ว ท่อนที่เหลือแต่ขยะถูกตัดทิ้งทั้งท่อน"""
    out: list[Utterance] = []
    for u in utts:
        raw = u.source or ""
        text = scrub_source(raw)
        dur = float(u.duration)
        if text != raw.strip():
            if is_noise_line(text, dur) or _LEFTOVER.match(text) or not text:
                log.info("drop hallucinated line %d: %s", u.id, raw)
                continue
            log.info("strip hallucinated phrase from line %d: %s -> %s", u.id, raw, text)
            u.source = text
            # เป้าหมายที่แปลจากขยะ (ขอบคุณมากมาก / เอนดิ้ง) ให้ว่างเพื่อแปลใหม่
            if u.target and (_PATTERN.search(u.target) or is_noise_line(u.target, dur)):
                u.target = ""
            out.append(u)
            continue
        if is_noise_line(raw, dur):
            log.info("drop noise/SFX line %d (%.2fs): %s", u.id, dur, raw)
            continue
        out.append(u)

    # รวมท่อนสั้นมากเข้าท่อนก่อนหน้าคนเดียวกัน (เศษ ASR ที่หลุดมา)
    merged: list[Utterance] = []
    for u in out:
        if (
            merged
            and u.duration < MIN_KEEP_SEC
            and len(_letters(u.source)) < 6
            and merged[-1].speaker == u.speaker
            and u.start - merged[-1].end < 1.0
        ):
            prev = merged[-1]
            gap = " " if prev.source and u.source and not prev.source.endswith((" ", "/")) else ""
            prev.source = f"{prev.source}{gap}{u.source}".strip()
            if u.target:
                tgap = " " if prev.target and not prev.target.endswith((" ", "/")) else ""
                prev.target = f"{prev.target}{tgap}{u.target}".strip()
            prev.end = max(prev.end, u.end)
            log.info("merge short line %d into %d", u.id, prev.id)
            continue
        merged.append(u)

    # เรียง id ใหม่ต่อเนื่องถ้าตัดไปเยอะ (คง id เดิมไว้ถ้าไม่ชน — runner อ้าง id)
    return merged
