"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, uploadTimeline, type Entitlements, type TargetLang } from "@/lib/api";
import { GENRES, LANGS, TARGET_LABEL } from "@/lib/format";
import { ArrowRight, UploadIcon } from "@/components/Icons";

import { tx } from "@/lib/i18n";
const TIMELINE_EXT = [".xml", ".fcpxml", ".edl", ".otio", ".zip"];
const FPS = [23.976, 24, 25, 29.97, 30, 50, 59.94, 60];

/** นำเข้าไทม์ไลน์จาก Premiere Pro / DaVinci Resolve / Final Cut Pro แล้วไปหน้าตั้งค่าแทร็ก */
export default function TimelineImportPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [fps, setFps] = useState("");
  const [sourceLang, setSourceLang] = useState("");
  const [targetLang, setTargetLang] = useState<TargetLang>("th");
  const [genre, setGenre] = useState("");
  const [glossary, setGlossary] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [ent, setEnt] = useState<Entitlements | null | undefined>(undefined);
  const abortRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    api.wallet().then((w) => setEnt(w.entitlements ?? null)).catch(() => setEnt(null));
  }, []);
  // รอโหลดสิทธิ์ก่อน — กันเผลออัปโหลดตอนยังไม่รู้แพ็ก / ไม่มีแพ็ก
  const locked = ent === undefined || (ent != null && !ent.timeline && ent.plan_id !== "admin");

  const pick = (f: File | undefined | null) => {
    setError("");
    if (!f) return;
    if (!TIMELINE_EXT.includes(f.name.slice(f.name.lastIndexOf(".")).toLowerCase())) {
      setError(tx("รองรับไฟล์ไทม์ไลน์ .xml (Premiere / Resolve), .fcpxml, .edl, .otio หรือ .zip ที่มีไทม์ไลน์กับไฟล์สื่อ"));
      return;
    }
    setFile(f);
  };
  const isEdl = !!file && file.name.toLowerCase().endsWith(".edl");

  const submit = async () => {
    if (!file || busy) return;
    setBusy(true); setError(""); setProgress(0);
    try {
      const up = uploadTimeline(file, [], {
        fps: fps ? Number(fps) : null, sourceLang, targetLang, genre: genre.trim(), glossary: glossary.trim(), review: true,
      }, setProgress);
      abortRef.current = up.abort;
      const { job } = await up.promise;
      router.push(`/jobs/${job.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
      setProgress(null);
    } finally {
      abortRef.current = null;
    }
  };

  if (locked) {
    return (
      <main className="page narrow">
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 600 }}>{tx("นำเข้าไทม์ไลน์")}</h1>
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <p className="muted" style={{ margin: 0 }}>
            {tx("ฟีเจอร์นี้ใช้ได้เฉพาะแพ็กเกจมือโปร แพ็กเกจปัจจุบันล็อกไว้")}
          </p>
          <Link href="/promotions" className="btn primary">{tx("อัปเกรดแพ็กเกจ")}</Link>
        </div>
      </main>
    );
  }

  return (
    <main className="page">
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 600 }}>{tx("นำเข้าไทม์ไลน์จากโปรแกรมตัดต่อ")}</h1>
        <p className="muted" style={{ margin: 0 }}>
          
          {tx("ส่งไทม์ไลน์ที่แยกเสียงแต่ละคนไว้คนละแทร็ก ระบบถอดเสียง แปล แล้วพาไปหน้าตรวจบทก่อนพากย์ — แก้บทได้เหมือนงานคลิปปกติ แล้วส่งกลับเป็น XML / FCPXML พร้อมเสียงแยกแทร็ก 48 kHz")}
        </p>
      </div>

      <label className={`dropzone${drag ? " drag" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}>
        <span className="icon"><UploadIcon color="#FF8A4C" /></span>
        {file ? (
          <>
            <span style={{ fontSize: 18, fontWeight: 500 }}>{file.name}</span>
            <span className="muted">{(file.size / 1024 / 1024).toFixed(1)}  {tx("MB · คลิกเพื่อเปลี่ยนไฟล์")}</span>
          </>
        ) : (
          <>
            <span style={{ fontSize: 20, fontWeight: 500 }}>{tx("ลากไฟล์ไทม์ไลน์มาวางที่นี่")}</span>
            <span className="muted">Premiere: File › Export › Final Cut Pro XML · Resolve: File › Export › Timeline (FCPXML / XML / EDL)</span>
            <span className="dim">{tx(".xml .fcpxml .edl .otio หรือ .zip ที่รวมไทม์ไลน์กับไฟล์เสียงไว้แล้ว")}</span>
          </>
        )}
        <input type="file" accept={TIMELINE_EXT.join(",")} aria-label={tx("เลือกไฟล์ไทม์ไลน์")} disabled={busy}
          onChange={(e) => pick(e.target.files?.[0])} />
      </label>

      <section className="grid-3" aria-label={tx("ตั้งค่างาน")}>
        <div className="card tight field">
          <label htmlFor="src">{tx("ภาษาต้นฉบับ")}</label>
          <select id="src" className="select" value={sourceLang} onChange={(e) => setSourceLang(e.target.value)}>
            <option value="">{tx("ตรวจอัตโนมัติ")}</option>
            {LANGS.map((l) => <option key={l.code} value={l.code}>{tx(l.label)}</option>)}
          </select>
        </div>
        <div className="card tight field">
          <span className="label">{tx("พากย์เป็นภาษา")}</span>
          <div className="seg" role="group" aria-label={tx("ภาษาพากย์")}>
            {(["th", "en"] as TargetLang[]).map((t) => (
              <button key={t} type="button" aria-pressed={targetLang === t} onClick={() => setTargetLang(t)}>{tx(TARGET_LABEL[t])}</button>
            ))}
          </div>
        </div>
        <div className="card tight field">
          <label htmlFor="fps">{tx("อัตราเฟรม")}{isEdl ? tx(" (จำเป็นสำหรับ EDL)") : ""}</label>
          <select id="fps" className="select" value={fps} onChange={(e) => setFps(e.target.value)}>
            <option value="">{isEdl ? tx("เลือกอัตราเฟรม") : tx("ตามไฟล์ไทม์ไลน์")}</option>
            {FPS.map((f) => <option key={f} value={f}>{f} fps</option>)}
          </select>
        </div>
        <div className="card tight field">
          <label htmlFor="genre">{tx("แนวเรื่อง (ถ้ารู้)")}</label>
          <input id="genre" className="input" list="genres" maxLength={80} value={genre} onChange={(e) => setGenre(e.target.value)} />
          <datalist id="genres">{GENRES.map((g) => <option key={g} value={tx(g)} />)}</datalist>
        </div>
      </section>

      <details className="card tight retranslate">
        <summary>{tx("ชื่อเฉพาะ")} <span className="dim">{tx("ไม่ใส่ก็ได้ ช่วยให้ชื่อตัวละครและสถานที่สะกดตรงกับฉบับไทย")}</span></summary>
        <label className="sr-only" htmlFor="glossary">{tx("ชื่อเฉพาะ บรรทัดละคำ")}</label>
        <textarea id="glossary" className="textarea" rows={4} maxLength={2000} placeholder={tx("บรรทัดละคำ เช่น\nJohn = จอห์น")}
          value={glossary} onChange={(e) => setGlossary(e.target.value)} />
      </details>

      {error && <div className="alert error" role="alert">{error}</div>}

      <div className="row" style={{ justifyContent: "space-between" }}>
        {progress !== null ? (
          <div style={{ flex: "1 1 260px", display: "flex", alignItems: "center", gap: 12 }}>
            <div className="progress" style={{ flex: 1 }}><div style={{ width: `${progress * 100}%` }} /></div>
            <span className="mono">{Math.round(progress * 100)}%</span>
            <button type="button" className="btn small" onClick={() => abortRef.current?.()}>{tx("ยกเลิก")}</button>
          </div>
        ) : <span />}
        <button type="button" className="btn primary lg" onClick={submit} disabled={!file || busy || (isEdl && !fps)}>
          {busy ? tx("กำลังอัปโหลด...") : tx("นำเข้าไทม์ไลน์")}{!busy && <ArrowRight />}
        </button>
      </div>
    </main>
  );
}
