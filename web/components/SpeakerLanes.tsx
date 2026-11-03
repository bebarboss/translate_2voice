"use client";

import { useEffect, useRef, useState } from "react";
import { fileUrl, type Job, type Utterance } from "@/lib/api";
import { fmtTime, speakerColor } from "@/lib/format";
import type { Transcript } from "@/lib/useTranscript";
import { CopyIcon, PasteIcon, ScissorsIcon, XIcon } from "./Icons";

import { tx } from "@/lib/i18n";
/** เลเยอร์เสียงของแต่ละตัวละครบนเส้นเวลา คลิกบล็อกเพื่อเลือกประโยค ลากบล็อกเพื่อเลื่อนเวลาหรือย้ายไปตัวละครอื่น
 *  เครื่องมือตัดแบ่งประโยคตรงที่คลิก ประโยคของต่างตัวละครวางซ้อนเวลากันได้ (เสียงพากย์จะเล่นทับกัน)
 *  ซูมเข้าออกและเลื่อนช่วงเวลาที่แสดงได้ (ปุ่ม แถบเลื่อน Ctrl+ล้อเมาส์ Shift+ล้อเมาส์ หรือลากที่ว่างบนแถบ)
 *  ลบตัวละครที่ระบบแยกเกินได้ */
const ZOOMS = [1, 2, 4, 8, 16, 32];
const TICKS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200];
export default function SpeakerLanes({ job, tr, total, t, highlight, onPick, onRetimed, onSeek, voiceSlot, voiceHead, stemLabel = tx("ฟังเสียงแยก") }: {
  job: Job;
  tr: Transcript;
  total: number;
  t: number;
  highlight: number | null; // ประโยคที่เน้น (กำลังพูดหรือที่เลือกไว้) มีที่จับให้ลากขอบปรับเวลา
  onPick: (u: Utterance) => void;
  onRetimed?: (sec: number) => void; // ลากขอบเสร็จ (เวลาของขอบที่ลาก) ใช้เลื่อนวิดีโอไปฟังตรงนั้น
  onSeek?: (sec: number) => void; // คลิกหรือลากบนไม้บรรทัดเวลา เลื่อนวิดีโอไปเวลานั้น
  stemLabel?: string;
  voiceSlot?: (speaker: string) => React.ReactNode; // ปุ่มเลือกเสียงพากย์ท้ายเลเยอร์ (ไม่ส่ง = ลิงก์ฟังเสียงแยก)
  voiceHead?: React.ReactNode; // หัวคอลัมน์เสียง (แถวเดียวกับไม้บรรทัดเวลา) เช่นปุ่มใช้เสียงแนะนำทั้งหมด
}) {
  const [removing, setRemoving] = useState<{ speaker: string; into: string } | null>(null);
  const [naming, setNaming] = useState<{ speaker: string; name: string } | null>(null);
  const [tool, setTool] = useState<"move" | "cut">("move");
  const [guide, setGuide] = useState<{ speaker: string; sec: number } | null>(null); // เส้นบอกจุดตัด
  const [dropLane, setDropLane] = useState<string | null>(null); // เลเยอร์ที่กำลังลากบล็อกไปวาง
  const dragged = useRef(false); // เพิ่งลากบล็อกเสร็จ ไม่นับเป็นคลิกเลือก
  const [clip, setClip] = useState<number | null>(null); // ประโยคที่คัดลอกไว้
  const pointer = useRef<{ x: number; y: number } | null>(null); // ตำแหน่งเมาส์ล่าสุด ใช้หาเลเยอร์ปลายทางของการวาง
  const speakerLabel = tr.label;
  const finishNaming = () => {
    if (naming && naming.name.trim() !== (tr.names[naming.speaker] ?? "")) tr.renameSpeaker(naming.speaker, naming.name.trim());
    setNaming(null);
  };
  const { speakers, sorted, busy } = tr;

  // ช่วงเวลาที่แสดง: ซูม z เท่า แสดง total/z วินาที เริ่มที่ from
  const [zoom, setZoom] = useState(1);
  const [from, setFrom] = useState(0);
  const span = Math.max(total, 1e-3) / zoom;
  // ท้ายคลิปที่ลากบล็อกไปได้: ใช้ความยาวที่เซิร์ฟเวอร์วัด (ความยาวในเบราว์เซอร์อาจเกินเล็กน้อย เซิร์ฟเวอร์จะไม่รับ)
  const limit = job.duration ? Math.min(total, job.duration) : total;
  const clampFrom = (x: number) => Math.min(Math.max(0, x), Math.max(0, total - span));
  const view = clampFrom(from);
  const pct = (sec: number) => `${((sec - view) / span) * 100}%`;
  const width = (sec: number) => `${(sec / span) * 100}%`;
  const playheadPct = pct(Math.min(t, total));
  const lanesRef = useRef<HTMLDivElement>(null);

  /** ซูมโดยให้เวลาที่ anchor (วินาที) อยู่ที่เดิมบนจอ */
  const zoomTo = (z: number, anchor = view + span / 2) => {
    const next = Math.min(Math.max(z, 1), ZOOMS[ZOOMS.length - 1]);
    const nextSpan = Math.max(total, 1e-3) / next;
    const ratio = (anchor - view) / span;
    setZoom(next);
    setFrom(Math.min(Math.max(0, anchor - ratio * nextSpan), Math.max(0, total - nextSpan)));
  };
  const step = (dir: 1 | -1) => zoomTo(ZOOMS[Math.min(Math.max(ZOOMS.findIndex((z) => z >= zoom) + dir, 0), ZOOMS.length - 1)],
    t >= view && t <= view + span ? t : undefined);

  // วิดีโอเล่นออกนอกช่วงที่แสดง → เลื่อนตาม ให้หัวอ่านอยู่ใกล้ขอบซ้าย
  useEffect(() => {
    if (zoom > 1 && (t < view || t > view + span)) setFrom(clampFrom(t - span * 0.1));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t]);

  // Ctrl/⌘ + ล้อเมาส์ (หรือหนีบ touchpad) ที่ไหนก็ได้ในการ์ดนี้ = ซูมเส้นเวลา ไม่ใช่ซูมทั้งหน้าเว็บ
  // ซูมรอบเวลาใต้เมาส์ (เมาส์อยู่นอกแถบ ใช้หัวอ่านถ้าเห็นอยู่ ไม่งั้นกลางจอ)
  // Shift + ล้อเมาส์ หรือปัดแนวนอนบนแถบ = เลื่อนเวลา (ล้อปกติยังเลื่อนหน้าเว็บ)
  const wheel = useRef<(e: WheelEvent) => void>(() => undefined);
  wheel.current = (e: WheelEvent) => {
    const track = (e.target as Element).closest(".track") ?? lanesRef.current?.querySelector(".track");
    if (!track) return;
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const rect = track.getBoundingClientRect();
      const inside = e.clientX >= rect.left && e.clientX <= rect.right;
      const anchor = inside ? secAt(e.clientX, track) : t >= view && t <= view + span ? t : undefined;
      // ล้อเมาส์หนึ่งคลิกราว 100 → ซูม 1.25 เท่า, touchpad ส่งค่าเล็กกว่ามาถี่ ๆ ซูมนุ่มตามนิ้ว
      const factor = Math.min(2, Math.max(0.5, Math.exp(-e.deltaY * 0.0022)));
      zoomTo(zoom * factor, anchor);
    } else if (zoom > 1 && (e.target as Element).closest(".track")
               && (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY))) {
      e.preventDefault();
      const d = e.shiftKey ? e.deltaY || e.deltaX : e.deltaX;
      setFrom(clampFrom(view + (d / track.getBoundingClientRect().width) * span));
    }
  };
  const cardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = cardRef.current;
    if (!el) return;
    const on = (e: WheelEvent) => wheel.current(e);
    el.addEventListener("wheel", on, { passive: false });
    return () => el.removeEventListener("wheel", on);
  }, []);

  // ลากที่ว่างบนแถบ (ไม่โดนบล็อก) = เลื่อนช่วงเวลาที่แสดง
  const pan = (e: React.PointerEvent<HTMLDivElement>) => {
    if (zoom <= 1 || e.button !== 0 || e.target !== e.currentTarget || tool !== "move") return;
    e.preventDefault(); // ไม่ให้ลากแล้วไปเลือกข้อความบนหน้า
    const w = e.currentTarget.getBoundingClientRect().width;
    const x0 = e.clientX;
    const f0 = view;
    const move = (ev: PointerEvent) => setFrom(clampFrom(f0 - ((ev.clientX - x0) / w) * span));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // คลิกหรือลากบนไม้บรรทัดเวลา = เลื่อนวิดีโอ (เหมือนแถบเวลาของวิดีโอ)
  const scrub = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!onSeek || e.button !== 0) return;
    e.preventDefault();
    const track = e.currentTarget;
    onSeek(secAt(e.clientX, track));
    const move = (ev: PointerEvent) => onSeek(secAt(ev.clientX, track));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const tick = TICKS.find((x) => span / x <= 8) ?? TICKS[TICKS.length - 1];
  const ticks: number[] = [];
  for (let x = Math.ceil(view / tick) * tick; x <= view + span + 1e-6; x += tick) ticks.push(x);
  const fmtTick = (sec: number) => {
    const m = Math.floor(sec / 60);
    const r = sec - m * 60;
    return `${m}:${(tick < 1 ? r.toFixed(1) : String(Math.round(r))).padStart(tick < 1 ? 4 : 2, "0")}`;
  };

  const secAt = (clientX: number, track: Element) => {
    const rect = track.getBoundingClientRect();
    return Math.min(total, Math.max(0, view + ((clientX - rect.left) / rect.width) * span));
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
      const shift = Math.round(((ev.clientX - x0) / rect.width) * span * 20) / 20;
      start = Math.round(Math.min(Math.max(0, d0.start + shift), limit - len) * 100) / 100;
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

  // คัดลอก/วางประโยค: ใช้ตอนสองคนพูดพร้อมกันแต่ถอดเสียงได้คนเดียว วางสำเนาซ้อนเวลาเดิมให้อีกตัวละครแล้วแก้บท
  const copy = () => {
    if (highlight == null) return;
    setClip(highlight);
    tr.setMessage({ kind: "info", text: tx("คัดลอกประโยคแล้ว ชี้เมาส์ที่เลเยอร์ตัวละครปลายทางแล้วกด Ctrl+V หรือปุ่มวาง") });
  };
  const paste = async () => {
    const src = sorted.find((u) => u.id === clip);
    if (!src) return;
    const d = tr.draftOf(src);
    // ปลายทาง: เลเยอร์ที่เมาส์ชี้ ถ้าไม่ได้ชี้หรือชี้เลเยอร์เดิม ใช้ตัวละครอื่นตัวแรก
    const hover = pointer.current && laneAt(pointer.current.x, pointer.current.y);
    const lane = hover && hover !== d.speaker ? hover : speakers.find((s) => s !== d.speaker) ?? d.speaker;
    // เวลาเดิม (พูดซ้อนกัน) ถ้าตัวละครปลายทางพูดอยู่ช่วงนั้นแล้ว วางที่หัวอ่านแทน
    const busyAt = (a: number) => sorted.some((u) => {
      const x = tr.draftOf(u);
      return x.speaker === lane && Math.min(a + (d.end - d.start), x.end) - Math.max(a, x.start) > 0.1;
    });
    const start = busyAt(d.start) ? Math.round(t * 100) / 100 : d.start;
    const created = await tr.duplicate(src, lane, start);
    if (created) onPick(created);
  };
  const keys = useRef<(e: KeyboardEvent) => void>(() => undefined);
  keys.current = (e: KeyboardEvent) => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    const el = e.target as HTMLElement;
    if (el.closest("input, textarea, select, [contenteditable=true]") || String(window.getSelection())) return;
    const k = e.key.toLowerCase();
    if (k === "c" && highlight != null) {
      e.preventDefault();
      copy();
    } else if (k === "v" && clip != null && !busy) {
      e.preventDefault();
      paste();
    }
  };
  useEffect(() => {
    const on = (e: KeyboardEvent) => keys.current(e);
    const track = (e: PointerEvent) => { pointer.current = { x: e.clientX, y: e.clientY }; };
    window.addEventListener("keydown", on);
    window.addEventListener("pointermove", track);
    return () => {
      window.removeEventListener("keydown", on);
      window.removeEventListener("pointermove", track);
    };
  }, []);

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
      let sec = Math.round((view + ((ev.clientX - rect.left) / rect.width) * span) * 20) / 20;
      // ปัดทีละ 0.05 แล้วกันไม่ให้สั้นกว่า 0.2 (บวกกันทศนิยมคลาดนิดหน่อย)
      sec = edge === "start" ? Math.min(Math.max(0, sec), Math.round((d.end - 0.2) * 1000 - 1) / 1000)
        : Math.max(Math.min(limit, sec), Math.round((d.start + 0.2) * 1000 + 1) / 1000);
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
    <div ref={cardRef} className="card tight">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ fontSize: 15 }}>{tx("เลเยอร์เสียงตัวละคร")}</h2>
        <div className="row" style={{ gap: 8 }}>
          <div className="zoom" role="group" aria-label={tx("ซูมเส้นเวลา")}>
            <button type="button" className="icon-btn" onClick={() => step(-1)} disabled={zoom <= 1} aria-label={tx("ซูมออก")} title={tx("ซูมออก")}>−</button>
            <button type="button" className="zoom-level" onClick={() => zoomTo(1)} title={tx("แสดงทั้งคลิป")}>
              {zoom <= 1 ? tx("ทั้งคลิป") : `${Math.round(zoom * 10) / 10}×`}
            </button>
            <button type="button" className="icon-btn" onClick={() => step(1)} disabled={zoom >= ZOOMS[ZOOMS.length - 1]} aria-label={tx("ซูมเข้า")} title={tx("ซูมเข้า (Ctrl + ล้อเมาส์)")}>+</button>
          </div>
          <div className="seg small" role="group" aria-label={tx("เครื่องมือบนเส้นเวลา")}>
            <button type="button" aria-pressed={tool === "move"} onClick={() => setTool("move")} title={tx("คลิกเพื่อเลือก ลากเพื่อเลื่อนเวลาหรือย้ายตัวละคร")}>
              
              {tx("เลือก/ลาก")}
            </button>
            <button type="button" aria-pressed={tool === "cut"} onClick={() => setTool("cut")} title={tx("คลิกบนบล็อกตรงที่จะตัดแบ่งประโยค")}>
              <ScissorsIcon />  {tx("ตัด")}
            </button>
          </div>
          <button type="button" className="btn small" disabled={!!busy || !cutTarget}
            onClick={() => cutTarget && tr.splitAt(cutTarget, t)} title={tx("ตัดประโยคตรงตำแหน่งที่วิดีโอเล่นอยู่")}>
            
            {tx("ตัดที่หัวอ่าน")}
          </button>
          <div className="seg small" role="group" aria-label={tx("คัดลอกและวางประโยค")}>
            <button type="button" onClick={copy} disabled={highlight == null} title={tx("คัดลอกประโยคที่เลือก (Ctrl+C)")}>
              <CopyIcon />  {tx("คัดลอก")}
            </button>
            <button type="button" onClick={paste} disabled={clip == null || !!busy}
              title={tx("วางสำเนาให้ตัวละครอื่นที่เวลาเดิม (Ctrl+V ขณะชี้เลเยอร์ปลายทาง)")}>
              <PasteIcon />  {tx("วาง")}
            </button>
          </div>
        </div>
      </div>
      <div ref={lanesRef} className={`lanes${tool === "cut" ? " cutting" : ""}${zoom > 1 ? " zoomed" : ""}`}>
        <div className="lane ruler">
          <div className="who" />
          <div className={`track${onSeek ? " scrub" : ""}`} onPointerDown={scrub} title={onSeek ? tx("คลิกหรือลากเพื่อเลื่อนวิดีโอ") : undefined}
            role={onSeek ? "slider" : undefined} aria-label={tx("ตำแหน่งวิดีโอ")} aria-valuemin={0} aria-valuemax={Math.round(total)}
            aria-valuenow={Math.round(t)} tabIndex={onSeek ? 0 : -1}
            onKeyDown={(e) => {
              if (!onSeek) return;
              const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
              if (d) { e.preventDefault(); onSeek(Math.min(total, Math.max(0, t + d * (e.shiftKey ? 5 : 1)))); }
            }}>
            {tr.overlaps.spans.filter((o) => o.end > view && o.start < view + span).map((o) => (
              <span key={o.start} className="overlap-band" style={{ left: pct(o.start), width: width(o.end - o.start) }}
                title={tx("พูดซ้อน {0}–{1} เสียงพากย์จะเล่นทับกัน", { 0: fmtTime(o.start), 1: fmtTime(o.end) })} />
            ))}
            {ticks.map((x) => <span key={x} className="tick" style={{ left: pct(x) }}>{fmtTick(x)}</span>)}
            <div className="playhead" style={{ left: playheadPct }}><span className="playhead-knob" /></div>
          </div>
          {voiceHead ? <div className="lane-voice">{voiceHead}</div> : <span className="lane-voice lane-spacer" />}
          <span className="icon-btn lane-spacer"><XIcon /></span>
        </div>
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
                      aria-label={tx("ชื่อของ{0}", { 0: speakerLabel(s) })}
                      onChange={(e) => setNaming({ speaker: s, name: e.target.value })}
                      onBlur={finishNaming}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") finishNaming();
                        if (e.key === "Escape") setNaming(null);
                      }} />
                  ) : (
                    <button type="button" className="who-name" title={tx("คลิกเพื่อตั้งชื่อตัวละคร")}
                      onClick={() => setNaming({ speaker: s, name: tr.names[s] ?? "" })}>{speakerLabel(s)}</button>
                  )}
                </div>
                <div className="track" onPointerDown={pan}
                  onPointerMove={(e) => tool === "cut" && setGuide({ speaker: s, sec: secAt(e.clientX, e.currentTarget) })}
                  onPointerLeave={() => setGuide(null)}>
                  {own.map((u) => {
                    const d = tr.draftOf(u);
                    return (
                      <button key={u.id} type="button" className={`block${tr.overlaps.ids.has(u.id) ? " overlapped" : ""}`}
                        aria-label={`${speakerLabel(s)} ${fmtTime(d.start)}`} title={d.target}
                        onClick={click(u)} onPointerDown={press(u, s)}
                        style={{
                          left: pct(d.start),
                          width: width(d.end - d.start),
                          background: color,
                          opacity: highlight === u.id ? 1 : 0.45,
                          outline: clip === u.id ? "2px dashed #fff" : undefined,
                        }} />
                    );
                  })}
                  {own.filter((u) => u.id === highlight).map((u) => {
                    const d = tr.draftOf(u);
                    return [
                      <div key="s" className="handle" style={{ left: pct(d.start) }} onPointerDown={drag(u, "start")}
                        title={tx("ลากเพื่อเลื่อนเวลาเริ่ม")} aria-hidden="true" />,
                      <div key="e" className="handle" style={{ left: pct(d.end) }} onPointerDown={drag(u, "end")}
                        title={tx("ลากเพื่อเลื่อนเวลาจบ")} aria-hidden="true" />,
                    ];
                  })}
                  {tool === "cut" && guide?.speaker === s && <div className="cut-guide" style={{ left: pct(guide.sec) }} />}
                  <div className="playhead" style={{ left: playheadPct }} />
                </div>
                <div className="lane-voice">
                  {voiceSlot ? voiceSlot(s) : (
                    <a href={fileUrl.stem(job.id, s)} target="_blank" rel="noreferrer" className="dim" style={{ color: "var(--accent)" }}>{stemLabel}</a>
                  )}
                </div>
                <button type="button" className="icon-btn" aria-label={tx("ลบ{0}", { 0: speakerLabel(s) })} title={tx("ลบตัวละครนี้")}
                  disabled={!!busy || speakers.length < 2}
                  onClick={() => own.length ? setRemoving({ speaker: s, into: speakers.find((x) => x !== s) ?? "" })
                    : tr.removeSpeaker(s, "")}>
                  <XIcon />
                </button>
              </div>
              {removing?.speaker === s && (
                <div className="lane-remove">
                  <span>{tx("ลบ")}{speakerLabel(s)}  {tx("ย้าย")} {own.length}  {tx("ประโยคไปให้")}</span>
                  <label className="sr-only" htmlFor={`into-${s}`}>{tx("ตัวละครที่รับประโยคไป")}</label>
                  <select id={`into-${s}`} className="spk-select" value={removing.into}
                    onChange={(e) => setRemoving({ speaker: s, into: e.target.value })}>
                    {speakers.filter((x) => x !== s).map((x) => <option key={x} value={x}>{speakerLabel(x)}</option>)}
                  </select>
                  <button type="button" className="btn small danger"
                    onClick={() => { setRemoving(null); tr.removeSpeaker(s, removing.into); }}>{tx("ลบ")}</button>
                  <button type="button" className="btn small" onClick={() => setRemoving(null)}>{tx("ยกเลิก")}</button>
                </div>
              )}
            </div>
          );
        })}
      </div>
      {zoom > 1 && (
        <div className="lane" style={{ marginTop: -2 }}>
          <div className="who dim">{fmtTick(view)}–{fmtTick(view + span)}</div>
          <input type="range" className="timeline-scroll" min={0} max={Math.max(0, total - span)} step={0.05} value={view}
            onChange={(e) => setFrom(Number(e.target.value))} aria-label={tx("เลื่อนช่วงเวลาที่แสดง")} />
          <span className="lane-voice lane-spacer" />
          <span className="icon-btn lane-spacer"><XIcon /></span>
        </div>
      )}
      <span className="dim">{tx("ซูม: ปุ่ม +/− หรือ Ctrl + ล้อเมาส์ · เลื่อนช่วงเวลา: แถบเลื่อน, Shift + ล้อเมาส์ หรือลากที่ว่างบนแถบ · ลากบล็อกเพื่อเลื่อนเวลา หรือลากไปเลเยอร์อื่นเพื่อเปลี่ยนตัวละคร (วางซ้อนเวลากับตัวละครอื่นได้ เสียงจะพูดทับกัน) · เครื่องมือ “ตัด” คลิกตรงที่จะแบ่งประโยค · สองคนพูดพร้อมกัน: เลือกประโยคแล้วกด Ctrl+C ชี้เมาส์ที่เลเยอร์ตัวละครอีกคนแล้วกด Ctrl+V จะได้สำเนาซ้อนเวลาเดิม แล้วแก้บท · คนเดียวถูกแยกเป็นสองตัวละคร กด ✕ เพื่อรวม · คลิกชื่อตัวละครเพื่อตั้งชื่อ")}</span>
    </div>
  );
}
