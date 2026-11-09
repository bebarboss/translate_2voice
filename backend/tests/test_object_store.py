"""unit tests สำหรับ R2 object_store (mock boto3 — ไม่ต่อเน็ต)"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app import object_store


@pytest.fixture()
def job_dir(tmp_path: Path) -> Path:
    d = tmp_path / "jobs" / "abc123def456"
    d.mkdir(parents=True)
    (d / "transcript.json").write_text("[]", encoding="utf-8")
    (d / "output.mp4").write_bytes(b"fake-mp4-data")
    (d / "vocals.wav").write_bytes(b"fake-wav")
    (d / "stems").mkdir()
    (d / "stems" / "speaker_01.wav").write_bytes(b"stem")
    (d / "subtitles.srt").write_text("1\n", encoding="utf-8")
    return d


def _r2_settings(**over):
    return SimpleNamespace(
        r2_bucket="test-bucket",
        r2_purge_local=False,
        **over,
    )


def test_is_media_rel():
    assert object_store.is_media_rel("output.mp4")
    assert object_store.is_media_rel("input.mov")
    assert object_store.is_media_rel("vocals.wav")
    assert object_store.is_media_rel("export.zip")
    assert object_store.is_media_rel("stems/speaker_01.wav")
    assert object_store.is_media_rel("tts/line_1.wav")
    assert not object_store.is_media_rel("transcript.json")
    assert not object_store.is_media_rel("subtitles.srt")
    assert not object_store.is_media_rel("metrics.json")
    assert not object_store.is_media_rel("ai_draft.json")


def test_iter_media_files_skips_json(job_dir: Path):
    files = object_store.iter_media_files(job_dir)
    rels = {p.relative_to(job_dir).as_posix() for p in files}
    assert "output.mp4" in rels
    assert "vocals.wav" in rels
    assert "stems/speaker_01.wav" in rels
    assert "transcript.json" not in rels
    assert "subtitles.srt" not in rels


def test_upload_job_media_writes_manifest(job_dir: Path):
    client = MagicMock()
    with patch.object(object_store, "enabled", return_value=True), \
         patch.object(object_store, "_client", return_value=client), \
         patch.object(object_store, "settings", _r2_settings()):
        keys = object_store.upload_job_media(job_dir)
    assert client.upload_file.call_count == 3
    man = object_store.load_manifest(job_dir)
    assert "output.mp4" in man["files"]
    assert man["files"]["output.mp4"]["key"] == "jobs/abc123def456/output.mp4"
    assert set(keys) == {
        "jobs/abc123def456/output.mp4",
        "jobs/abc123def456/vocals.wav",
        "jobs/abc123def456/stems/speaker_01.wav",
    }
    # อัปซ้ำไม่ควรเรียก upload อีกถ้าขนาด/mtime เท่าเดิม
    with patch.object(object_store, "enabled", return_value=True), \
         patch.object(object_store, "_client", return_value=client), \
         patch.object(object_store, "settings", _r2_settings()):
        object_store.upload_job_media(job_dir)
    assert client.upload_file.call_count == 3


def test_purge_keeps_json_srt(job_dir: Path):
    man = {
        "files": {
            "output.mp4": {"key": "jobs/abc123def456/output.mp4", "size": 13, "mtime": 1.0},
            "vocals.wav": {"key": "jobs/abc123def456/vocals.wav", "size": 8, "mtime": 1.0},
            "stems/speaker_01.wav": {"key": "jobs/abc123def456/stems/speaker_01.wav", "size": 4, "mtime": 1.0},
        }
    }
    object_store.save_manifest(job_dir, man)
    n = object_store.purge_local_media(job_dir, only_uploaded=True)
    assert n == 3
    assert not (job_dir / "output.mp4").exists()
    assert (job_dir / "transcript.json").exists()
    assert (job_dir / "subtitles.srt").exists()
    assert (job_dir / "r2_manifest.json").exists()


def test_ensure_local_downloads_when_missing(job_dir: Path):
    (job_dir / "output.mp4").unlink()
    object_store.save_manifest(job_dir, {
        "files": {"output.mp4": {"key": "jobs/abc123def456/output.mp4", "size": 13, "mtime": 1.0}},
    })

    def fake_download(bucket, key, dest):
        Path(dest).write_bytes(b"from-r2")

    client = MagicMock()
    client.download_file.side_effect = fake_download
    with patch.object(object_store, "enabled", return_value=True), \
         patch.object(object_store, "_client", return_value=client), \
         patch.object(object_store, "settings", _r2_settings()):
        path = object_store.ensure_local(job_dir, job_dir / "output.mp4")
    assert path.exists()
    assert path.read_bytes() == b"from-r2"
    client.download_file.assert_called_once()


def test_delete_prefix_pages(job_dir: Path):
    client = MagicMock()
    client.list_objects_v2.side_effect = [
        {
            "Contents": [{"Key": "jobs/abc123def456/output.mp4"}],
            "IsTruncated": True,
            "NextContinuationToken": "t2",
        },
        {
            "Contents": [{"Key": "jobs/abc123def456/vocals.wav"}],
            "IsTruncated": False,
        },
    ]
    with patch.object(object_store, "enabled", return_value=True), \
         patch.object(object_store, "_client", return_value=client), \
         patch.object(object_store, "settings", _r2_settings()):
        n = object_store.delete_prefix("abc123def456")
    assert n == 2
    assert client.delete_objects.call_count == 2
