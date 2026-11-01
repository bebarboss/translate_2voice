"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fileUrl, type LibraryVoice, type SpeakerVoice } from "@/lib/api";
import { GENDER_LABEL } from "@/lib/format";
import { XIcon } from "./Icons";
import VoiceAvatar from "./VoiceAvatar";
import { PreviewButton, usePreview } from "./VoicePreview";

/** แถบเลือกเสียงจากคลังที่สไลด์ออกมาจากขวา เรียงตามความใกล้เคียงกับเสียงตัวละคร ค้นหาและกรองหมวดได้
 *  voiceId null = เลียนเสียงนักแสดงต้นฉบับ */
export default function VoicePicker({ cast, label, color, stemUrl, voices, selected, onPick, onClose }: {
  cast: SpeakerVoice;
  label: string;
  color: string;
  stemUrl: string;
  voices: Record<string, LibraryVoice>;
  selected: string | null;
  onPick: (voiceId: string | null) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const preview = usePreview();
  const searchRef = useRef<HTMLInputElement>(null);

  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    searchRef.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, []);

  // เสียงที่มีคะแนนความใกล้เคียงเรียงก่อน (มากไปน้อย) เสียงที่วัดไม่ได้ต่อท้ายตามชื่อ
  const score = useMemo(() => Object.fromEntries(cast.suggestions.map((s) => [s.voice_id, s.score])), [cast]);
  const ranked = useMemo(() => Object.values(voices).sort((a, b) =>
    (score[b.id] ?? -1) - (score[a.id] ?? -1) || a.name.localeCompare(b.name, "th")), [voices, score]);
  const topId = cast.suggestions.find((s) => voices[s.voice_id])?.voice_id;
  const categories = [...new Set(ranked.flatMap((v) => v.categories ?? []))];

  const q = query.trim().toLowerCase();
  const shown = ranked.filter((v) => (!category || (v.categories ?? []).includes(category)) && (!q || [
    v.name, v.tone, v.description, v.gender && GENDER_LABEL[v.gender], ...(v.categories ?? []),
  ].some((x) => x && x.toLowerCase().includes(q))));

  const pick = (id: string | null) => {
    onPick(id);
    onClose();
  };

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="picker-title" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
            <h2 id="picker-title" className="row" style={{ gap: 8, fontSize: 17 }}>
              <span className="swatch" style={{ background: color }} />เลือกเสียงให้{label}
            </h2>
            <span className="dim">
              {cast.gender ? `น่าจะ${GENDER_LABEL[cast.gender]}` : "วัดเสียงไม่ได้"}{cast.pitch_hz ? ` · ${Math.round(cast.pitch_hz)} Hz` : ""}
              {" "}· เรียงตามความใกล้เคียงกับเสียงตัวละคร
            </span>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="ปิด"><XIcon /></button>
        </div>

        <div className="drawer-tools">
          <PreviewButton url={stemUrl} playing={preview.playing} onToggle={preview.toggle} label="ฟังเสียงตัวละคร" />
          <input ref={searchRef} className="input" type="search" placeholder="ค้นหาชื่อ โทน หมวด รายละเอียด"
            aria-label="ค้นหาเสียง" value={query} onChange={(e) => setQuery(e.target.value)} />
          {categories.length > 0 && (
            <div className="chips" role="group" aria-label="กรองตามหมวดหมู่">
              <button type="button" className="chip" aria-pressed={!category} onClick={() => setCategory("")}>ทั้งหมด</button>
              {categories.map((c) => (
                <button key={c} type="button" className="chip" aria-pressed={category === c} onClick={() => setCategory(c)}>{c}</button>
              ))}
            </div>
          )}
        </div>

        <ul className="pick-list" aria-label="เสียงในคลัง">
          {!q && !category && (
            <li className="pick-row">
              <button type="button" className="pick" aria-pressed={selected === null} onClick={() => pick(null)}>
                <span className="avatar" style={{ width: 44, height: 44, fontSize: 18 }} aria-hidden="true">🎭</span>
                <span className="pick-main">
                  <span className="pick-name">เสียงต้นฉบับ</span>
                  <span className="dim">เลียนเสียงนักแสดงในคลิป ไม่ใช้เสียงในคลัง</span>
                </span>
                {selected === null && <span className="badge done">ใช้อยู่</span>}
              </button>
            </li>
          )}
          {shown.map((v) => {
            const s = score[v.id];
            return (
              <li key={v.id} className="pick-row">
                <button type="button" className="pick" aria-pressed={selected === v.id} onClick={() => pick(v.id)}>
                  <VoiceAvatar name={v.name} url={v.image ? fileUrl.voiceImage(v.id, v.updated_at) : ""} size={44} />
                  <span className="pick-main">
                    <span className="pick-name">{v.name}</span>
                    <span className="row" style={{ gap: 4 }}>
                      {v.id === topId && <span className="badge awaiting_review">★ แนะนำ</span>}
                      {v.gender && <span className="badge queued">{GENDER_LABEL[v.gender]}</span>}
                      {v.tone && <span className="badge queued">{v.tone}</span>}
                      {(v.categories ?? []).map((c) => <span key={c} className="badge category">{c}</span>)}
                    </span>
                    {v.description && <span className="dim pick-desc">{v.description}</span>}
                  </span>
                  <span className="pick-score" title="ความใกล้เคียงกับเสียงตัวละคร (ระดับเสียงและเนื้อเสียง)">
                    {s != null ? (
                      <>
                        <span className="mono">{Math.round(s * 100)}%</span>
                        <span className="meter"><span style={{ width: `${Math.round(s * 100)}%` }} /></span>
                      </>
                    ) : <span className="dim">วัดไม่ได้</span>}
                    {selected === v.id && <span className="badge done">ใช้อยู่</span>}
                  </span>
                </button>
                <PreviewButton url={fileUrl.voice(v.id, v.updated_at)} playing={preview.playing} onToggle={preview.toggle} label="ฟัง" />
              </li>
            );
          })}
          {shown.length === 0 && <li className="empty">ไม่พบเสียงที่ตรงกับคำค้น</li>}
        </ul>
      </aside>
    </div>
  );
}
