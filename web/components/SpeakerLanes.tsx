"use client";

import { useRef, useState } from "react";
import { fileUrl, type Job, type Utterance } from "@/lib/api";
import { fmtTime, speakerColor } from "@/lib/format";
import type { Transcript } from "@/lib/useTranscript";
import { ScissorsIcon, XIcon } from "./Icons";

/** เลเยอร์เสียงของแต่ละตัวละครบนเส้นเวลา คลิกบล็อกเพื่อเลือกประโยค ลากบล็อกเพื่อเลื่อนเวลาหรือย้ายไปตัวละครอื่น
 *  เครื่องมือตัดแบ่งประโยคตรงที่คลิก ประโยคของต่างตัวละครวางซ้อนเวลากันได้ (เสียงพากย์จะเล่นทับกัน)
 *  ลบตัวละครที่ระบบแยกเกินได้ */
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
  const [naming, setNaming] = useState<{ speaker: string; name: string } | null>(null);
  const [tool, setTool] = useState<"move" | "cut">("move");
  const [guide, setGuide] = useState<{ speaker: string; sec: number } | null>(null); // เส้นบอกจุดตัด
  const [dropLane, setDropLane] = useState<string | null>(null); // เลเยอร์ที่กำลังลากบล็อกไปวาง
  const dragged = useRef(false); // เพิ่งลากบล็อกเสร็จ ไม่นับเป็นคลิกเลือก
  const speakerLabel = tr.label;
  const finishNaming = () => {
    if (naming && naming.name.trim() !== (tr.names[naming.speaker] ?? "")) tr.renameSpeaker(naming.speaker, naming.name.trim());
    setNaming(null);
  };
  const { speakers, sorted, busy } = tr;
  const playheadPct = `${Math.min(100, (t / Math.max(total, 1e-3)) * 100)}%`;
  const pct = (sec: number) => `${(sec / total) * 100}%`;

  const secAt = (clientX: number, track: Element) => {
    const rect = track.getBoundingClientRect();
    return Math.min(total, Math.max(0, ((clientX - rect.left) / rect.width) * total));
  };
  const laneAt = (x: number, y: number) =>
    (document.elementFromPoint(x, y)?.closest("[data-speaker]") as HTMLElement | null)?.dataset.speaker ?? null;

  // ลากทั้งบล็อก: เลื่อนเวลาทั้งประโยค (ความยาวเท่าเดิม) และย้ายไปเลเยอร์ตัวละครอื่นได้ ขยับไม่ถึง 4 px นับเป็นคลิก
  const press = (u: Utterance, speaker: string) => (e: React.PointerEvent<HTMLButtonElement>) => {
    if (tool !== "move" || e.button !== 0) return;
    const block = e.currentTarget;
    const rect = block.parentElement!.getBoundingClientRect();
    const x0 = e.clientX;
    const d0 = tr.draftOf(u);
    const len = d0.end - d0.start;
    let moved = false;
    let start = d0.start;
    let lane = speaker;
    dragged.current = false;
    const move = (ev: PointerEvent) => {
      if (!moved && Math.abs(ev.clientX - x0) < 4 && Math.abs(ev.clientY - e.clientY) < 4) return;
      moved = true;
      const shift = Math.round(((ev.clientX - x0) / rect.width) * total * 20) / 20;
      start = Math.round(Math.min(Math.max(0, d0.start + shift), total - len) * 100) / 100;
      tr.setDraft(u.id, { start, end: Math.round((start + len) * 100) / 100 });
      lane = laneAt(ev.clientX, ev.clientY) ?? lane;
      setDropLane(lane !== speaker ? lane : null);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      setDropLane(null);
      if (!moved) return;
      dragged.current = true;
      if (lane !== speaker) tr.setDraft(u.id, { speaker: lane });
      onRetimed?.(start);
    };
    // ฟังที่ window ไม่ใช่ที่บล็อก เพราะเมาส์หลุดออกจากบล็อกได้ระหว่างลาก
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  };

  // คลิกบล็อก: เครื่องมือตัด → ตัดตรงที่คลิก, เครื่องมือปกติ → เลือกประโยค (ยกเว้นเพิ่งลากเสร็จ)
  const click = (u: Utterance) => (e: React.MouseEvent<HTMLButtonElement>) => {
    if (tool === "cut") {
      const sec = e.detail === 0 ? t : secAt(e.clientX, e.currentTarget.parentElement!); // กดด้วยคีย์บอร์ด = ตัดที่หัวอ่าน
      tr.splitAt(u, sec);
      return;
    }
    if (dragged.current) {
      dragged.current = false;
      return;
    }
    onPick(u);
  };

  // ตัดประโยคที่หัวอ่านอยู่ (ประโยคที่เลือกไว้ก่อน ถ้าหัวอ่านไม่อยู่ในประโยคนั้น ใช้ประโยคแรกที่ครอบหัวอ่าน)
  const under = sorted.filter((u) => { const d = tr.draftOf(u); return d.start + 0.2 < t && t < d.end - 0.2; });
  const cutTarget = under.find((u) => u.id === highlight) ?? under[0];

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
        <div className="row" style={{ gap: 8 }}>
          <div className="seg small" role="group" aria-label="เครื่องมือบนเส้นเวลา">
            <button type="button" aria-pressed={tool === "move"} onClick={() => setTool("move")} title="คลิกเพื่อเลือก ลากเพื่อเลื่อนเวลาหรือย้ายตัวละคร">
              เลือก/ลาก
            </button>
            <button type="button" aria-pressed={tool === "cut"} onClick={() => setTool("cut")} title="คลิกบนบล็อกตรงที่จะตัดแบ่งประโยค">
              <ScissorsIcon /> ตัด
            </button>
          </div>
          <button type="button" className="btn small" disabled={!!busy || !cutTarget}
            onClick={() => cutTarget && tr.splitAt(cutTarget, t)} title="ตัดประโยคตรงตำแหน่งที่วิดีโอเล่นอยู่">
            ตัดที่หัวอ่าน
          </button>
        </div>
      </div>
      <div className={`lanes${tool === "cut" ? " cutting" : ""}`}>
        {speakers.map((s) => {
          const color = speakerColor(s, speakers);
          const own = sorted.filter((u) => tr.draftOf(u).speaker === s);
          return (
            <div key={s} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div className={`lane${dropLane === s ? " drop" : ""}`} data-speaker={s}>
                <div className="who">
                  <span className="swatch" style={{ background: color }} />
                  {naming?.speaker === s ? (
                    <input className="who-input" autoFocus maxLength={40} value={naming.name} placeholder={speakerLabel(s)}
                      aria-label={`ชื่อของ${speakerLabel(s)}`}
                      onChange={(e) => setNaming({ speaker: s, name: e.target.value })}
                      onBlur={finishNaming}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") finishNaming();
                        if (e.key === "Escape") setNaming(null);
                      }} />
                  ) : (
                    <button type="button" className="who-name" title="คลิกเพื่อตั้งชื่อตัวละคร"
                      onClick={() => setNaming({ speaker: s, name: tr.names[s] ?? "" })}>{speakerLabel(s)}</button>
                  )}
                </div>
                <div className="track"
                  onPointerMove={(e) => tool === "cut" && setGuide({ speaker: s, sec: secAt(e.clientX, e.currentTarget) })}
                  onPointerLeave={() => setGuide(null)}>
                  {own.map((u) => {
                    const d = tr.draftOf(u);
                    return (
                      <button key={u.id} type="button" className="block"
                        aria-label={`${speakerLabel(s)} ${fmtTime(d.start)}`} title={d.target}
                        onClick={click(u)} onPointerDown={press(u, s)}
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
                  {tool === "cut" && guide?.speaker === s && <div className="cut-guide" style={{ left: pct(guide.sec) }} />}
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
      <span className="dim">ลากบล็อกเพื่อเลื่อนเวลา หรือลากไปเลเยอร์อื่นเพื่อเปลี่ยนตัวละคร (วางซ้อนเวลากับตัวละครอื่นได้ เสียงจะพูดทับกัน) · เครื่องมือ “ตัด” คลิกตรงที่จะแบ่งประโยค · คนเดียวถูกแยกเป็นสองตัวละคร กด ✕ เพื่อรวม · คลิกชื่อตัวละครเพื่อตั้งชื่อ</span>
    </div>
  );
}
