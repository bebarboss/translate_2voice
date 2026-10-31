"use client";

import { useState } from "react";
import { fileUrl, type Job, type Utterance } from "@/lib/api";
import { fmtTime, speakerColor, speakerLabel } from "@/lib/format";
import type { Transcript } from "@/lib/useTranscript";
import { XIcon } from "./Icons";

/** เลเยอร์เสียงของแต่ละตัวละครบนเส้นเวลา คลิกบล็อกเพื่อเลือกประโยค ลบตัวละครที่ระบบแยกเกินได้ */
export default function SpeakerLanes({ job, tr, total, t, highlight, onPick, stemLabel = "ฟังเสียงแยก" }: {
  job: Job;
  tr: Transcript;
  total: number;
  t: number;
  highlight: number | null; // ประโยคที่เน้น (กำลังพูดหรือที่เลือกไว้)
  onPick: (u: Utterance) => void;
  stemLabel?: string;
}) {
  const [removing, setRemoving] = useState<{ speaker: string; into: string } | null>(null);
  const { speakers, sorted, busy } = tr;
  const playheadPct = `${Math.min(100, (t / Math.max(total, 1e-3)) * 100)}%`;

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
                  {own.map((u) => (
                    <button key={u.id} type="button" className={`block${highlight === u.id ? " on" : ""}`}
                      aria-label={`${speakerLabel(s)} ${fmtTime(u.start)}`} title={tr.draftOf(u).target}
                      onClick={() => onPick(u)}
                      style={{
                        left: `${(u.start / total) * 100}%`,
                        width: `${((u.end - u.start) / total) * 100}%`,
                        background: color,
                        opacity: highlight === u.id ? 1 : 0.45,
                      }} />
                  ))}
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
