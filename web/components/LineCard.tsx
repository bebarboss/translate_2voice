"use client";

import type { ReactNode, Ref } from "react";
import type { Utterance } from "@/lib/api";
import { fmtTime, speakerColor, speakerLabel } from "@/lib/format";
import { NEW_SPEAKER, type Transcript } from "@/lib/useTranscript";
import { MergeIcon, ScissorsIcon } from "./Icons";

/** แก้ประโยคเดียว: ตัวละคร บทพากย์ แยกประโยค รวมกับประโยคถัดไป */
export default function LineCard({ u, tr, isLast, active, speaking, tooLong, onSeek, onFocusText, boxRef, tools }: {
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
}) {
  const d = tr.draftOf(u);
  const changed = d.target !== u.target || d.speaker !== u.speaker;
  return (
    <div ref={boxRef} className={`line${active ? " active" : ""}${speaking ? " speaking" : ""}`}>
      <div className="row" style={{ gap: 8 }}>
        <button type="button" className="time-btn" onClick={() => onSeek(u.start)} aria-label={`ไปที่ ${fmtTime(u.start)}`}>
          {fmtTime(u.start)}
        </button>
        <span className="swatch" style={{ background: speakerColor(d.speaker, tr.speakers) }} />
        <label className="sr-only" htmlFor={`spk-${u.id}`}>ตัวละครของประโยคที่ {u.id}</label>
        <select id={`spk-${u.id}`} className="spk-select" value={d.speaker} disabled={tr.busy === "edit"}
          onChange={(e) => tr.changeSpeaker(u, e.target.value)}>
          {tr.speakers.map((s) => <option key={s} value={s}>{speakerLabel(s)}</option>)}
          <option value={NEW_SPEAKER}>+ ตัวละครใหม่</option>
        </select>
        <span style={{ marginLeft: "auto" }} className="row">
          {changed && <span className="badge awaiting_review">แก้แล้ว</span>}
          {tooLong && <span className="badge warn">ยาวเกินเวลา</span>}
        </span>
      </div>
      <p className="src">{u.source}</p>
      <label className="sr-only" htmlFor={`tg-${u.id}`}>บทพากย์ประโยคที่ {u.id}</label>
      <textarea id={`tg-${u.id}`} className="textarea" rows={2} value={d.target}
        onChange={(e) => tr.setDraft(u.id, { target: e.target.value })}
        onSelect={(e) => { tr.cursors.current[u.id] = e.currentTarget.selectionStart; }}
        onFocus={onFocusText} />
      <div className="line-tools">
        {tools}
        <button type="button" className="icon-btn" onClick={() => tr.split(u)} disabled={!!tr.busy}
          title="แยกตรงเคอร์เซอร์ในบท หรือตรงเวลาที่หยุดวิดีโอไว้">
          <ScissorsIcon />แยกประโยค
        </button>
        <button type="button" className="icon-btn" onClick={() => tr.merge(u)}
          disabled={!!tr.busy || isLast} title="รวมกับประโยคถัดไป">
          <MergeIcon />รวมกับถัดไป
        </button>
      </div>
    </div>
  );
}
