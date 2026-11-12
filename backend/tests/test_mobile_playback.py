"""มือถือเล่นวิดีโอผลลัพธ์ได้: Range 206 + H.264 Main / AAC / faststart"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.media_file import media_file_response
from app.pipeline.audio import h264_video_args
from app.pipeline.mix import mux_video


def _app(path: Path) -> FastAPI:
    app = FastAPI()

    @app.get("/v")
    def video(download: bool = False):
        return media_file_response(path, "video/mp4", "out.mp4", inline=not download)

    return app


def test_range_probe_returns_206(tmp_path: Path):
    """iOS ส่ง Range: bytes=0-1 ก่อนเล่น ต้องได้ 206 ไม่ใช่ทั้งไฟล์แบบ 200"""
    payload = bytes(range(256)) * 4
    path = tmp_path / "output.mp4"
    path.write_bytes(payload)
    client = TestClient(_app(path))

    probe = client.get("/v", headers={"Range": "bytes=0-1"})
    assert probe.status_code == 206
    assert probe.content == payload[:2]
    assert probe.headers["content-type"].startswith("video/mp4")
    assert probe.headers["accept-ranges"] == "bytes"
    assert probe.headers["content-range"] == f"bytes 0-1/{len(payload)}"
    assert probe.headers["content-length"] == "2"
    assert probe.headers["content-disposition"].startswith("inline;")
    assert "no-store" not in probe.headers.get("cache-control", "")

    whole = client.get("/v", headers={"Range": "bytes=0-"})
    assert whole.status_code == 206
    assert whole.content == payload
    assert whole.headers["content-length"] == str(len(payload))
    assert whole.headers["content-range"] == f"bytes 0-{len(payload) - 1}/{len(payload)}"

    full = client.get("/v")
    assert full.status_code == 200
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-length"] == str(len(payload))
    assert full.content == payload


def test_download_query_is_attachment(tmp_path: Path):
    path = tmp_path / "output.mp4"
    path.write_bytes(b"0123456789")
    client = TestClient(_app(path))
    res = client.get("/v", params={"download": "1"})
    assert res.status_code == 200
    assert res.headers["content-disposition"].startswith("attachment;")


def test_missing_media_is_404(tmp_path: Path):
    client = TestClient(_app(tmp_path / "missing.mp4"))
    assert client.get("/v").status_code == 404


def _cmds(monkeypatch, probe: str, fail_copy: bool = False) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None):
        text = [str(c) for c in cmd]
        calls.append(text)
        if text[0] == "ffprobe":
            return probe
        if fail_copy and "-c:v" in text and text[text.index("-c:v") + 1] == "copy":
            raise RuntimeError("copy failed")
        return ""

    monkeypatch.setattr("app.pipeline.mix.run", fake_run)
    return calls


def _has(cmd: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return any(cmd[i:i + n] == needle for i in range(len(cmd) - n + 1))


def test_h264_args_are_main_yuv420p():
    args = h264_video_args()
    assert args[args.index("-profile:v") + 1] == "main"
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert "-level" not in args


def test_mux_reencodes_with_aac_and_faststart(tmp_path: Path, monkeypatch):
    calls = _cmds(monkeypatch, "vp9,yuv420p\n")
    video, audio, out = tmp_path / "in.mp4", tmp_path / "a.wav", tmp_path / "out.mp4"
    video.write_bytes(b"v")
    audio.write_bytes(b"a")
    mux_video(video, audio, out)
    cmd = calls[-1]
    assert cmd[0] == "ffmpeg"
    assert _has(cmd, h264_video_args())
    assert _has(cmd, ["-c:a", "aac"])
    assert _has(cmd, ["-movflags", "+faststart"])


def test_mux_copies_h264_but_keeps_aac_faststart(tmp_path: Path, monkeypatch):
    calls = _cmds(monkeypatch, "h264,yuv420p\n")
    video, audio, out = tmp_path / "in.mp4", tmp_path / "a.wav", tmp_path / "out.mp4"
    video.write_bytes(b"v")
    audio.write_bytes(b"a")
    mux_video(video, audio, out)
    cmd = calls[-1]
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert _has(cmd, ["-c:a", "aac"])
    assert _has(cmd, ["-movflags", "+faststart"])


def test_mux_copy_failure_falls_back_to_mobile_encode(tmp_path: Path, monkeypatch):
    calls = _cmds(monkeypatch, "h264,yuv420p\n", fail_copy=True)
    video, audio, out = tmp_path / "in.mp4", tmp_path / "a.wav", tmp_path / "out.mp4"
    video.write_bytes(b"v")
    audio.write_bytes(b"a")
    mux_video(video, audio, out)
    assert _has(calls[-1], h264_video_args())
    assert _has(calls[-1], ["-movflags", "+faststart"])
