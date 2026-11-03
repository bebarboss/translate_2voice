"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, fileUrl, type Job, type JobStatus } from "@/lib/api";
import { TARGET_LABEL, fmtDuration, fmtWhen, isActive, langName } from "@/lib/format";
import StatusBadge from "@/components/StatusBadge";
import { PlusIcon, SearchIcon, ShuffleIcon, TrashIcon, WaveIcon, XIcon } from "@/components/Icons";

import { tx } from "@/lib/i18n";
type Filter = "all" | "active" | "awaiting_review" | "done" | "failed";

const FILTERS: { key: Filter; label: string; match: (s: JobStatus) => boolean }[] = [
  { key: "all", label: "ทั้งหมด", match: () => true },
  { key: "active", label: "กำลังทำ", match: (s) => s === "queued" || s === "running" },
  { key: "awaiting_review", label: "รอตรวจบท", match: (s) => s === "awaiting_review" },
  { key: "done", label: "เสร็จแล้ว", match: (s) => s === "done" },
  { key: "failed", label: "ล้มเหลว/ยกเลิก", match: (s) => s === "failed" || s === "cancelled" },
];

function actionFor(job: Job): { href: string; label: string } {
  if (job.status === "awaiting_review") return { href: `/jobs/${job.id}`, label: tx("ตรวจบท") };
  if (job.status === "done") return { href: `/jobs/${job.id}`, label: tx("เปิดผลลัพธ์") };
  if (isActive(job)) return { href: `/jobs/${job.id}`, label: tx("ดูความคืบหน้า") };
  return { href: `/jobs/${job.id}`, label: tx("ดูรายละเอียด") };
}

type View = "grid" | "list";
const VIEW_KEY = "jobs-view";

