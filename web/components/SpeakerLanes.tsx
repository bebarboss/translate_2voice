"use client";

import { useState } from "react";
import { fileUrl, type Job, type Utterance } from "@/lib/api";
import { fmtTime, speakerColor, speakerLabel } from "@/lib/format";
import type { Transcript } from "@/lib/useTranscript";
import { XIcon } from "./Icons";

/** เลเยอร์เสียงของแต่ละตัวละครบนเส้นเวลา คลิกบล็อกเพื่อเลือกประโยค ลบตัวละครที่ระบบแยกเกินได้ */
export default function SpeakerLanes({ job, tr, total, t, highlight, onPick, onRetimed, stemLabel = "ฟังเสียงแยก" }: {
  job: Job;
  tr: Transcript;
  total: number;
  t: number;
  highlight: number | null; // ประโยคที่เน้น (กำลังพูดหรือที่เลือกไว้) มีที่จับให้ลากขอบปรับเวลา
  onPick: (u: Utterance) => void;
  onRetimed?: (sec: number) => void; // ลากขอบเสร็จ (เวลาของขอบที่ลาก) ใช้เลื่อนวิดีโอไปฟังตรงนั้น
  stemLabel?: string;
}) {
  const [removing, setRemoving] = useState<{ speaker: string; into: string } | null>(null);
  const { speakers, sorted, busy } = tr;
  const playheadPct = `${Math.min(100, (t / Math.max(total, 1e-3)) * 100)}%`;
  const pct = (sec: number) => `${(sec / total) * 100}%`;

  // ลากที่จับขอบบล็อก: แปลงตำแหน่งเมาส์บนแถบเป็นวินาที ปัดทีละ 0.05 วินาที ประโยคยาวอย่างน้อย 0.2 วินาที
  const drag = (u: Utterance, edge: "start" | "end") => (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const handle = e.currentTarget;
    const rect = handle.parentElement!.getBoundingClientRect();
    handle.setPointerCapture(e.pointerId);
    let last = tr.draftOf(u)[edge];
    const move = (ev: PointerEvent) => {
      const d = tr.draftOf(u);
      let sec = Math.round(((ev.clientX - rect.left) / rect.width) * total * 20) / 20;
      sec = edge === "start" ? Math.min(Math.max(0, sec), d.end - 0.2) : Math.max(Math.min(total, sec), d.start + 0.2);
      last = sec;
      tr.setDraft(u.id, { [edge]: sec });
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      onRetimed?.(last);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
  };

  return (
    <div className="card tight">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ fontSize: 15 }}>เลเยอร์เสียงตัวละคร</h2>
        <span className="dim">คลิกบล็อกเพื่อเลือกประโยคนั้น</span>
      </div>
      <div className="lanes">
        {speakers.map((s) => {
          const color = speakerColor(s, speakers);
          const own = sorted.filter((u) => tr.draftOf(u).speaker === s);
          return (
            <div key={s} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div className="lane">
                <div className="who"><span className="swatch" style={{ background: color }} />{speakerLabel(s)}</div>
                <div className="track">
                  {own.map((u) => {
                    const d = tr.draftOf(u);
                    return (
                      <button key={u.id} type="button" className="block"
                        aria-label={`${speakerLabel(s)} ${fmtTime(d.start)}`} title={d.target}
                        onClick={() => onPick(u)}
                        style={{
                          left: pct(d.start),
                          width: pct(d.end - d.start),
                          background: color,
                          opacity: highlight === u.id ? 1 : 0.45,
                        }} />
                    );
                  })}
                  {own.filter((u) => u.id === highlight).map((u) => {
                    const d = tr.draftOf(u);
                    return [
                      <div key="s" className="handle" style={{ left: pct(d.start) }} onPointerDown={drag(u, "start")}
                        title="ลากเพื่อเลื่อนเวลาเริ่ม" aria-hidden="true" />,
                      <div key="e" className="handle" style={{ left: pct(d.end) }} onPointerDown={drag(u, "end")}
                        title="ลากเพื่อเลื่อนเวลาจบ" aria-hidden="true" />,
                    ];
                  })}
                  <div className="playhead" style={{ left: playheadPct }} />
                </div>
                <a href={fileUrl.stem(job.id, s)} target="_blank" rel="noreferrer" className="dim" style={{ flex: "none", color: "var(--accent)" }}>{stemLabel}</a>
                <button type="button" className="icon-btn" aria-label={`ลบ${speakerLabel(s)}`} title="ลบตัวละครนี้"
                  disabled={!!busy || speakers.length < 2}
                  onClick={() => own.length ? setRemoving({ speaker: s, into: speakers.find((x) => x !== s) ?? "" })
                    : tr.removeSpeaker(s, "")}>
                  <XIcon />
                </button>
              </div>
              {removing?.speaker === s && (
                <div className="lane-remove">
                  <span>ลบ{speakerLabel(s)} ย้าย {own.length} ประโยคไปให้</span>
                  <label className="sr-only" htmlFor={`into-${s}`}>ตัวละครที่รับประโยคไป</label>
                  <select id={`into-${s}`} className="spk-select" value={removing.into}
                    onChange={(e) => setRemoving({ speaker: s, into: e.target.value })}>
                    {speakers.filter((x) => x !== s).map((x) => <option key={x} value={x}>{speakerLabel(x)}</option>)}
                  </select>
                  <button type="button" className="btn small danger"
                    onClick={() => { setRemoving(null); tr.removeSpeaker(s, removing.into); }}>ลบ</button>
                  <button type="button" className="btn small" onClick={() => setRemoving(null)}>ยกเลิก</button>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <span className="dim">แยกเสียงผิด? คนเดียวถูกแยกเป็นสองตัวละคร กด ✕ เพื่อรวมเข้าตัวอื่น · สองคนถูกรวมเป็นตัวเดียว เลือก “+ ตัวละครใหม่” ในช่องตัวละครของประโยค · สองคนพูดในประโยคเดียว กด “แยกประโยค”</span>
    </div>
  );
}
