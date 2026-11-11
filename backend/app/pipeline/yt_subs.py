"""ดึงซับไตเติลจาก YouTube ด้วย yt-dlp

ใช้ซับที่คนทำไว้ก่อน ถ้าไม่มีค่อยใช้ซับอัตโนมัติของ YouTube
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger("dubbing.yt_subs")

# ภาษาที่สนใจเรียงตามความสำคัญ (ต้นฉบับที่พบบ่อยในงานพากย์ไทย)
LANG_PREF = ("th", "en", "zh-Hans", "zh-Hant", "zh", "ja", "ko", "id", "vi")


def _pick_lang(available: dict, prefer: Optional[str] = None) -> Optional[str]:
    if prefer and prefer in available:
        return prefer
    for code in LANG_PREF:
        if code in available:
            return code
    return next(iter(available), None)


def fetch(url: str, out_dir: Path, prefer_lang: Optional[str] = None) -> Optional[Path]:
    """ดาวน์โหลดซับ YouTube ไปที่ out_dir คืน path ไฟล์ .vtt/.srt หรือ None

    ลองซับมือก่อน (writesubtitles) แล้วค่อยอัตโนมัติ (writeautomaticsub)
    """
    import yt_dlp

    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / "yt_subs"
    # ลบของเก่า
    for p in out_dir.glob("yt_subs*"):
        p.unlink(missing_ok=True)

    info = None
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("yt-dlp info for subs failed: %s", exc)
        return None

    subs = info.get("subtitles") or {}
    autos = info.get("automatic_captions") or {}
    manual = bool(subs)
    pool = subs if manual else autos
    if not pool:
        log.info("no youtube captions for %s", url[:80])
        return None
    lang = _pick_lang(pool, prefer_lang)
    if not lang:
        return None

    opts = {
        "quiet": True,
        "noplaylist": True,
        "skip_download": True,
        "writesubtitles": manual,
        "writeautomaticsub": not manual,
        "subtitleslangs": [lang],
        "subtitlesformat": "vtt",
        "outtmpl": str(base),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as exc:  # noqa: BLE001
        log.warning("youtube subtitle download failed: %s", exc)
        return None

    found = sorted(out_dir.glob("yt_subs*"), key=lambda p: p.stat().st_mtime, reverse=True)
    found = [p for p in found if p.suffix.lower() in (".vtt", ".srt", ".ttml", ".srv3", ".json3")]
    if not found:
        return None
    path = found[0]
    meta = {"lang": lang, "manual": manual, "path": path.name}
    (out_dir / "yt_subs.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    log.info("youtube subs: lang=%s manual=%s file=%s", lang, manual, path.name)
    return path


_TIME = re.compile(
    r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})"
)
_TAG = re.compile(r"<[^>]+>")
_CUE = re.compile(r"^\d+$|NOTE |STYLE|REGION|WEBVTT", re.I)


def _sec(h: Optional[str], m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_cues(path: Path) -> list[dict]:
    """อ่าน .vtt / .srt → [{start, end, text}, ...]"""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        m = _TIME.search(line)
        if not m:
            continue
        start = _sec(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _sec(m.group(5), m.group(6), m.group(7), m.group(8))
        body: list[str] = []
        while i < len(lines) and lines[i].strip():
            raw = lines[i].strip()
            i += 1
            if _CUE.match(raw):
                continue
            cleaned = _TAG.sub("", raw).strip()
            if cleaned:
                body.append(cleaned)
        i += 1  # blank
        if body and end > start:
            out.append({"start": round(start, 3), "end": round(end, 3), "text": " ".join(body)})
    return out


def apply_to_utterances(utterances: list, cues: list[dict], min_overlap: float = 0.45) -> int:
    """ทับ source ด้วยซับ YouTube เมื่อช่วงเวลาทับกันพอ คืนจำนวนบรรทัดที่แทนที่

    คงเวลา/ผู้พูดจาก diarization+ASR ไว้ ใช้แค่ข้อความจากซับ (คนทำไว้หรืออัตโนมัติ)
    """
    if not cues or not utterances:
        return 0
    n = 0
    for u in utterances:
        best, best_ov = None, 0.0
        for c in cues:
            ov = max(0.0, min(u.end, c["end"]) - max(u.start, c["start"]))
            frac = ov / max(u.duration, 1e-6)
            if frac > best_ov:
                best, best_ov = c, frac
        if best is None or best_ov < min_overlap:
            continue
        text = (best.get("text") or "").strip()
        if not text:
            continue
        if text != (u.source or "").strip():
            u.source = text
            n += 1
            # ซับคนทำ = มั่นใจขึ้น; เคลียร์ธงถอดไม่ชัดถ้ามี
            if getattr(u, "unclear", False) and best_ov >= 0.7:
                u.unclear = False
                u.unclear_reason = ""
    return n
