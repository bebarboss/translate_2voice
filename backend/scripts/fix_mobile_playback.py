"""แปลงวิดีโอของงานเก่าที่เป็น VP9/AV1 ให้เป็น H.264 เพื่อให้เล่นบนมือถือได้

    python scripts/fix_mobile_playback.py [โฟลเดอร์ data/jobs]

ข้ามงานที่กำลังรันหรือรอคิว แปลงทับไฟล์เดิม (input.mp4, output.mp4, output_subs.mp4)
"""
import json
import subprocess
import sys
from pathlib import Path

NAMES = ["input.mp4", "output.mp4", "output_subs.mp4"]
BUSY = {"queued", "running"}


def probe(path: Path) -> list[str]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=codec_name,pix_fmt", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout
    return out.strip().split("\n")[0].split(",")[:2]


def convert(path: Path) -> None:
    tmp = path.with_suffix(".h264.tmp.mp4")
    proc = subprocess.run(["ffmpeg", "-y", "-i", str(path), "-map", "0:v:0", "-map", "0:a?",
                           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                           "-c:a", "copy", "-movflags", "+faststart", str(tmp)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(proc.stderr[-800:])
    tmp.replace(path)


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "data" / "jobs")
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        meta = d / "job.json"
        status = json.loads(meta.read_text(encoding="utf-8")).get("status") if meta.exists() else None
        if status in BUSY:
            print(f"{d.name}: ข้าม (สถานะ {status})")
            continue
        for name in NAMES:
            f = d / name
            if not f.exists():
                continue
            codec = probe(f)
            if codec == ["h264", "yuv420p"]:
                continue
            print(f"{d.name}/{name}: {','.join(codec)} -> h264 ...", flush=True)
            try:
                convert(f)
            except RuntimeError as exc:
                print(f"  ไม่สำเร็จ: {exc}")


if __name__ == "__main__":
    main()
