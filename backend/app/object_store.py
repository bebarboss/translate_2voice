"""Cloudflare R2 (S3-compatible) สำหรับไฟล์สื่องานหลังเสร็จ

ระหว่าง analyze/synthesize ยังเขียนที่ data/jobs/<id>/ เหมือนเดิม
เมื่องาน done → upload_job_media → (ถ้า R2_PURGE_LOCAL) ลบสื่อ local
ดาวน์โหลดผ่าน API: ensure_local ดึงจาก R2 ถ้าไฟล์หาย
"""
from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path
from typing import Iterable, Optional

from .config import settings

log = logging.getLogger("pakdee.r2")

MANIFEST_NAME = "r2_manifest.json"

# ชื่อไฟล์สื่อที่รากโฟลเดอร์งาน (นามสกุลหรือชื่อเต็ม)
_ROOT_MEDIA_NAMES = frozenset({
    "audio.wav", "vocals.wav", "bgm.wav", "dub_voice.wav", "final_audio.wav",
    "thumb.jpg", "export.zip", "export_subs.zip",
})
_MEDIA_DIRS = ("stems", "tts")  # stems/*.wav, tts/*.wav


def enabled() -> bool:
    return bool(
        settings.r2_enabled
        and settings.r2_bucket
        and settings.r2_access_key_id
        and settings.r2_secret_access_key
        and (settings.r2_endpoint or settings.r2_account_id)
    )


def _endpoint() -> str:
    if settings.r2_endpoint:
        return settings.r2_endpoint.rstrip("/")
    return f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"


def _client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=_endpoint(),
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def object_key(job_id: str, rel: str, *, free_tier: bool = False) -> str:
    """คีย์ R2 — โหมดฟรีใช้ prefix free/ เพื่อตั้งกฎ lifecycle ลบอัตโนมัติที่ 7 วัน"""
    rel = rel.replace("\\", "/").lstrip("/")
    prefix = "free/jobs" if free_tier else "jobs"
    return f"{prefix}/{job_id}/{rel}"


def job_id_from_dir(job_dir: Path) -> str:
    return job_dir.name


def manifest_path(job_dir: Path) -> Path:
    return job_dir / MANIFEST_NAME


def load_manifest(job_dir: Path) -> dict:
    p = manifest_path(job_dir)
    if not p.exists():
        return {"files": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"files": {}}
    if not isinstance(data, dict):
        return {"files": {}}
    files = data.get("files")
    if not isinstance(files, dict):
        data["files"] = {}
    return data


def save_manifest(job_dir: Path, data: dict) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path(job_dir).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(manifest_path(job_dir))


_VIDEO_AUDIO_EXT = frozenset({
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wav", ".mp3", ".m4a",
})


def is_media_rel(rel: str) -> bool:
    """relative path ภายใต้โฟลเดอร์งานที่เป็นไฟล์สื่อที่ต้องอัป R2"""
    rel = rel.replace("\\", "/")
    parts = rel.split("/")
    if len(parts) == 1:
        name = parts[0]
        if name in _ROOT_MEDIA_NAMES:
            return True
        if name.startswith("export") and name.endswith(".zip"):
            return True
        if name.startswith("input.") and Path(name).suffix.lower() in _VIDEO_AUDIO_EXT:
            return True
        if name.startswith("output") and Path(name).suffix.lower() in _VIDEO_AUDIO_EXT:
            return True
        return False
    if len(parts) == 2 and parts[0] in _MEDIA_DIRS and Path(parts[1]).suffix.lower() == ".wav":
        return True
    return False


def iter_media_files(job_dir: Path) -> list[Path]:
    if not job_dir.is_dir():
        return []
    out: list[Path] = []
    for p in job_dir.iterdir():
        if p.is_file() and is_media_rel(p.name):
            out.append(p)
    for sub in _MEDIA_DIRS:
        d = job_dir / sub
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_file() and p.suffix.lower() == ".wav":
                out.append(p)
    return sorted(out)


def _content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def upload_file(job_id: str, local: Path, job_dir: Path, *, free_tier: bool = False) -> str:
    rel = local.relative_to(job_dir).as_posix()
    key = object_key(job_id, rel, free_tier=free_tier)
    client = _client()
    extra = {"ContentType": _content_type(local)}
    client.upload_file(str(local), settings.r2_bucket, key, ExtraArgs=extra)
    return key


def upload_job_media(job_dir: Path, *, purge: Optional[bool] = None, free_tier: bool = False) -> list[str]:
    """อัปไฟล์สื่อที่ยังไม่อยู่ใน manifest คืนรายการคีย์ที่อัป (รวมของเดิมใน manifest)
    free_tier=True → คีย์ใต้ free/jobs/… (ตั้งกฎ lifecycle R2 ลบ prefix นี้หลัง 7 วัน)"""
    if not enabled():
        return []
    job_id = job_id_from_dir(job_dir)
    man = load_manifest(job_dir)
    files: dict = man.setdefault("files", {})
    man["free_tier"] = bool(free_tier)
    uploaded: list[str] = []
    for local in iter_media_files(job_dir):
        rel = local.relative_to(job_dir).as_posix()
        key = object_key(job_id, rel, free_tier=free_tier)
        prev = files.get(rel) or {}
        size = local.stat().st_size
        mtime = local.stat().st_mtime
        if prev.get("key") == key and prev.get("size") == size and abs(float(prev.get("mtime", 0)) - mtime) < 0.5:
            uploaded.append(key)
            continue
        try:
            upload_file(job_id, local, job_dir, free_tier=free_tier)
            files[rel] = {"key": key, "size": size, "mtime": mtime}
            uploaded.append(key)
            log.info("r2 uploaded %s (%d bytes)", key, size)
        except Exception:  # noqa: BLE001
            log.exception("r2 upload failed %s", key)
            raise
    man["files"] = files
    save_manifest(job_dir, man)
    do_purge = settings.r2_purge_local if purge is None else purge
    if do_purge:
        purge_local_media(job_dir, only_uploaded=True)
    return uploaded


