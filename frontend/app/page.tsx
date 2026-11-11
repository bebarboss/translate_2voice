"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, fileUrl, uploadJob, type CreateOptions, type Job, type Project, type TargetLang } from "@/lib/api";
import { LANGS, TARGET_LABEL, fmtDuration, fmtWhen, langName } from "@/lib/format";
import StatusBadge from "@/components/StatusBadge";
import { ArrowRight, FolderIcon, LinkIcon, PlayIcon, TimelineIcon, UploadIcon, VideoIcon, WaveIcon } from "@/components/Icons";

import { tx } from "@/lib/i18n";
const ACCEPT = ".mp4,.mov,.mkv,.webm,.avi,.m4v";

/** การ์ดวิดีโอของงานล่าสุด: ภาพปกจริงของคลิป สถานะ และความยาว */
function VideoCard({ job }: { job: Job }) {
  const [noThumb, setNoThumb] = useState(false);
  return (
    <Link href={`/jobs/${job.id}`} className="vc">
      <span className="vc-thumb">
        {!noThumb && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={fileUrl.thumb(job.id, job.input_path ? "1" : "")} alt="" loading="lazy" onError={() => setNoThumb(true)} />
        )}
        <span className="vc-play" aria-hidden="true"><PlayIcon size={18} /></span>
        <StatusBadge job={job} />
        {job.duration ? <span className="dur">{fmtDuration(job.duration)}</span> : null}
      </span>
      <span className="vc-text">
        <b title={job.filename}>{job.filename}</b>
        <span>{langName(job.detected_lang ?? job.source_lang)} → {tx(TARGET_LABEL[job.target_lang])} · {fmtWhen(job.updated_at)}</span>
      </span>
    </Link>
  );
}

