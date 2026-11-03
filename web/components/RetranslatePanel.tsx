"use client";

import { useState } from "react";
import { api, type Job } from "@/lib/api";
import { GENRES } from "@/lib/format";

import { tx } from "@/lib/i18n";
/** แปลบทใหม่ทั้งเรื่องจากบทถอดเสียงเดิม ใช้แนวเรื่อง คำเฉพาะ และชื่อตัวละครที่ตั้งไว้ */
export default function RetranslatePanel({ job, names, onStarted }: {
  job: Job;
  names: Record<string, string>;
  onStarted: () => void;
}) {
  const [genre, setGenre] = useState(job.genre ?? "");
  const [glossary, setGlossary] = useState(job.glossary ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const named = Object.values(names).filter(Boolean);

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
      <summary>{tx("แปลใหม่ทั้งเรื่อง")} <span className="dim">{tx("ใช้แนวเรื่อง ชื่อเฉพาะ และชื่อตัวละคร ช่วยให้สรรพนามและชื่อถูกต้อง")}</span></summary>
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
