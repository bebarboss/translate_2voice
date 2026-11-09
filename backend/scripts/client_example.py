"""ตัวอย่างเรียกใช้ API จาก Python

python scripts/client_example.py clip.mp4
python scripts/client_example.py clip.mp4 --lang zh --speakers 3 --review
"""
import argparse
import sys
import time
from pathlib import Path

import requests


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--key", default="", help="API key ถ้าเซิร์ฟเวอร์ตั้งไว้")
    p.add_argument("--lang", default="", help="รหัสภาษาต้นฉบับ ว่างไว้ = ตรวจอัตโนมัติ")
    p.add_argument("--speakers", type=int, default=0)
    p.add_argument("--review", action="store_true", help="หยุดให้ตรวจบทก่อนพากย์")
    args = p.parse_args()

    s = requests.Session()
    if args.key:
        s.headers["X-API-Key"] = args.key

    data = {"review": str(args.review).lower()}
    if args.lang:
        data["source_lang"] = args.lang
    if args.speakers:
        data["num_speakers"] = str(args.speakers)

    with open(args.video, "rb") as f:
        r = s.post(f"{args.url}/jobs", files={"file": f}, data=data)
    r.raise_for_status()
    job_id = r.json()["id"]
    print("ส่งงานแล้ว:", job_id)

    while True:
        job = s.get(f"{args.url}/jobs/{job_id}").json()
        print(f"\r{job['status']:<16} {job['stage']:<16} {job['progress'] * 100:5.1f}%", end="", flush=True)
        if job["status"] == "failed":
            sys.exit(f"\nล้มเหลว: {job['error']}")
        if job["status"] == "awaiting_review":
            print("\n\nบทที่แปลได้:")
            for u in s.get(f"{args.url}/jobs/{job_id}/transcript").json():
                print(f"[{u['id']}] {u['speaker']} {u['start']:.1f}-{u['end']:.1f}s | {u['source']} → {u['thai']}")
            input("\nแก้บทผ่าน PUT /jobs/{id}/transcript ได้ แล้วกด Enter เพื่อพากย์ต่อ...")
            s.post(f"{args.url}/jobs/{job_id}/synthesize").raise_for_status()
        if job["status"] == "done":
            break
        time.sleep(3)

    out = Path(args.video).with_name(Path(args.video).stem + "_th.mp4")
    out.write_bytes(s.get(f"{args.url}/jobs/{job_id}/result").content)
    srt = out.with_suffix(".srt")
    srt.write_bytes(s.get(f"{args.url}/jobs/{job_id}/subtitles").content)
    print(f"\nเสร็จแล้ว: {out}\nซับไตเติล: {srt}")


if __name__ == "__main__":
    main()