def purge_local_media(job_dir: Path, *, only_uploaded: bool = True) -> int:
    """ลบไฟล์สื่อ local ที่อัปแล้ว (ไม่ลบ JSON/SRT/manifest)"""
    man = load_manifest(job_dir)
    files = man.get("files") or {}
    n = 0
    for local in iter_media_files(job_dir):
        rel = local.relative_to(job_dir).as_posix()
        if only_uploaded and rel not in files:
            continue
        try:
            local.unlink(missing_ok=True)
            n += 1
        except OSError:
            log.warning("r2 purge could not delete %s", local)
    # ลบโฟลเดอร์ว่างใน stems/tts
    for sub in _MEDIA_DIRS:
        d = job_dir / sub
        if d.is_dir() and not any(d.iterdir()):
            try:
                d.rmdir()
            except OSError:
                pass
    return n


def download_to(job_dir: Path, rel: str, dest: Optional[Path] = None) -> Path:
    """ดาวน์โหลดอ็อบเจ็กต์ตาม relative path ลง dest (ค่าเริ่ม = job_dir/rel)"""
    if not enabled():
        raise RuntimeError("R2 ยังไม่เปิด")
    job_id = job_id_from_dir(job_dir)
    man = load_manifest(job_dir)
    entry = (man.get("files") or {}).get(rel.replace("\\", "/"))
    key = (entry or {}).get("key") or object_key(job_id, rel)
    dest = dest or (job_dir / rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".r2part")
    _client().download_file(settings.r2_bucket, key, str(tmp))
    tmp.replace(dest)
    return dest


def ensure_local(job_dir: Path, path: Path) -> Path:
    """มีไฟล์ local ใช้เลย; ไม่มีแต่มีใน R2 manifest → ดาวน์โหลดกลับ"""
    path = path.resolve()
    if path.exists() and path.stat().st_size > 0:
        return path
    if not enabled():
        return path
    try:
        rel = path.relative_to(job_dir.resolve()).as_posix()
    except ValueError:
        return path
    man = load_manifest(job_dir)
    if rel not in (man.get("files") or {}):
        # ลองเดาคีย์มาตรฐานแม้ manifest ไม่ครบ
        if not is_media_rel(rel):
            return path
    try:
        return download_to(job_dir, rel, path)
    except Exception:  # noqa: BLE001
        log.exception("r2 download failed for %s", path)
        return path


def hydrate_job(job_dir: Path, rels: Optional[Iterable[str]] = None) -> list[str]:
    """ดึงไฟล์ที่จำเป็นกลับจาก R2 คืนรายการ relative ที่โหลดได้"""
    if not enabled() or not job_dir.is_dir():
        return []
    man = load_manifest(job_dir)
    files = man.get("files") or {}
    want = list(rels) if rels is not None else list(files.keys())
    got: list[str] = []
    for rel in want:
        rel = rel.replace("\\", "/")
        dest = job_dir / rel
        if dest.exists() and dest.stat().st_size > 0:
            continue
        if rel not in files and not is_media_rel(rel):
            continue
        try:
            download_to(job_dir, rel, dest)
            got.append(rel)
        except Exception:  # noqa: BLE001
            log.exception("r2 hydrate failed %s/%s", job_dir.name, rel)
    return got


def delete_prefix(job_id: str) -> int:
    """ลบทุกอ็อบเจ็กต์ภายใต้ jobs/{job_id}/ และ free/jobs/{job_id}/ คืนจำนวนที่ลบ"""
    if not enabled():
        return 0
    client = _client()
    n = 0
    for prefix in (f"jobs/{job_id}/", f"free/jobs/{job_id}/"):
        token = None
        while True:
            kw = {"Bucket": settings.r2_bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = client.list_objects_v2(**kw)
            objs = [{"Key": o["Key"]} for o in resp.get("Contents") or []]
            if objs:
                client.delete_objects(Bucket=settings.r2_bucket, Delete={"Objects": objs, "Quiet": True})
                n += len(objs)
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
    if n:
        log.info("r2 deleted %d objects for job %s", n, job_id)
    return n


def archive_after_done(job_dir: Path, *, free_tier: bool = False) -> None:
    """เรียกหลังงาน status=done — อัป R2 (และ purge ตามตั้งค่า) ไม่โยน error ให้งานล้ม
    free_tier → เก็บใต้ free/jobs/ สำหรับกฎ lifecycle ลบอัตโนมัติหลัง FREE_RETENTION_DAYS"""
    if not enabled():
        return
    try:
        keys = upload_job_media(job_dir, free_tier=free_tier)
        log.info("r2 archive job %s: %d objects (free=%s)", job_dir.name, len(keys), free_tier)
    except Exception:  # noqa: BLE001
        log.exception("r2 archive failed for job %s", job_dir.name)
