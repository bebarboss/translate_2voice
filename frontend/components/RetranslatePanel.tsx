"use client";

import { useState } from "react";
import { api, type Job } from "@/lib/api";
import { GENRES } from "@/lib/format";
import { tx } from "@/lib/i18n";

const GENDER: Record<string, string> = { male: "ชาย", female: "หญิง" };

/** บริบทเรื่องที่ AI วิเคราะห์จากบททั้งเรื่อง (แนวเรื่อง ระดับภาษา ตัวละคร ชื่อเฉพาะ จุดที่น่าจะถอดผิด)
 * และแปลบทใหม่ทั้งเรื่องด้วยแนวเรื่อง คำเฉพาะ และชื่อตัวละครที่แก้ไว้ (ค่าเริ่มต้นมาจากผลวิเคราะห์) */
export default function RetranslatePanel({ job, names, onStarted, onJump, speakerOf, onSpeaker, label }: {
  job: Job;
  names: Record<string, string>;
  onStarted: () => void;
  onJump?: (lineId: number) => void;
  /** ผู้พูดตอนนี้ของบรรทัด กับเปลี่ยนผู้พูด (ปุ่มรับข้อเสนอ "อาจผิดตัวละคร") */
  speakerOf?: (lineId: number) => string | undefined;
  onSpeaker?: (lineId: number, speaker: string) => void;
  label?: (speaker: string) => string;
}) {
  const story = job.story;
  const [genre, setGenre] = useState(job.genre || (story ? [story.genre, story.setting].filter(Boolean).join(" · ") : ""));
  const [glossary, setGlossary] = useState(job.glossary || (story?.glossary ?? []).join("\n"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const named = Object.values(names).filter(Boolean);
  const issues = [
    ...(story?.asr_fixes ?? []).map((x) => ({ id: x.id, kind: tx("อาจถอดเสียงผิด"), text: x.likely, speaker: "" })),
    ...(story?.speaker_doubts ?? []).map((x) => ({ id: x.id, kind: tx("อาจผิดตัวละคร"), text: x.note, speaker: x.speaker ?? "" })),
  ].sort((a, b) => a.id - b.id);
  const name = (s: string) => label?.(s) || names[s] || s;

  const start = async () => {
    if (!window.confirm(tx("แปลบทใหม่ทั้งเรื่อง? บทที่แก้เองไว้จะถูกแทนด้วยคำแปลใหม่ (ตัวละคร เวลา และอารมณ์ของแต่ละประโยคคงเดิม)"))) return;
    setBusy(true);
    setError("");
    try {
      await api.retranslate(job.id, { genre: genre.trim(), glossary: glossary.trim() });
      onStarted();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <details className="card tight retranslate">
      <summary>
        {story ? tx("บริบทเรื่องและแปลใหม่") : tx("แปลใหม่ทั้งเรื่อง")}{" "}
        <span className="dim">
          {story?.genre ? story.genre : tx("ใช้แนวเรื่อง ชื่อเฉพาะ และชื่อตัวละคร ช่วยให้สรรพนามและชื่อถูกต้อง")}
        </span>
        {issues.length > 0 && <span className="badge warn">{tx("ควรตรวจ {0} จุด", { 0: issues.length })}</span>}
      </summary>

      {story && (
        <div className="story">
          <span className="dim">{tx("AI อ่านบทต้นฉบับทั้งเรื่องแล้วสรุปไว้ให้ผู้แปลใช้ เป็นการเดาจากบท ตรวจและแก้ได้ด้านล่าง")}</span>
          {story.content_type && <div><b>{tx("ประเภทคลิป")}</b> <span className="muted">{tx(story.content_type === "teaser" ? "ทีเซอร์-รวมฉาก" : "เรื่องต่อเนื่อง")}</span></div>}
          {story.register && <div><b>{tx("ระดับภาษา")}</b> <span className="muted">{story.register}</span></div>}
          {story.characters.length > 0 && (
            <div className="story-chars">
              {story.characters.map((c) => (
                <div key={c.speaker} className="story-char">
                  <b>{names[c.speaker] || c.name || c.speaker}</b>
                  <span className="dim">{[c.gender && tx(GENDER[c.gender]), c.role].filter(Boolean).join(" · ")}</span>
                  {(c.self || c.addresses) && (
                    <span className="dim">{[c.self && tx("แทนตัวว่า {0}", { 0: c.self }), c.addresses && tx("เรียกคนอื่นว่า {0}", { 0: c.addresses })].filter(Boolean).join(" · ")}</span>
                  )}
                </div>
              ))}
            </div>
          )}
          {issues.length > 0 && (
            <div className="story-issues">
              <b>{tx("จุดที่ควรตรวจ")}</b>
              {issues.map((x, i) => (
                <div key={`${x.id}-${i}`} className="row" style={{ gap: 8, flexWrap: "nowrap", alignItems: "flex-start" }}>
                  <button type="button" className="time-btn" onClick={() => onJump?.(x.id)} title={tx("ไปที่ประโยคนี้")}>#{x.id}</button>
                  <span className="badge warn">{x.kind}</span>
                  <span className="muted" style={{ fontSize: 14, flex: 1 }}>{x.text}</span>
                  {x.speaker && onSpeaker && (speakerOf?.(x.id) === x.speaker
                    ? <span className="badge done">{tx("✓ เปลี่ยนแล้ว")}</span>
                    : speakerOf?.(x.id) !== undefined && (
                      <button type="button" className="btn small" style={{ whiteSpace: "nowrap" }} onClick={() => onSpeaker(x.id, x.speaker)}>
                        {tx("เปลี่ยนเป็น {0}", { 0: name(x.speaker) })}
                      </button>
                    ))}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="grid-2">
        <div className="field">
          <label htmlFor="rt-genre">{tx("แนวเรื่อง")}</label>
          <input id="rt-genre" className="input" list="rt-genres" maxLength={80} placeholder={tx("เช่น การ์ตูนเด็ก")}
            value={genre} onChange={(e) => setGenre(e.target.value)} />
          <datalist id="rt-genres">{GENRES.map((g) => <option key={g} value={tx(g)} />)}</datalist>
          <span className="dim">
            {named.length ? tx("ชื่อตัวละครที่ตั้งไว้: {0}", { 0: named.join(", ") }) : tx("ตั้งชื่อตัวละครในเลเยอร์เสียงก่อน AI จะเลือกสรรพนามให้เข้ากับคนพูดได้ดีขึ้น")}
          </span>
        </div>
        <div className="field">
          <label htmlFor="rt-glossary">{tx("ชื่อเฉพาะ (บรรทัดละคำ)")}</label>
          <textarea id="rt-glossary" className="textarea" rows={4} maxLength={2000}
            placeholder={tx("ドラえもん = โดราเอมอน\nのび太 = โนบิตะ")} value={glossary} onChange={(e) => setGlossary(e.target.value)} />
        </div>
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      <button type="button" className="btn small primary" style={{ alignSelf: "flex-start" }} onClick={start} disabled={busy}>
        {busy ? tx("กำลังส่ง...") : tx("แปลใหม่")}
      </button>
    </details>
  );
}
