"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, fileUrl, type Job } from "@/lib/api";
import { TARGET_LABEL, isActive, langName, speakerColor, speakerLabel, stageLabel, stepsFor } from "@/lib/format";
import StatusBadge from "./StatusBadge";
import { CheckIcon } from "./Icons";

const TITLE: Record<string, string> = {
  analyze: "กำลังเตรียมบทพากย์",
  synthesize: "กำลังพากย์เสียง",
  render: "กำลังฝังซับลงวิดีโอ",
};

export default function ProcessingView({ job, onChanged }: { job: Job; onChanged: () => void }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const steps = stepsFor(job);
  const currentIdx = steps.indexOf(job.stage);
  const active = isActive(job);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try { await fn(); onChanged(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const title = job.status === "failed" ? "งานล้มเหลว"
    : job.status === "cancelled" ? "ยกเลิกงานแล้ว"
    : job.status === "queued" ? "รอคิวประมวลผล"
    : TITLE[job.phase] ?? "กำลังประมวลผล";

  return (
    <main className="page">
      <div className="split">
        <section className="main card" aria-labelledby="ptitle" style={{ padding: 28, gap: 22 }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
              <h1 id="ptitle" style={{ margin: 0, fontSize: 26, fontWeight: 600 }}>{title}</h1>
              <span className="muted" style={{ wordBreak: "break-all" }}>
                {job.filename} · {job.detected_lang ?? job.source_lang ? langName(job.detected_lang ?? job.source_lang) : "ตรวจภาษาอัตโนมัติ"} → {TARGET_LABEL[job.target_lang]}
              </span>
            </div>
            <StatusBadge job={job} />
          </div>

          {active && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
                <span className="mono" style={{ fontSize: 34 }}>{Math.round(job.progress * 100)}%</span>
                <span className="muted">{job.stage === "cancelling" ? "กำลังยกเลิก รอให้ขั้นปัจจุบันจบก่อน" : stageLabel(job.stage)}</span>
              </div>
              <div className="progress" role="progressbar" aria-valuenow={Math.round(job.progress * 100)}
                aria-valuemin={0} aria-valuemax={100} aria-label="ความคืบหน้ารวม">
                <div style={{ width: `${job.progress * 100}%` }} />
              </div>
            </div>
          )}

          {job.status === "failed" && job.error && (
            <div className="alert error" role="alert" style={{ whiteSpace: "pre-wrap" }}>{job.error}</div>
          )}

          <ol className="steps">
            {steps.map((s, i) => {
              const state = job.status === "queued" ? "todo"
                : currentIdx < 0 ? (job.stage === "analyzed" || job.stage === "done" ? "done" : "todo")
                : i < currentIdx ? "done" : i === currentIdx ? (active ? "now" : "todo") : "todo";
              return (
                <li key={s} className={state}>
                  <span className="dot">{state === "done" && <CheckIcon />}</span>
                  <span className="name">{stageLabel(s)}</span>
                  <span className="dim">
                    {state === "done" ? (s === "diarize" && job.speakers.length ? `พบ ${job.speakers.length} ตัวละคร` : "เสร็จ")
                      : state === "now" ? "กำลังทำ" : "รอ"}
                  </span>
                </li>
              );
            })}
          </ol>

          {error && <div className="alert error" role="alert">{error}</div>}

          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="dim">
              {active ? "ปิดหน้านี้ได้ ระบบจะทำงานต่อ กลับมาดูได้ที่หน้างานทั้งหมด" : ""}
            </span>
            <div className="row">
              {active && (
                <button type="button" className="btn danger" disabled={busy || job.stage === "cancelling"}
                  onClick={() => run(() => api.cancel(job.id))}>ยกเลิกงาน</button>
              )}
              {!active && (
                <>
                  <button type="button" className="btn danger" disabled={busy}
                    onClick={() => {
                      if (window.confirm("ลบงานนี้และไฟล์ทั้งหมด?")) {
                        run(async () => { await api.deleteJob(job.id); router.push("/jobs"); });
                      }
                    }}>ลบงาน</button>
                  <button type="button" className="btn primary" disabled={busy}
                    onClick={() => run(() => api.retry(job.id))}>ลองใหม่</button>
                </>
              )}
            </div>
          </div>
        </section>

        <aside className="side card" aria-labelledby="stitle">
          <h2 id="stitle">ตัวละครที่พบ</h2>
          {job.speakers.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>จะแสดงหลังขั้นแยกผู้พูดเสร็จ ฟังเสียงแยกของแต่ละคนได้จากตรงนี้</p>
          ) : (
            <>
              <p className="muted" style={{ margin: 0, fontSize: 14 }}>ฟังเสียงแยกของแต่ละคน เพื่อเช็กว่าระบบแยกตัวละครถูกไหม</p>
              {job.speakers.map((s) => (
                <div key={s} style={{ display: "flex", flexDirection: "column", gap: 8, padding: 12, borderRadius: 12, background: "var(--surface-3)" }}>
                  <div className="row" style={{ gap: 8 }}>
                    <span className="swatch" style={{ background: speakerColor(s, job.speakers) }} />
                    <span>{speakerLabel(s)}</span>
                    <span className="dim">{s}</span>
                  </div>
                  <audio controls preload="none" src={fileUrl.stem(job.id, s)} style={{ width: "100%", height: 36 }}
                    aria-label={`เสียงแยกของ${speakerLabel(s)}`} />
                </div>
              ))}
            </>
          )}
          <Link href="/jobs" className="btn" style={{ marginTop: 4 }}>กลับหน้างานทั้งหมด</Link>
        </aside>
      </div>
    </main>
  );
}