export default function UploadPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"file" | "url">("file");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [drag, setDrag] = useState(false);
  const [sourceLang, setSourceLang] = useState("");
  const [targetLang, setTargetLang] = useState<TargetLang>("th");
  const [review, setReview] = useState(true);
  const [burnSubs, setBurnSubs] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState<Job[] | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [quote, setQuote] = useState<{ credits: number; remaining: number; enough: boolean; title?: string } | null>(null);
  const [quoteBusy, setQuoteBusy] = useState(false);
  const abortRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    api.getSettings().then((s) => {
      setTargetLang(s.default_target_lang);
      setReview(s.default_review);
      setBurnSubs(s.default_burn_subs);
    }).catch(() => { /* ใช้ค่าเริ่มต้นในหน้าเว็บ */ });
    api.listJobs().then((j) => setRecent(j.slice(0, 5))).catch(() => setRecent([]));
    // ?project=<id> จากปุ่ม "ส่งคลิปเข้าโปรเจกต์" เลือกโปรเจกต์นั้นไว้ให้
    const wanted = new URLSearchParams(window.location.search).get("project") ?? "";
    api.listProjects().then((list) => {
      setProjects(list);
      const p = list.find((x) => x.id === wanted);
      if (p) { setProjectId(p.id); setTargetLang(p.target_lang); }
    }).catch(() => setProjects([]));
  }, []);

  // ประมาณเครดิตจากลิงก์ (debounce)
  useEffect(() => {
    if (mode !== "url") return;
    const u = url.trim();
    if (!/^https?:\/\/\S+$/i.test(u)) {
      setQuote(null);
      setQuoteBusy(false);
      return;
    }
    let cancelled = false;
    setQuoteBusy(true);
    const t = window.setTimeout(() => {
      api.quoteUrl(u)
        .then((q) => {
          if (!cancelled) setQuote({ credits: q.credits, remaining: q.remaining, enough: q.enough, title: q.title });
        })
        .catch(() => { if (!cancelled) setQuote(null); })
        .finally(() => { if (!cancelled) setQuoteBusy(false); });
    }, 600);
    return () => { cancelled = true; window.clearTimeout(t); };
  }, [mode, url]);

  const project = projects.find((p) => p.id === projectId);
  const pickProject = (id: string) => {
    setProjectId(id);
    const p = projects.find((x) => x.id === id);
    if (p) setTargetLang(p.target_lang);
  };

  const pickFile = (f: File | undefined | null) => {
    setError("");
    setQuote(null);
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPT.split(",").includes(ext)) {
      setError(tx("รองรับเฉพาะไฟล์ MP4, MOV, MKV, WEBM, AVI, M4V"));
      return;
    }
    setFile(f);
    const urlObj = URL.createObjectURL(f);
    const video = document.createElement("video");
    video.preload = "metadata";
    video.onloadedmetadata = () => {
      const sec = video.duration;
      URL.revokeObjectURL(urlObj);
      if (!Number.isFinite(sec) || sec <= 0) return;
      api.quoteJob(sec).then((q) => setQuote({ credits: q.credits, remaining: q.remaining, enough: q.enough }))
        .catch(() => setQuote(null));
    };
    video.src = urlObj;
  };

  const ready = mode === "file" ? !!file : /^https?:\/\/\S+$/i.test(url.trim());

  const submit = async () => {
    if (!ready || busy) return;
    setError("");
    setBusy(true);
    const opts: CreateOptions = {
      sourceLang, targetLang, review, burnSubs, projectId: projectId || undefined,
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
    <main className="page" style={{ maxWidth: 980, gap: 36 }}>
      <section style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 22 }}>
        <div className="hero">
          <h1>{tx("วันนี้อยากพากย์คลิปไหนดี?")}</h1>
          <p>{tx("ส่งคลิปละครภาษาใดก็ได้ ระบบจะแยกเสียงตัวละคร แปล แล้วให้คุณตรวจบทก่อนพากย์")}</p>
        </div>

        <div className="create-box">
          <div className="tabs" role="tablist" aria-label={tx("วิธีส่งคลิป")}>
            <button type="button" role="tab" className="tab" aria-selected={mode === "file"} onClick={() => { setMode("file"); setQuote(null); }}>
              <UploadIcon size={15} />{tx("อัปโหลดไฟล์")}
            </button>
            <button type="button" role="tab" className="tab" aria-selected={mode === "url"} onClick={() => { setMode("url"); setQuote(null); }}>
              <LinkIcon size={15} />{tx("วางลิงก์")}
            </button>
            <Link href="/timeline" className="tab">
              <TimelineIcon size={15} />{tx("นำเข้าไทม์ไลน์")} <span className="tag">{tx("Beta")}</span>
            </Link>
          </div>

          {mode === "file" ? (
            <label
              className={`dropzone${drag ? " drag" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); pickFile(e.dataTransfer.files[0]); }}
            >
              <span className="icon"><UploadIcon size={26} /></span>
              {file ? (
                <>
                  <span className="t">{file.name}</span>
                  <span className="dim">{(file.size / 1024 / 1024).toFixed(1)}  {tx("MB · คลิกเพื่อเปลี่ยนไฟล์")}</span>
                </>
              ) : (
                <>
                  <span className="t">{tx("ลากคลิปมาวาง หรือ")} <span className="u">{tx("เลือกไฟล์")}</span></span>
                  <span className="dim">{tx("MP4, MOV, MKV, WEBM · ไม่เกิน 500 MB")}</span>
                </>
              )}
              <input type="file" accept={ACCEPT} aria-label={tx("เลือกไฟล์วิดีโอ")} onChange={(e) => pickFile(e.target.files?.[0])} disabled={busy} />
            </label>
          ) : (
            <div className="create-url">
              <label htmlFor="url" className="label">{tx("ลิงก์คลิป")}</label>
              <input id="url" className="input" type="url" placeholder="https://www.youtube.com/watch?v=..."
                value={url} onChange={(e) => setUrl(e.target.value)} disabled={busy} />
              <span className="dim">{tx("รองรับ YouTube, TikTok, Facebook, Bilibili และเว็บอื่นที่ yt-dlp รองรับ · คลิปยาวไม่เกิน 60 นาที")}</span>
            </div>
          )}

          <div className="create-opts" aria-label={tx("ตั้งค่างาน")}>
            <label className="chip-select">
              <span>{tx("ต้นฉบับ")}</span>
              <select aria-label={tx("ภาษาต้นฉบับ")} value={sourceLang} onChange={(e) => setSourceLang(e.target.value)}>
                <option value="">{tx("ตรวจอัตโนมัติ")}</option>
                {LANGS.map((l) => <option key={l.code} value={l.code}>{tx(l.label)}</option>)}
              </select>
            </label>
            <div className="seg" role="group" aria-label={tx("ภาษาพากย์")}>
              {(["th", "en"] as TargetLang[]).map((t) => (
                <button key={t} type="button" aria-pressed={targetLang === t} onClick={() => setTargetLang(t)}>
                  {tx(TARGET_LABEL[t])}
                </button>
              ))}
            </div>
            <label className="chip" title={tx("หยุดรอให้แก้บทหลังแปลเสร็จ")}>
              <input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} />{tx("ตรวจบทก่อนพากย์")}
            </label>
            <label className="chip" title={tx("ได้ไฟล์ SRT แยกมาเสมอ")}>
              <input type="checkbox" checked={burnSubs} onChange={(e) => setBurnSubs(e.target.checked)} />{tx("ฝังซับในวิดีโอ")}
            </label>
            {projects.length > 0 && (
              <label className="chip-select">
                <span><FolderIcon size={14} /></span>
                <select aria-label={tx("โปรเจกต์")} value={projectId} onChange={(e) => pickProject(e.target.value)}>
                  <option value="">{tx("ไม่อยู่ในโปรเจกต์")}</option>
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </label>
            )}
            <button type="button" className="btn primary go" onClick={submit} disabled={!ready || busy}>
              {busy ? (mode === "file" ? tx("กำลังอัปโหลด...") : tx("กำลังส่งงาน...")) : tx("เริ่มพากย์")}
              {!busy && <ArrowRight size={16} />}
            </button>
          </div>

          {project && (
            <span className="dim" style={{ padding: "0 4px" }}>
              {tx("ใช้ตัวละคร {0} ตัว เสียงพากย์ และชื่อเฉพาะของโปรเจกต์นี้ ระบบจับคู่ตัวละครด้วยลายเสียงให้เอง", { 0: project.characters.length })}
            </span>
          )}
          {quoteBusy && mode === "url" && (
            <span className="dim" style={{ padding: "0 4px" }}>{tx("กำลังประมาณเครดิตจากลิงก์...")}</span>
          )}
          {quote && (
            <div className={`alert ${quote.enough ? "info" : "error"}`} role="status" style={{ margin: "0 4px" }}>
              {quote.title ? `${quote.title} · ` : ""}
              {tx("งานนี้ใช้ประมาณ {0} เครดิต · หลังเริ่มจะเหลือประมาณ {1} เครดิต", {
                0: quote.credits.toFixed(2),
                1: Math.max(0, quote.remaining).toFixed(2),
              })}
              {!quote.enough && (
                <> — <Link href="/promotions">{tx("เติมเครดิตหรืออัปเกรด")}</Link></>
              )}
            </div>
          )}
          {progress !== null && (
            <div className="create-progress">
              <div className="progress"><div style={{ width: `${progress * 100}%` }} /></div>
              <span className="mono">{Math.round(progress * 100)}%</span>
              <button type="button" className="btn small" onClick={() => abortRef.current?.()}>{tx("ยกเลิก")}</button>
            </div>
          )}
          {error && <div className="alert error" role="alert">{error}</div>}
        </div>
      </section>

      <section className="qa-grid" aria-label={tx("ทางลัด")}>
        <button type="button" className="qa" style={{ font: "inherit", textAlign: "left", cursor: "pointer" }} onClick={() => setMode("file")}>
          <span className="ico-tile"><VideoIcon size={22} /></span>
          <span><b>{tx("พากย์คลิปเดียว")}</b><span className="d">{tx("อัปโหลดแล้วได้คลิปพากย์ไทยพร้อมซับ")}</span></span>
        </button>
        <Link href="/projects" className="qa">
          <span className="ico-tile orange"><FolderIcon size={22} /></span>
          <span><b>{tx("ซีรีส์หลายตอน")}</b><span className="d">{tx("จำชื่อตัวละครและเสียงพากย์ข้ามตอน")}</span></span>
        </Link>
        <Link href="/voices" className="qa">
          <span className="ico-tile blue"><WaveIcon size={22} /></span>
          <span><b>{tx("คลังเสียง")}</b><span className="d">{tx("เลือกเสียงนักพากย์ หรือใช้เสียงต้นฉบับ")}</span></span>
        </Link>
        <Link href="/timeline" className="qa">
          <span className="ico-tile purple"><TimelineIcon size={22} /></span>
          <span><b>{tx("นำเข้าไทม์ไลน์")}</b><span className="d">{tx("จาก Premiere Pro / DaVinci Resolve")}</span></span>
        </Link>
      </section>

      <section aria-labelledby="recent" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="section-head">
          <h2 id="recent">{tx("งานล่าสุด")}</h2>
          <Link href="/jobs">{tx("ดูทั้งหมด")}</Link>
        </div>
        {recent === null ? (
          <div className="empty">{tx("กำลังโหลด...")}</div>
        ) : recent.length === 0 ? (
          <div className="card empty">{tx("ยังไม่มีงาน")}</div>
        ) : (
          <div className="vc-grid">
            {recent.map((j) => <VideoCard key={j.id} job={j} />)}
          </div>
        )}
      </section>
    </main>
  );
}
