"use client";

import type { ReactNode, Ref } from "react";
import type { Utterance } from "@/lib/api";
import { MOOD_LABEL, fmtTime, speakerColor } from "@/lib/format";
import { NEW_SPEAKER, isChanged, type Transcript } from "@/lib/useTranscript";
import { ArrowLeft, MergeIcon, ScissorsIcon, ShuffleIcon, TrashIcon } from "./Icons";

import { tx } from "@/lib/i18n";
/** แก้ประโยคเดียว: ตัวละคร บทพากย์ แยกประโยค รวมกับประโยคถัดไป */
export default function LineCard({ u, tr, isLast, active, speaking, tooLong, onSeek, onFocusText, boxRef, tools, retake }: {
  u: Utterance;
  tr: Transcript;
  isLast: boolean;
  active?: boolean;
  speaking?: boolean;
  tooLong?: boolean;
  onSeek: (sec: number) => void;
  onFocusText?: () => void;
  boxRef?: Ref<HTMLDivElement>;
  tools?: ReactNode; // ปุ่มเพิ่มของแต่ละหน้า (เช่น เล่นช่วงนี้)
  retake?: boolean; // แสดงปุ่มสุ่มเสียงพากย์ใหม่ (หลังพากย์แล้ว)
}) {
  const d = tr.draftOf(u);
  const changed = isChanged(u, d);
  const retimed = d.start !== u.start || d.end !== u.end;
  // อารมณ์เลือกได้เมื่อตัวละครใช้เสียงในคลังที่มีเสียงอารมณ์อื่น (อารมณ์ที่เลือกไว้แต่ถูกลบไปแล้วยังแสดงให้เปลี่ยนกลับได้)
  const moods = tr.moodsOf(d.speaker);
  const showMood = moods.length > 0 || (!!d.mood && d.mood !== "normal");
  // อารมณ์ที่ระบบเลือกไว้ตอนพากย์รอบล่าสุด (แสดงเมื่อบทยังเหมือนตอนที่เลือก)
  const auto = u.mood_auto && u.mood_auto_text === d.target ? u.mood_auto : "";
  // ช่องเวลา: ปัดทีละ 0.05 วินาที ไม่ให้สั้นกว่า 0.2 วินาที
  const setTime = (key: "start" | "end", raw: string) => {
    const v = Math.round(Number(raw) * 20) / 20;
    if (!Number.isFinite(v) || v < 0) return;
    if (key === "start" ? v > d.end - 0.2 : v < d.start + 0.2) return;
    tr.setDraft(u.id, { [key]: v });
  };
  return (
    <div ref={boxRef} className={`line${active ? " active" : ""}${speaking ? " speaking" : ""}`}>
      <div className="row" style={{ gap: 8 }}>
        <button type="button" className="time-btn" onClick={() => onSeek(u.start)} aria-label={tx("ไปที่ {0}", { 0: fmtTime(u.start) })}>
          {fmtTime(u.start)}
        </button>
        <span className="swatch" style={{ background: speakerColor(d.speaker, tr.speakers) }} />
        <label className="sr-only" htmlFor={`spk-${u.id}`}>{tx("ตัวละครของประโยคที่")} {u.id}</label>
        <select id={`spk-${u.id}`} className="spk-select" value={d.speaker} disabled={tr.busy === "edit"}
          onChange={(e) => tr.changeSpeaker(u, e.target.value)}>
          {tr.speakers.map((s) => <option key={s} value={s}>{tr.label(s)}</option>)}
          <option value={NEW_SPEAKER}>{tx("+ ตัวละครใหม่")}</option>
        </select>
        {showMood && (
          <>
            <label className="sr-only" htmlFor={`mood-${u.id}`}>{tx("อารมณ์ของประโยคที่")} {u.id}</label>
            <select id={`mood-${u.id}`} className="spk-select" value={d.mood}
              title={tx("อัตโนมัติ: ระบบเลือกอารมณ์จากบทและน้ำเสียงต้นฉบับตอนพากย์ หรือเลือกเองเพื่อใช้เสียงตัวอย่างอารมณ์นั้นของเสียงในคลัง")}
              onChange={(e) => tr.setDraft(u.id, { mood: e.target.value as typeof d.mood })}>
              <option value="">{auto ? tx("อัตโนมัติ · {0}", { 0: MOOD_LABEL[auto] }) : tx("อารมณ์อัตโนมัติ")}</option>
              <option value="normal">{tx("อารมณ์ปกติ")}</option>
              {moods.map((m) => <option key={m} value={m}>{tx(MOOD_LABEL[m])}</option>)}
              {d.mood && d.mood !== "normal" && !moods.includes(d.mood) && <option value={d.mood}>{tx(MOOD_LABEL[d.mood])}  {tx("(ไม่มีในเสียงนี้ ใช้เสียงปกติ)")}</option>}
            </select>
          </>
        )}
        <span style={{ marginLeft: "auto" }} className="row">
          {d.take > 0 && <span className="badge" style={{ background: "var(--surface-2)", color: "var(--text-2)" }}>{tx("เสียงรอบที่")} {d.take + 1}</span>}
          {tr.overlaps.ids.has(u.id) && <span className="badge overlap" title={tx("ตัวละครอื่นพูดพร้อมกันในช่วงนี้ เสียงพากย์จะเล่นทับกัน")}>{tx("พูดซ้อน")}</span>}
          {changed && <span className="badge awaiting_review">{tx("แก้แล้ว")}</span>}
          {tooLong && <span className="badge warn">{tx("ยาวเกินเวลา")}</span>}
          {u.unclear && (
            <span className="badge warn" title={u.unclear_reason || tx("เพลงดังทับเสียงพูด ถอดเสียงสองรอบแล้วยังไม่มั่นใจ ฟังต้นฉบับแล้วแก้ข้อความถ้าผิด")}>{tx("ถอดไม่ชัด ควรฟัง")}</span>
          )}
          {!!u.check_note && !changed && <span className="badge warn" title={u.check_note}>{tx("ควรตรวจ")}</span>}
          {!!u.unclear_reason && !u.unclear && !u.check_note && (
            <span className="badge warn" title={u.unclear_reason}>{tx("ควรตรวจ")}</span>
          )}
          {!!u.heard && !changed && (
            <span className="badge warn" title={tx("ระบบฟังเสียงพากย์แล้วได้ยินว่า: {0}", { 0: u.heard })}>{tx("ควรฟัง")}</span>
          )}
        </span>
      </div>
      <p className="src">{u.source}</p>
      <div className="row time-range" style={{ gap: 6 }}>
        <label htmlFor={`st-${u.id}`}>{tx("เริ่ม")}</label>
        <input id={`st-${u.id}`} type="number" step={0.05} min={0} value={d.start}
          onChange={(e) => setTime("start", e.target.value)} />
        <label htmlFor={`en-${u.id}`}>{tx("จบ")}</label>
        <input id={`en-${u.id}`} type="number" step={0.05} min={0} value={d.end}
          onChange={(e) => setTime("end", e.target.value)} />
        <span className="dim">{tx("วิ · ยาว")} {(d.end - d.start).toFixed(2)}  {tx("วิ")}</span>
        {retimed && (
          <button type="button" className="icon-btn" onClick={() => tr.setDraft(u.id, { start: u.start, end: u.end })}>
            
            {tx("คืนเวลาเดิม")}
          </button>
        )}
      </div>
      <label className="sr-only" htmlFor={`tg-${u.id}`}>{tx("บทพากย์ประโยคที่")} {u.id}</label>
      <textarea id={`tg-${u.id}`} className="textarea" rows={2} value={d.target}
        title={tx("/ คือจุดหยุดหายใจตามต้นฉบับ เสียงพากย์จะเว้นตรงนั้น ลบหรือย้ายได้")}
        onChange={(e) => tr.setDraft(u.id, { target: e.target.value })}
        onSelect={(e) => { tr.cursors.current[u.id] = e.currentTarget.selectionStart; }}
        onFocus={onFocusText} />
      <div className="line-tools">
        {tools}
        {retake && (
          <>
            {d.take > 0 && (
              <button type="button" className="icon-btn" onClick={() => tr.setDraft(u.id, { take: d.take - 1 })}
                title={tx("กลับไปใช้เสียงพากย์รอบก่อน (ใช้เสียงที่เก็บไว้ ไม่ต้องพากย์ซ้ำ)")}>
                <ArrowLeft size={13} />{tx("รอบก่อน")}
              </button>
            )}
            <button type="button" className="icon-btn" onClick={() => tr.setDraft(u.id, { take: d.take + 1 })}
              title={tx("ให้ระบบพากย์ประโยคนี้ใหม่ ได้น้ำเสียงหรือการออกเสียงแบบใหม่ บทเหมือนเดิม")}>
              <ShuffleIcon />{tx("สุ่มเสียงใหม่")}
            </button>
          </>
        )}
        <button type="button" className="icon-btn" onClick={() => tr.split(u)} disabled={!!tr.busy}
          title={tx("แยกตรงเคอร์เซอร์ในบท หรือตรงเวลาที่หยุดวิดีโอไว้")}>
          <ScissorsIcon />{tx("แยกประโยค")}
        </button>
        <button type="button" className="icon-btn" onClick={() => tr.merge(u)}
          disabled={!!tr.busy || isLast} title={tx("รวมกับประโยคถัดไป")}>
          <MergeIcon />{tx("รวมกับถัดไป")}
        </button>
        <button type="button" className="icon-btn" disabled={!!tr.busy} title={tx("ลบประโยคนี้ ช่วงนั้นจะไม่มีเสียงพากย์")}
          onClick={() => window.confirm(tx("ลบประโยคนี้? ช่วงนั้นจะไม่มีเสียงพากย์")) && tr.removeLine(u)}>
          <TrashIcon />{tx("ลบ")}
        </button>
      </div>
    </div>
  );
}
