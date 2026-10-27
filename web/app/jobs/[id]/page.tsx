"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, type Job } from "@/lib/api";
import { isActive } from "@/lib/format";
import ProcessingView from "@/components/ProcessingView";
import ReviewView from "@/components/ReviewView";
import ResultView from "@/components/ResultView";

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false); // เปิดหน้าตรวจบทจากงานที่เสร็จแล้ว

  const refresh = useCallback(async () => {
    try {
      const j = await api.getJob(id);
      setJob(j);
      setError("");
      return j;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [id]);

  useEffect(() => { refresh(); }, [refresh]);

  // ระหว่างงานกำลังทำ ถามสถานะทุก 2 วินาที
  const active = job ? isActive(job) : false;
  useEffect(() => {
    if (!active) return;
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [active, refresh]);

  // งานเริ่มพากย์ใหม่แล้ว ปิดโหมดแก้บท
  useEffect(() => { if (active) setEditing(false); }, [active]);

  if (!job) {
    return (
      <main className="page">
        {error ? (
          <>
            <div className="alert error" role="alert">{error}</div>
            <Link href="/jobs">กลับไปหน้างานทั้งหมด</Link>
          </>
        ) : <div className="empty">กำลังโหลด...</div>}
      </main>
    );
  }

  if (job.status === "awaiting_review" || (editing && job.status === "done")) {
    return <ReviewView job={job} onChanged={refresh} onCancelEdit={editing ? () => setEditing(false) : undefined} />;
  }
  if (job.status === "done") {
    return <ResultView job={job} onChanged={refresh} onEdit={() => setEditing(true)} />;
  }
  return <ProcessingView job={job} onChanged={refresh} />;
}
