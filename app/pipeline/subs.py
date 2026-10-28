"""ซับไตเติล: เขียน .srt / .ass ฝังซับลงวิดีโอ และหารายชื่อฟอนต์ในเครื่อง"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from ..config import settings
from ..schemas import SubtitleStyle, Utterance
from .audio import run

THAI_CHAR = 0x0E01  # ก


def _ts_srt(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ts_ass(sec: float) -> str:
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_srt(utts: list[Utterance], out_srt: Path) -> Path:
    lines = []
    for i, u in enumerate((u for u in utts if u.target), start=1):
        lines += [str(i), f"{_ts_srt(u.start)} --> {_ts_srt(u.end)}", u.target, ""]
    out_srt.write_text("\n".join(lines), encoding="utf-8")
    return out_srt


def _ass_color(hex_rgb: str) -> str:
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"&H00{b}{g}{r}".upper()


def style_key(style: SubtitleStyle) -> str:
    return hashlib.sha1(style.model_dump_json().encode()).hexdigest()[:16]


def write_ass(utts: list[Utterance], out_ass: Path, style: SubtitleStyle,
              width: int, height: int) -> Path:
    scale = height / 1080
    size = max(10, round(style.size * scale))
    outline = max(1, round(3 * scale))
    margin_v = round(50 * scale)
    align = 8 if style.position == "top" else 2
    font = style.font.replace(",", " ")
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},{_ass_color(style.color)},&H000000FF,{_ass_color(style.outline_color)},&H64000000,0,0,0,0,100,100,0,0,1,{outline},0,{align},{round(60 * scale)},{round(60 * scale)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for u in utts:
        if not u.target:
            continue
        text = u.target.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")
        events.append(f"Dialogue: 0,{_ts_ass(u.start)},{_ts_ass(u.end)},Default,,0,0,0,,{text}")
    out_ass.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return out_ass


def video_size(video: Path) -> tuple[int, int]:
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", video])
    w, h = out.strip().split("\n")[0].split("x")[:2]
    return int(w), int(h)


def burn(video: Path, utts: list[Utterance], style: SubtitleStyle, out_mp4: Path) -> Path:
    """ฝังซับลงวิดีโอ (ต้องเข้ารหัสภาพใหม่ จึงช้ากว่าขั้นอื่น)"""
    work = out_mp4.parent
    w, h = video_size(video)
    write_ass(utts, work / "subs.ass", style, w, h)
    vf = "ass=subs.ass"
    if settings.fonts_dir and Path(settings.fonts_dir).is_dir():
        local_fonts = work / "_fonts"
        if not local_fonts.exists():
            shutil.copytree(settings.fonts_dir, local_fonts)
        vf += ":fontsdir=_fonts"
    tmp = out_mp4.with_suffix(".tmp.mp4")
    # รันในโฟลเดอร์งาน จะได้ไม่ต้อง escape path ของ Windows ในตัวกรอง ass
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(tmp)],
        capture_output=True, text=True, cwd=work)
    if proc.returncode != 0:
        raise RuntimeError(f"ฝังซับไม่สำเร็จ: {proc.stderr[-1200:]}")
    tmp.replace(out_mp4)
    (work / "subs_style.json").write_text(json.dumps({"key": style_key(style)}), encoding="utf-8")
    return out_mp4


def burned_matches(work: Path, style: SubtitleStyle) -> bool:
    meta = work / "subs_style.json"
    if not (work / "output_subs.mp4").exists() or not meta.exists():
        return False
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("key") == style_key(style)
    except ValueError:
        return False


# ---------------- รายชื่อฟอนต์ ----------------
def _font_dirs() -> list[Path]:
    dirs = []
    if settings.fonts_dir:
        dirs.append(Path(settings.fonts_dir))
    if sys.platform == "win32":
        dirs.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        dirs += [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library/Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
                 Path.home() / ".local/share/fonts"]
    return [d for d in dirs if d.is_dir()]


def _fc_list() -> dict[str, list[str]] | None:
    if not shutil.which("fc-list"):
        return None
    try:
        thai = subprocess.run(["fc-list", ":lang=th", "family"], capture_output=True, text=True, timeout=20).stdout
        latin = subprocess.run(["fc-list", ":lang=en", "family"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None

    def names(text: str) -> set[str]:
        return {line.split(",")[0].strip() for line in text.splitlines() if line.strip()}

    th = names(thai)
    return {"thai": sorted(th), "english": sorted(names(latin) - th)}


def _scan_with_fonttools() -> dict[str, list[str]]:
    try:
        from fontTools.ttLib import TTCollection, TTFont
    except ImportError:
        return {"thai": [], "english": []}
    thai, latin = set(), set()
    for d in _font_dirs():
        for path in d.rglob("*"):
            if path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            try:
                fonts = TTCollection(str(path), lazy=True).fonts if path.suffix.lower() == ".ttc" \
                    else [TTFont(str(path), lazy=True)]
            except Exception:  # noqa: BLE001  ไฟล์ฟอนต์เสีย ข้ามไป
                continue
            for f in fonts:
                try:
                    name = f["name"].getBestFamilyName()
                    cmap = f.getBestCmap() or {}
                except Exception:  # noqa: BLE001
                    continue
                if not name:
                    continue
                if THAI_CHAR in cmap:
                    thai.add(name)
                elif ord("A") in cmap:
                    latin.add(name)
    return {"thai": sorted(thai), "english": sorted(latin - thai)}


@lru_cache(maxsize=1)
def list_fonts() -> dict[str, list[str]]:
    """ฟอนต์ที่ติดตั้งในเครื่องเซิร์ฟเวอร์ แยกเป็นฟอนต์ที่มีตัวไทย กับฟอนต์อังกฤษล้วน"""
    return _fc_list() or _scan_with_fonttools()
