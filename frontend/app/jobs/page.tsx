"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Job, type JobStatus } from "@/lib/api";
import { TARGET_LABEL, fmtDuration, fmtWhen, isActive, langName } from "@/lib/format";
import StatusBadge from "@/components/StatusBadge";
import JobCard from "@/components/JobCard";
import { GridIcon, ListIcon, PlusIcon, SearchIcon } from "@/components/Icons";

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

/** ปุ่มจัดการของหนึ่งงาน ใช้ทั้งแถวในตารางและใบงานบนจอแคบ */
function JobActions({ job, busy, onAct, className }: {
  job: Job;
  busy: boolean;
  onAct: (id: string, fn: () => Promise<unknown>) => void;
  className?: string;
}) {
  const a = actionFor(job);
  return (
    <div className={className ?? "row"} style={className ? undefined : { justifyContent: "flex-end", gap: 14 }}>
      <Link href={a.href} aria-label={`${a.label} ${job.filename}`}>{a.label}</Link>
      {(job.status === "failed" || job.status === "cancelled") && (
        <button type="button" className="btn small" disabled={busy}
          aria-label={`${tx("ลองใหม่")} ${job.filename}`}
          onClick={() => onAct(job.id, () => api.retry(job.id))}>{tx("ลองใหม่")}</button>
      )}
      {isActive(job) ? (
        <button type="button" className="btn small danger" disabled={busy}
          aria-label={`${tx("ยกเลิก")} ${job.filename}`}
          onClick={() => onAct(job.id, () => api.cancel(job.id))}>{tx("ยกเลิก")}</button>
      ) : (
        <button type="button" className="btn small danger" disabled={busy}
          aria-label={`${tx("ลบ")} ${job.filename}`}
          onClick={() => {
            if (window.confirm(tx("ลบงาน {0} และไฟล์ทั้งหมด?", { 0: job.filename }))) onAct(job.id, () => api.deleteJob(job.id));
          }}>{tx("ลบ")}</button>
      )}
    </div>
  );
}

type View = "grid" | "list";
const VIEW_KEY = "jobs-view";

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
        <div className="row">
          <label className="search" style={{ flex: "1 1 240px", maxWidth: 320 }}>
            <SearchIcon />
            <span className="sr-only">{tx("ค้นหางาน")}</span>
            <input type="search" placeholder={tx("ค้นหาชื่อไฟล์")} value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <Link href="/" className="btn primary small"><PlusIcon />{tx("ส่งคลิปใหม่")}</Link>
        </div>
      </div>

      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="chips" role="group" aria-label={tx("กรองตามสถานะ")}>
          {FILTERS.map((f) => (
            <button key={f.key} type="button" className="chip filter" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
              {tx(f.label)} <span className="n">{counts[f.key]}</span>
            </button>
          ))}
        </div>
        <div className="seg icons" role="group" aria-label={tx("มุมมอง")}>
          <button type="button" aria-pressed={view === "list"} aria-label={tx("รายการ")} title={tx("รายการ")} onClick={() => pickView("list")}><ListIcon size={16} /></button>
          <button type="button" aria-pressed={view === "grid"} aria-label={tx("การ์ด")} title={tx("การ์ด")} onClick={() => pickView("grid")}><GridIcon size={16} /></button>
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
      <>
      <div className="table-wrap jobs-table-wrap">
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
              {shown.map((j) => (
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
                    <JobActions job={j} busy={busyId === j.id} onAct={act} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {jobs !== null && shown.length > 0 && (
        <ul className="job-list-cards">
          {shown.map((j) => (
            <li key={j.id} className="job-list-card">
              <div className="job-list-main">
                <Link href={`/jobs/${j.id}`} className="job-list-title">{j.filename}</Link>
                <span className="muted">{fmtWhen(j.created_at)}</span>
                <StatusBadge job={j} detail />
                {j.status === "running" && (
                  <div className="progress" style={{ width: "100%", height: 4 }}><div style={{ width: `${j.progress * 100}%` }} /></div>
                )}
                {j.status === "failed" && j.error && (
                  <span className="dim">{j.error.slice(0, 120)}</span>
                )}
              </div>
              <JobActions job={j} busy={busyId === j.id} onAct={act} className="job-list-actions" />
            </li>
          ))}
        </ul>
      )}
      </>
      )}
    </main>
  );
}
