"use client";

import Link from "next/link";
import { useState } from "react";
import { fileUrl, type Job } from "@/lib/api";
import { TARGET_LABEL, fmtDuration, fmtWhen, isActive, langName } from "@/lib/format";
import { tx } from "@/lib/i18n";
import StatusBadge from "./StatusBadge";
import { ShuffleIcon, TrashIcon, WaveIcon, XIcon } from "./Icons";

/** การ์ดงาน: ภาพตัวอย่าง (งานเสียงล้วนแสดงไอคอน) สถานะ ความยาว และปุ่มจัดการเมื่อชี้ */
export default function JobCard({ job, busy, onRetry, onCancel, onDelete }: {
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