/** การ์ดงาน: ภาพตัวอย่าง (งานเสียงล้วนแสดงไอคอน) สถานะ ความยาว และปุ่มจัดการเมื่อชี้ */
function JobCard({ job, busy, onRetry, onCancel, onDelete }: {
  job: Job; busy: boolean; onRetry: () => void; onCancel: () => void; onDelete: () => void;
}) {
  const [noThumb, setNoThumb] = useState(false);
  const stop = (fn: () => void) => (e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation(); fn(); };
  return (
    <Link href={`/jobs/${job.id}`} className="job-card">
      <div className="job-thumb">
        {noThumb ? <WaveIcon /> : (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={fileUrl.thumb(job.id, job.input_path ? "1" : "")} alt="" loading="lazy" onError={() => setNoThumb(true)} />
        )}
        <StatusBadge job={job} />
        {job.duration ? <span className="dur">{fmtDuration(job.duration)}</span> : null}
        {job.status === "running" && <div className="bar"><div style={{ width: `${job.progress * 100}%` }} /></div>}
        <div className="job-actions">
          {(job.status === "failed" || job.status === "cancelled") && (
            <button type="button" className="icon-btn" disabled={busy} title={tx("ลองใหม่")} aria-label={tx("ลองใหม่")} onClick={stop(onRetry)}><ShuffleIcon /></button>
          )}
          {isActive(job)
            ? <button type="button" className="icon-btn" disabled={busy} title={tx("ยกเลิก")} aria-label={tx("ยกเลิก")} onClick={stop(onCancel)}><XIcon /></button>
            : <button type="button" className="icon-btn" disabled={busy} title={tx("ลบ")} aria-label={tx("ลบ")} onClick={stop(onDelete)}><TrashIcon /></button>}
        </div>
      </div>
      <div className="job-meta">
        <span className="avatar-dot plain" aria-hidden="true">{job.filename.slice(0, 1).toUpperCase()}</span>
        <div>
          <b title={job.filename}>{job.filename}</b>
          <span>{langName(job.detected_lang ?? job.source_lang)} → {tx(TARGET_LABEL[job.target_lang])} · {tx("แก้ไขเมื่อ {0}", { 0: fmtWhen(job.updated_at) })}</span>
        </div>
      </div>
    </Link>
  );
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [busyId, setBusyId] = useState("");
  const [view, setView] = useState<View>("grid");
  useEffect(() => {
    try { if (localStorage.getItem(VIEW_KEY) === "list") setView("list"); } catch { /* ใช้ค่าเริ่มต้น */ }
  }, []);
  const pickView = (v: View) => {
    setView(v);
    try { localStorage.setItem(VIEW_KEY, v); } catch { /* ไม่จำก็ได้ */ }
  };

  const load = useCallback(() => {
    api.listJobs().then((j) => { setJobs(j); setError(""); }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: 0, active: 0, awaiting_review: 0, done: 0, failed: 0 };
    for (const j of jobs ?? []) for (const f of FILTERS) if (f.match(j.status)) c[f.key]++;
    return c;
  }, [jobs]);

  const shown = useMemo(() => {
    const f = FILTERS.find((x) => x.key === filter)!;
    const q = query.trim().toLowerCase();
    return (jobs ?? []).filter((j) => f.match(j.status) && (!q || j.filename.toLowerCase().includes(q)));
  }, [jobs, filter, query]);

  const act = async (id: string, fn: () => Promise<unknown>) => {
    setBusyId(id);
    try { await fn(); load(); } catch (e) { setError((e as Error).message); } finally { setBusyId(""); }
  };

  return (
    <main className="page" style={{ maxWidth: 1200 }}>
      <div className="page-head">
        <h1>{tx("งานทั้งหมด")}</h1>
        <Link href="/" className="btn primary small"><PlusIcon />{tx("ส่งคลิปใหม่")}</Link>
      </div>

      <div className="row" style={{ gap: 8 }}>
        <label className="search" style={{ flex: "1 1 260px", maxWidth: 360 }}>
          <SearchIcon />
          <span className="sr-only">{tx("ค้นหางาน")}</span>
          <input type="search" placeholder={tx("ค้นหาชื่อไฟล์")} value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <select className="select pill-select" aria-label={tx("กรองตามสถานะ")} value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
          {FILTERS.map((f) => <option key={f.key} value={f.key}>{tx(f.label)} ({counts[f.key]})</option>)}
        </select>
        <div className="seg" role="group" aria-label={tx("มุมมอง")}>
          <button type="button" aria-pressed={view === "grid"} onClick={() => pickView("grid")}>{tx("การ์ด")}</button>
          <button type="button" aria-pressed={view === "list"} onClick={() => pickView("list")}>{tx("รายการ")}</button>
        </div>
      </div>

      {error && <div className="alert error" role="alert">{error}</div>}

      {view === "grid" && jobs !== null && shown.length > 0 ? (
        <div className="job-grid">
          {shown.map((j) => (
            <JobCard key={j.id} job={j} busy={busyId === j.id}
              onRetry={() => act(j.id, () => api.retry(j.id))}
              onCancel={() => act(j.id, () => api.cancel(j.id))}
              onDelete={() => { if (window.confirm(tx("ลบงาน {0} และไฟล์ทั้งหมด?", { 0: j.filename }))) act(j.id, () => api.deleteJob(j.id)); }} />
          ))}
        </div>
      ) : (
      <div className="table-wrap">
        {jobs === null ? (
          <div className="empty">{tx("กำลังโหลด...")}</div>
        ) : shown.length === 0 ? (
          <div className="empty">{tx("ไม่มีงานในหมวดนี้")}</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th scope="col">{tx("คลิป")}</th>
                <th scope="col">{tx("ภาษา")}</th>
                <th scope="col">{tx("ความยาว")}</th>
                <th scope="col">{tx("ตัวละคร")}</th>
                <th scope="col">{tx("สถานะ")}</th>
                <th scope="col">{tx("ส่งเมื่อ")}</th>
                <th scope="col">{tx("จัดการ")}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((j) => {
                const a = actionFor(j);
                return (
                  <tr key={j.id}>
                    <td style={{ maxWidth: 320 }}>
                      <Link href={`/jobs/${j.id}`} style={{ color: "var(--text)", textDecoration: "none", fontSize: 15 }}>{j.filename}</Link>
                      {j.source_url && <div className="dim" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{j.source_url}</div>}
                    </td>
                    <td>{langName(j.detected_lang ?? j.source_lang)} → {tx(TARGET_LABEL[j.target_lang])}</td>
                    <td className="mono">{fmtDuration(j.duration)}</td>
                    <td>{j.speakers.length || "—"}</td>
                    <td>
                      <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-start" }}>
                        <StatusBadge job={j} detail />
                        {j.status === "running" && (
                          <div className="progress" style={{ width: 120, height: 4 }}><div style={{ width: `${j.progress * 100}%` }} /></div>
                        )}
                        {j.status === "failed" && j.error && (
                          <span className="dim" style={{ maxWidth: 260 }}>{j.error.slice(0, 120)}</span>
                        )}
                      </div>
                    </td>
                    <td className="muted">{fmtWhen(j.created_at)}</td>
                    <td>
                      <div className="row" style={{ justifyContent: "flex-end", gap: 14 }}>
                        <Link href={a.href}>{a.label}</Link>
                        {(j.status === "failed" || j.status === "cancelled") && (
                          <button type="button" className="btn small" disabled={busyId === j.id}
                            onClick={() => act(j.id, () => api.retry(j.id))}>{tx("ลองใหม่")}</button>
                        )}
                        {isActive(j) ? (
                          <button type="button" className="btn small danger" disabled={busyId === j.id}
                            onClick={() => act(j.id, () => api.cancel(j.id))}>{tx("ยกเลิก")}</button>
                        ) : (
                          <button type="button" className="btn small danger" disabled={busyId === j.id}
                            onClick={() => {
                              if (window.confirm(tx("ลบงาน {0} และไฟล์ทั้งหมด?", { 0: j.filename }))) act(j.id, () => api.deleteJob(j.id));
                            }}>{tx("ลบ")}</button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      )}
    </main>
  );
}
