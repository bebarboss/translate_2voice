"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Job, type JobStatus } from "@/lib/api";
import { TARGET_LABEL, fmtDuration, fmtWhen, isActive, langName } from "@/lib/format";
import StatusBadge from "@/components/StatusBadge";
import { PlusIcon, SearchIcon } from "@/components/Icons";

type Filter = "all" | "active" | "awaiting_review" | "done" | "failed";

const FILTERS: { key: Filter; label: string; match: (s: JobStatus) => boolean }[] = [
  { key: "all", label: "ทั้งหมด", match: () => true },
  { key: "active", label: "กำลังทำ", match: (s) => s === "queued" || s === "running" },
  { key: "awaiting_review", label: "รอตรวจบท", match: (s) => s === "awaiting_review" },
  { key: "done", label: "เสร็จแล้ว", match: (s) => s === "done" },
  { key: "failed", label: "ล้มเหลว/ยกเลิก", match: (s) => s === "failed" || s === "cancelled" },
];

function actionFor(job: Job): { href: string; label: string } {
  if (job.status === "awaiting_review") return { href: `/jobs/${job.id}`, label: "ตรวจบท" };
  if (job.status === "done") return { href: `/jobs/${job.id}`, label: "เปิดผลลัพธ์" };
  if (isActive(job)) return { href: `/jobs/${job.id}`, label: "ดูความคืบหน้า" };
  return { href: `/jobs/${job.id}`, label: "ดูรายละเอียด" };
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [busyId, setBusyId] = useState("");

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
        <h1>งานทั้งหมด</h1>
        <Link href="/" className="btn primary"><PlusIcon />ส่งคลิปใหม่</Link>
      </div>

      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row" role="group" aria-label="กรองตามสถานะ" style={{ gap: 6 }}>
          {FILTERS.map((f) => (
            <button key={f.key} type="button" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}
              className="btn small"
              style={filter === f.key
                ? { borderRadius: 999, borderColor: "var(--accent)", background: "var(--accent-soft)", color: "#FFB27F" }
                : { borderRadius: 999, background: "transparent" }}>
              {f.label} {counts[f.key]}
            </button>
          ))}
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, height: 40, padding: "0 12px", borderRadius: 10, border: "1px solid var(--border-2)", background: "var(--surface-2)", minWidth: 240 }}>
          <SearchIcon color="#9AA1AD" />
          <span className="sr-only">ค้นหางาน</span>
          <input type="search" placeholder="ค้นหาชื่อไฟล์" value={query} onChange={(e) => setQuery(e.target.value)}
            style={{ flex: 1, minWidth: 0, border: "none", background: "transparent", outline: "none" }} />
        </label>
      </div>

      {error && <div className="alert error" role="alert">{error}</div>}

      <div className="table-wrap">
        {jobs === null ? (
          <div className="empty">กำลังโหลด...</div>
        ) : shown.length === 0 ? (
          <div className="empty">ไม่มีงานในหมวดนี้</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th scope="col">คลิป</th>
                <th scope="col">ภาษา</th>
                <th scope="col">ความยาว</th>
                <th scope="col">ตัวละคร</th>
                <th scope="col">สถานะ</th>
                <th scope="col">ส่งเมื่อ</th>
                <th scope="col">จัดการ</th>
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
                    <td>{langName(j.detected_lang ?? j.source_lang)} → {TARGET_LABEL[j.target_lang]}</td>
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
                            onClick={() => act(j.id, () => api.retry(j.id))}>ลองใหม่</button>
                        )}
                        {isActive(j) ? (
                          <button type="button" className="btn small danger" disabled={busyId === j.id}
                            onClick={() => act(j.id, () => api.cancel(j.id))}>ยกเลิก</button>
                        ) : (
                          <button type="button" className="btn small danger" disabled={busyId === j.id}
                            onClick={() => {
                              if (window.confirm(`ลบงาน ${j.filename} และไฟล์ทั้งหมด?`)) act(j.id, () => api.deleteJob(j.id));
                            }}>ลบ</button>
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
    </main>
  );
}
