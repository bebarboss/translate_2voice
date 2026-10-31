"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, uploadJob, type CreateOptions, type Job, type TargetLang } from "@/lib/api";
import { LANGS, TARGET_LABEL, langName } from "@/lib/format";
import StatusBadge from "@/components/StatusBadge";
import { ArrowRight, LinkIcon, UploadIcon } from "@/components/Icons";

const ACCEPT = ".mp4,.mov,.mkv,.webm,.avi,.m4v";

export default function UploadPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"file" | "url">("file");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [drag, setDrag] = useState(false);
  const [sourceLang, setSourceLang] = useState("");
  const [targetLang, setTargetLang] = useState<TargetLang>("th");
  const [speakers, setSpeakers] = useState("");
  const [review, setReview] = useState(true);
  const [burnSubs, setBurnSubs] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState<Job[] | null>(null);
  const abortRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    api.getSettings().then((s) => {
      setTargetLang(s.default_target_lang);
      setReview(s.default_review);
      setBurnSubs(s.default_burn_subs);
    }).catch(() => { /* ใช้ค่าเริ่มต้นในหน้าเว็บ */ });
    api.listJobs().then((j) => setRecent(j.slice(0, 5))).catch(() => setRecent([]));
  }, []);

  const pickFile = (f: File | undefined | null) => {
    setError("");
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPT.split(",").includes(ext)) {
      setError("รองรับเฉพาะไฟล์ MP4, MOV, MKV, WEBM, AVI, M4V");
      return;
    }
    setFile(f);
  };

  const ready = mode === "file" ? !!file : /^https?:\/\/\S+$/i.test(url.trim());

  const submit = async () => {
    if (!ready || busy) return;
    setError("");
    setBusy(true);
    const opts: CreateOptions = {
      sourceLang, targetLang, review, burnSubs,
      numSpeakers: speakers ? Number(speakers) : null,
    };
    try {
      let id: string;
      if (mode === "file" && file) {
        setProgress(0);
        const up = uploadJob(file, opts, setProgress);
        abortRef.current = up.abort;
        id = (await up.promise).id;
      } else {
        id = (await api.createFromUrl(url.trim(), opts)).id;
      }
      router.push(`/jobs/${id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
      setProgress(null);
    } finally {
      abortRef.current = null;
    }
  };

  return (
    <main className="page">
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h1 style={{ margin: 0, fontSize: 32, fontWeight: 600, lineHeight: 1.25 }}>พากย์คลิปด้วยเสียงนักแสดงต้นฉบับ</h1>
        <p className="muted" style={{ margin: 0, fontSize: 16 }}>
          ส่งคลิปละครภาษาใดก็ได้ ระบบจะแยกเสียงตัวละคร แปล แล้วให้คุณตรวจบทก่อนพากย์
        </p>
      </div>

      <div className="seg" role="group" aria-label="วิธีส่งคลิป" style={{ alignSelf: "flex-start" }}>
        <button type="button" aria-pressed={mode === "file"} onClick={() => setMode("file")}>อัปโหลดไฟล์</button>
        <button type="button" aria-pressed={mode === "url"} onClick={() => setMode("url")}>วางลิงก์</button>
      </div>

      {mode === "file" ? (
        <label
          className={`dropzone${drag ? " drag" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); pickFile(e.dataTransfer.files[0]); }}
        >
          <span className="icon"><UploadIcon color="#FF8A4C" /></span>
          {file ? (
            <>
              <span style={{ fontSize: 18, fontWeight: 500 }}>{file.name}</span>
              <span className="muted">{(file.size / 1024 / 1024).toFixed(1)} MB · คลิกเพื่อเปลี่ยนไฟล์</span>
            </>
          ) : (
            <>
              <span style={{ fontSize: 20, fontWeight: 500 }}>ลากคลิปมาวางที่นี่</span>
              <span className="muted">หรือ <span style={{ color: "var(--accent)", textDecoration: "underline" }}>เลือกไฟล์จากเครื่อง</span></span>
              <span className="dim">MP4, MOV, MKV, WEBM · ไม่เกิน 500 MB</span>
            </>
          )}
          <input type="file" accept={ACCEPT} aria-label="เลือกไฟล์วิดีโอ" onChange={(e) => pickFile(e.target.files?.[0])} disabled={busy} />
        </label>
      ) : (
        <div className="card">
          <div className="field">
            <label htmlFor="url">ลิงก์คลิป</label>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <LinkIcon color="#9AA1AD" />
              <input id="url" className="input" type="url" placeholder="https://www.youtube.com/watch?v=..."
                value={url} onChange={(e) => setUrl(e.target.value)} disabled={busy} />
            </div>
          </div>
          <span className="dim">รองรับ YouTube, TikTok, Facebook, Bilibili และเว็บอื่นที่ yt-dlp รองรับ · คลิปยาวไม่เกิน 60 นาที</span>
        </div>
      )}

      <section className="grid-3" aria-label="ตั้งค่างาน">
        <div className="card tight field">
          <label htmlFor="src">ภาษาต้นฉบับ</label>
          <select id="src" className="select" value={sourceLang} onChange={(e) => setSourceLang(e.target.value)}>
            <option value="">ตรวจอัตโนมัติ</option>
            {LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select>
        </div>
        <div className="card tight field">
          <span className="label">พากย์เป็นภาษา</span>
          <div className="seg" role="group" aria-label="ภาษาพากย์">
            {(["th", "en"] as TargetLang[]).map((t) => (
              <button key={t} type="button" aria-pressed={targetLang === t} onClick={() => setTargetLang(t)}>
                {TARGET_LABEL[t]}
              </button>
            ))}
          </div>
        </div>
        <div className="card tight field">
          <label htmlFor="spk">จำนวนตัวละคร (ถ้ารู้)</label>
          <input id="spk" className="input" type="number" min={1} max={20} placeholder="ไม่ระบุ"
            value={speakers} onChange={(e) => setSpeakers(e.target.value)} />
        </div>
        <label className="card tight check">
          <span className="t"><span>ตรวจบทก่อนพากย์</span><small>หยุดรอให้แก้บทหลังแปลเสร็จ</small></span>
          <input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} />
        </label>
        <label className="card tight check">
          <span className="t"><span>ฝังซับในวิดีโอ</span><small>ได้ไฟล์ SRT แยกมาเสมอ</small></span>
          <input type="checkbox" checked={burnSubs} onChange={(e) => setBurnSubs(e.target.checked)} />
        </label>
      </section>

      {error && <div className="alert error" role="alert">{error}</div>}

      <div className="row" style={{ justifyContent: "space-between" }}>
        {progress !== null ? (
          <div style={{ flex: "1 1 260px", display: "flex", alignItems: "center", gap: 12 }}>
            <div className="progress" style={{ flex: 1 }}><div style={{ width: `${progress * 100}%` }} /></div>
            <span className="mono">{Math.round(progress * 100)}%</span>
            <button type="button" className="btn small" onClick={() => abortRef.current?.()}>ยกเลิก</button>
          </div>
        ) : (
          <span />
        )}
        <button type="button" className="btn primary lg" onClick={submit} disabled={!ready || busy}>
          {busy ? (mode === "file" ? "กำลังอัปโหลด..." : "กำลังส่งงาน...") : "เริ่มประมวลผล"}
          {!busy && <ArrowRight />}
        </button>
      </div>

      <section aria-labelledby="recent" style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 8 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 id="recent" style={{ margin: 0, fontSize: 17, fontWeight: 500 }}>งานล่าสุด</h2>
          <Link href="/jobs" style={{ fontSize: 14 }}>ดูทั้งหมด</Link>
        </div>
        <div className="table-wrap">
          {recent === null ? (
            <div className="empty">กำลังโหลด...</div>
          ) : recent.length === 0 ? (
            <div className="empty">ยังไม่มีงาน</div>
          ) : (
            recent.map((j) => (
              <Link key={j.id} href={`/jobs/${j.id}`} className="row"
                style={{ padding: "14px 18px", borderBottom: "1px solid var(--line)", color: "var(--text)", textDecoration: "none", justifyContent: "space-between" }}>
                <span style={{ flex: "1 1 220px", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{j.filename}</span>
                <span className="dim">{langName(j.detected_lang ?? j.source_lang)} → {TARGET_LABEL[j.target_lang]}</span>
                <StatusBadge job={j} detail />
              </Link>
            ))
          )}
        </div>
      </section>
    </main>
  );
}
