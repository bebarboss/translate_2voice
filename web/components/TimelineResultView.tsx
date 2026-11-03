"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fileUrl, type Job, type TimelineFormat, type TimelineInfo } from "@/lib/api";
import { ArrowLeft, DownloadIcon } from "./Icons";

const FORMATS: { id: TimelineFormat; label: string; hint: string }[] = [
  { id: "xml", label: "Final Cut Pro XML", hint: "นำเข้า Premiere Pro / DaVinci Resolve" },
  { id: "fcpxml", label: "FCPXML", hint: "นำเข้า DaVinci Resolve / Final Cut Pro" },
  { id: "stems", label: "เสียงพากย์แยกผู้พูด", hint: "WAV 24-bit ยาวเท่าไทม์ไลน์ วางที่ต้นไทม์ไลน์ได้เลย" },
  { id: "mix", label: "เสียงพากย์รวม", hint: "ผู้พูดทุกคนในไฟล์เดียว" },
  { id: "srt", label: "ซับไตเติล SRT", hint: "เวลาตาม timecode ของไทม์ไลน์" },
];

/** งานไทม์ไลน์ที่พากย์เสร็จ: ฟังเสียงพากย์รวม เลือกไฟล์ที่จะส่งกลับเข้าโปรแกรมตัดต่อ แล้วดาวน์โหลดเป็น zip */
export default function TimelineResultView({ job, onEdit }: { job: Job; onEdit: () => void }) {
  const [info, setInfo] = useState<TimelineInfo | null>(null);
  const [audio, setAudio] = useState<"dub" | "orig">("dub");
  const [formats, setFormats] = useState<TimelineFormat[]>(["xml", "fcpxml", "stems", "mix", "srt"]);
  const [mediaDir, setMediaDir] = useState("");
  useEffect(() => { api.getTimeline(job.id).then((s) => setInfo(s.timeline)).catch(() => setInfo(null)); }, [job.id]);

  const toggle = (f: TimelineFormat) => setFormats(formats.includes(f) ? formats.filter((x) => x !== f) : [...formats, f]);
  const speakers = info ? [...new Set(info.tracks.filter((t) => t.enabled && t.clips.length).map((t) => t.speaker_name || t.name))] : [];
  const needsDir = formats.includes("xml") || formats.includes("fcpxml");

  return (
    <main className="page" style={{ maxWidth: 960 }}>
      <div className="page-head">
        <div>
          <Link href="/jobs" className="dim" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><ArrowLeft />งานทั้งหมด</Link>
          <h1 style={{ margin: "6px 0 0" }}>{info?.name || job.filename}</h1>
          {info && <span className="muted">{info.fps} fps{info.drop_frame ? " drop-frame" : ""} · {info.sample_rate / 1000} kHz
            · {info.start_tc} – ยาว {info.duration_tc} · ผู้พูด {speakers.length} คน</span>}
        </div>
        <button type="button" className="btn" onClick={onEdit}>แก้บทแล้วพากย์ใหม่</button>
      </div>

      <section className="card" aria-labelledby="listen-title">
        <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
          <h2 id="listen-title" style={{ margin: 0 }}>ฟังผลลัพธ์</h2>
          <div className="seg" role="group" aria-label="เสียงที่ฟัง">
            <button type="button" aria-pressed={audio === "dub"} onClick={() => setAudio("dub")}>เสียงพากย์</button>
            <button type="button" aria-pressed={audio === "orig"} onClick={() => setAudio("orig")}>เสียงต้นฉบับ</button>
          </div>
        </div>
        <audio key={audio} controls preload="metadata" style={{ width: "100%" }}
          src={audio === "dub" ? fileUrl.stem(job.id, "final_audio") : fileUrl.source(job.id)} />
        {speakers.length > 0 && <span className="dim">ผู้พูด: {speakers.join(", ")}</span>}
      </section>

      <section className="card" aria-labelledby="export-title">
        <h2 id="export-title" style={{ margin: 0 }}>ส่งออกกลับเข้าโปรแกรมตัดต่อ</h2>
        <div style={{ display: "grid", gap: 8 }}>
          {FORMATS.map((f) => (
            <label key={f.id} className="agree">
              <input type="checkbox" checked={formats.includes(f.id)} onChange={() => toggle(f.id)} />
              <span>{f.label} <span className="dim">· {f.hint}</span></span>
            </label>
          ))}
        </div>
        {needsDir && (
          <div className="field">
            <label htmlFor="media-dir">โฟลเดอร์ที่จะวางไฟล์เสียงพากย์บนเครื่องตัดต่อ (ไม่บังคับ)</label>
            <input id="media-dir" className="input" value={mediaDir} onChange={(e) => setMediaDir(e.target.value)}
              placeholder="เช่น D:\Projects\EP01\TH_dub  ว่าง = โฟลเดอร์ TH_dub ข้างไฟล์เสียงเดิม" />
            <span className="dim">ไฟล์ XML จะชี้ไปที่โฟลเดอร์นี้ แตก zip แล้ววางโฟลเดอร์ TH_dub ไว้ตรงนั้น โปรแกรมตัดต่อจะหาไฟล์เจอเอง (อ่านวิธีใน README ใน zip)</span>
          </div>
        )}
        <div className="row">
          <a className={`btn primary${formats.length ? "" : " disabled"}`} aria-disabled={!formats.length}
            href={formats.length ? fileUrl.timelineExport(job.id, formats, mediaDir.trim()) : undefined} download>
            <DownloadIcon />ดาวน์โหลด zip
          </a>
        </div>
      </section>
    </main>
  );
}
