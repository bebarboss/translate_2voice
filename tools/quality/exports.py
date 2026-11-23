"""Find and load job exports. Supported layouts (all produced by the app today):

1. job folder (data/jobs/<id>/, as JobStore writes it):
     job.json, transcript.json, final_audio.wav, dub_voice.wav, bgm.wav, tts/<id:04d>.wav, subtitles*.srt
   Missing transcript.json falls back to the SRT (no source text, so most rules cannot run).
2. timeline export (timeline/exporter.py zip, or the folder it was unpacked to):
     TH_mixdown.wav, TH_<n>_<name>.wav (one dub stem per speaker), *.srt, README.md
3. plain export (GET /jobs/{id}/export zip): <name>.mp4 + <name>.srt
Zips are unpacked under <out>/_unzipped/ first.
"""
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.schemas import Utterance

MEDIA_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".wav", ".mp3", ".m4a", ".flac"}


@dataclass
class JobExport:
    job_id: str
    kind: str                      # job_dir | timeline | plain
    root: Path
    utts: list[Utterance]
    target_lang: str = "th"
    hints: dict = field(default_factory=dict)
    final: Optional[Path] = None   # the finished mix that people hear
    voice: list[Path] = field(default_factory=list)  # dub voice track(s), summed
    bgm: Optional[Path] = None     # background stem before ducking
    tts: dict[int, Path] = field(default_factory=dict)  # utterance id -> rendered dub line
    has_source: bool = True
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- SRT
_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _sec(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 10 ** len(ms)


def parse_srt(text: str) -> list[Utterance]:
    out: list[Utterance] = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "").strip()):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = _TS.search(line)
            if m:
                g = m.groups()
                body = " ".join(x.strip() for x in lines[i + 1:] if x.strip())
                out.append(Utterance(id=len(out), speaker="", start=_sec(*g[:4]), end=_sec(*g[4:]),
                                     source="", target=body))
                break
    return out


# ---------------------------------------------------------------- discovery
def _safe_unzip(zpath: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            name = Path(info.filename)
            if info.is_dir() or name.is_absolute() or ".." in name.parts:
                continue
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
    return dest


def _is_job_dir(d: Path) -> bool:
    return (d / "job.json").is_file()


def _is_timeline(d: Path) -> bool:
    return (d / "TH_mixdown.wav").is_file() or any(d.glob("TH_*_*.wav"))


def _is_plain(d: Path) -> bool:
    return any(d.glob("*.srt")) and any(p.suffix.lower() in MEDIA_EXT for p in d.iterdir() if p.is_file())


def discover(root: Path, unzip_dir: Path) -> list[Path]:
    """Every export folder under root (root itself may be one). Zips are unpacked to unzip_dir first."""
    root = root.resolve()
    for z in sorted(root.rglob("*.zip")):
        if unzip_dir.resolve() in z.resolve().parents:
            continue
        try:
            _safe_unzip(z, unzip_dir / z.stem)
        except zipfile.BadZipFile:
            continue
    found: list[Path] = []
    for base in (root, unzip_dir):
        if not base.exists():
            continue
        for d in [base, *sorted(p for p in base.rglob("*") if p.is_dir())]:
            if any(f in d.parents for f in found):
                continue  # inside an export already found (tts/, stems/, timeline/)
            if _is_job_dir(d) or _is_timeline(d) or _is_plain(d):
                found.append(d)
    return found


# ---------------------------------------------------------------- load
def _project_glossary(d: Path, project_id: Optional[str]) -> str:
    if not project_id:
        return ""
    for p in (d / "project.json", d.parent.parent / "projects" / f"{project_id}.json",
              d.parent / "projects" / f"{project_id}.json"):
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8")).get("glossary") or ""
            except (OSError, ValueError):
                return ""
    return ""


def _merge_glossary(*parts: str) -> str:
    lines, known = [], set()
    for part in parts:
        for line in (part or "").splitlines():
            key = line.split("=")[0].strip().lower()
            if line.strip() and key not in known:
                known.add(key)
                lines.append(line)
    return "\n".join(lines)


def _srt_in(d: Path) -> Optional[Path]:
    for name in ("subtitles.srt", "subtitles_th.srt"):
        if (d / name).is_file():
            return d / name
    srts = sorted(d.glob("*.srt"))
    return srts[0] if srts else None


def load(d: Path, extra_glossary: str = "") -> JobExport:
    if _is_job_dir(d):
        return _load_job_dir(d, extra_glossary)
    srt = _srt_in(d)
    utts = parse_srt(srt.read_text(encoding="utf-8", errors="replace")) if srt else []
    if _is_timeline(d):
        mix = d / "TH_mixdown.wav"
        ex = JobExport(job_id=d.name, kind="timeline", root=d, utts=utts, final=mix if mix.is_file() else None,
                       voice=sorted(p for p in d.glob("TH_*_*.wav")), has_source=False,
                       hints={"glossary": extra_glossary})
    else:
        media = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_EXT)
        ex = JobExport(job_id=d.name, kind="plain", root=d, utts=utts, final=media[0] if media else None,
                       has_source=False, hints={"glossary": extra_glossary})
    ex.notes.append("no source text in this export: number/name/particle rules skipped")
    if ex.kind == "plain":
        ex.notes.append("no voice/bgm stems: overrun and ducking not measured")
    return ex


def _load_job_dir(d: Path, extra_glossary: str) -> JobExport:
    from app.pipeline import translate as T
    job = json.loads((d / "job.json").read_text(encoding="utf-8"))
    tp = d / "transcript.json"
    notes = []
    if tp.is_file():
        utts = [Utterance.model_validate(x) for x in json.loads(tp.read_text(encoding="utf-8"))]
        has_source = True
    else:
        srt = _srt_in(d)
        utts = parse_srt(srt.read_text(encoding="utf-8", errors="replace")) if srt else []
        has_source = False
        notes.append("no transcript.json: rules that need source text skipped")
    hints = {"glossary": _merge_glossary(job.get("glossary") or "", extra_glossary,
                                         _project_glossary(d, job.get("project_id"))),
             "names": job.get("speaker_names") or {}}
    hints = T.story_hints(job.get("story"), hints)
    tts = {}
    for p in (d / "tts").glob("*.wav") if (d / "tts").is_dir() else []:
        if re.fullmatch(r"\d{4}", p.stem):  # NNNN.wav = current take; NNNN.<key>.wav = cached takes
            tts[int(p.stem)] = p
    final = d / "final_audio.wav"
    voice = d / "dub_voice.wav"
    bgm = d / "bgm.wav"
    if not final.is_file():
        media = Path(job.get("output_path") or "") if job.get("output_path") else None
        final = media if media and media.is_file() else None
        notes.append("no final_audio.wav")
    return JobExport(job_id=str(job.get("id") or d.name), kind="job_dir", root=d, utts=utts,
                     target_lang=job.get("target_lang") or "th", hints=hints,
                     final=final if final and final.is_file() else None,
                     voice=[voice] if voice.is_file() else [], bgm=bgm if bgm.is_file() else None,
                     tts=tts, has_source=has_source, notes=notes)
