"""ดาวน์โหลดคลิปจากลิงก์ (YouTube, TikTok, Facebook, Bilibili ฯลฯ) ด้วย yt-dlp

แพลตฟอร์มเหล่านี้เปลี่ยนระบบบ่อย ถ้าโหลดไม่ได้ให้อัปเดตก่อน: pip install -U yt-dlp
"""
from pathlib import Path
from typing import Callable

from ..config import settings


class _Stop(Exception):
    pass


def fetch_info(url: str) -> dict:
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True, "skip_download": True}) as ydl:
        return ydl.extract_info(url, download=False)


def download(url: str, out_dir: Path, check_cancel: Callable[[], None],
             on_progress: Callable[[float], None]) -> tuple[Path, str, float]:
    """คืนค่า (ไฟล์วิดีโอ, ชื่อคลิป, ความยาววินาที)"""
    import yt_dlp

    info = fetch_info(url)
    if info.get("_type") == "playlist":
        raise RuntimeError("ลิงก์นี้เป็นเพลย์ลิสต์ กรุณาใส่ลิงก์คลิปเดียว")
    duration = float(info.get("duration") or 0)
    if duration and duration > settings.max_url_minutes * 60:
        raise RuntimeError(f"คลิปยาว {duration / 60:.0f} นาที เกินที่ตั้งไว้ {settings.max_url_minutes:.0f} นาที")

    cancelled = {"flag": False}

    def hook(d: dict) -> None:
        try:
            check_cancel()
        except Exception:
            cancelled["flag"] = True
            raise _Stop()
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                on_progress(min(1.0, d.get("downloaded_bytes", 0) / total))

    opts = {
        "quiet": True,
        "noplaylist": True,
        "format": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "input.%(ext)s"),
        "progress_hooks": [hook],
        "retries": 3,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as exc:  # noqa: BLE001
        if cancelled["flag"]:
            check_cancel()  # โยน Cancelled ออกไป
        raise RuntimeError(f"ดาวน์โหลดคลิปไม่สำเร็จ: {str(exc)[:300]}") from exc

    files = [p for p in out_dir.glob("input.*") if p.suffix not in (".part", ".ytdl", ".json")]
    if not files:
        raise RuntimeError("ดาวน์โหลดเสร็จแต่ไม่พบไฟล์วิดีโอ")
    title = str(info.get("title") or "clip").strip()
    return max(files, key=lambda p: p.stat().st_size), title, duration
