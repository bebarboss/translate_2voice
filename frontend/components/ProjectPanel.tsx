"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Job, type Project } from "@/lib/api";
import { tx } from "@/lib/i18n";
import { FolderIcon } from "./Icons";

/** งานนี้กับโปรเจกต์: ตัวละครที่จับคู่ได้จากลายเสียง และบันทึกชื่อ เสียงพากย์ ข้อมูลตัวละครกลับเข้าโปรเจกต์
 * งานที่ยังไม่อยู่ในโปรเจกต์ เลือกโปรเจกต์ให้ได้ (จับคู่ตัวละครทันที) */
export default function ProjectPanel({ job, label, onChanged }: {
  job: Job; label: (speaker: string) => string; onChanged: () => void;
}) {
  const [project, setProject] = useState<Project | null>(null);
  const [all, setAll] = useState<Project[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [settings, setSettings] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const matches = job.project_matches ?? {};

  useEffect(() => {
    if (job.project_id) api.getProject(job.project_id).then(setProject).catch(() => setProject(null));
    else api.listProjects().then(setAll).catch(() => setAll([]));
  }, [job.project_id]);
  useEffect(() => {
    // ค่าเริ่มต้น: ตรงกับตัวละครเดิม (มั่นใจหรือแนะนำ) → บันทึกทับตัวนั้น, ตั้งชื่อไว้ → ตัวใหม่, ไม่ได้ตั้งชื่อ → ไม่บันทึก
    setMapping(Object.fromEntries(job.speakers.map((s) => [s, matches[s]?.character ?? (job.speaker_names?.[s] ? "new" : "skip")])));
    setSettings(!!project && !project.genre && !project.glossary);
  }, [job.speakers, job.project_matches, job.speaker_names, project]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (fn: () => Promise<string>) => {
    setBusy(true); setMessage(null);
    try { setMessage({ kind: "info", text: await fn() }); onChanged(); }
    catch (e) { setMessage({ kind: "error", text: (e as Error).message }); }
    finally { setBusy(false); }
  };

  if (!job.project_id) {
    if (all.length === 0) return null;
    return (
      <div className="card tight row" style={{ gap: 10 }}>
        <FolderIcon />
        <span className="muted">{tx("พากย์หลายตอน? เพิ่มงานนี้เข้าโปรเจกต์ ระบบจับคู่ตัวละครกับตอนก่อน ๆ ให้")}</span>
        <select className="select pill-select" aria-label={tx("เพิ่มเข้าโปรเจกต์")} value="" disabled={busy}
          onChange={(e) => e.target.value && run(async () => { await api.setJobProject(job.id, e.target.value); return tx("เพิ่มเข้าโปรเจกต์แล้ว"); })}>
          <option value="">{tx("เลือกโปรเจกต์")}</option>
          {all.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>
    );
  }
  if (!project) return null;
  const byId = Object.fromEntries(project.characters.map((c) => [c.id, c]));
  const sync = () => run(async () => {
    const r = await api.syncProject(job.id, mapping, settings);
    setProject(r.project);
    return tx("บันทึก {0} ตัวละครเข้าโปรเจกต์แล้ว ตอนถัดไปจะได้ชื่อและเสียงพากย์ตามนี้", { 0: r.saved });
  });

  return (
    <details className="card tight retranslate" open={Object.values(matches).some((m) => !m.sure) || undefined}>
      <summary>
        <FolderIcon size={16} /> {tx("โปรเจกต์")} <Link href={`/projects/${project.id}`} onClick={(e) => e.stopPropagation()}>{project.name}</Link>
        <span className="dim">{tx("จับคู่ตัวละครได้ {0} จาก {1} คน", { 0: Object.values(matches).filter((m) => m.sure).length, 1: job.speakers.length })}</span>
      </summary>
      <span className="dim">{tx("ตรวจว่าผู้พูดแต่ละคนตรงกับตัวละครไหน แล้วกดบันทึก ระบบจำชื่อ เสียงพากย์ที่บันทึกไว้ในงาน และลายเสียงไว้ใช้กับตอนถัดไป")}</span>
      <div>
        {job.speakers.map((s) => {
          const m = matches[s];
          return (
            <div key={s} className="project-match">
              <b style={{ minWidth: 120 }}>{label(s)}</b>
              {m ? (
                <span className={`badge ${m.sure ? "done" : "warn"}`}>
                  {m.sure ? tx("ตรงกับ {0}", { 0: byId[m.character]?.name ?? m.name }) : tx("อาจเป็น {0}", { 0: byId[m.character]?.name ?? m.name })}
                  {m.score != null && ` · ${Math.round(m.score * 100)}%`}
                </span>
              ) : <span className="badge queued">{tx("ไม่ตรงกับตัวละครเดิม")}</span>}
              <select className="select pill-select" style={{ marginLeft: "auto" }} aria-label={tx("บันทึก {0} เป็น", { 0: label(s) })}
                value={mapping[s] ?? "skip"} onChange={(e) => setMapping({ ...mapping, [s]: e.target.value })}>
                {project.characters.map((c) => <option key={c.id} value={c.id}>{tx("บันทึกเป็น {0}", { 0: c.name })}</option>)}
                <option value="new">{tx("ตัวละครใหม่")}</option>
                <option value="skip">{tx("ไม่บันทึก")}</option>
              </select>
            </div>
          );
        })}
      </div>
      <label className="agree">
        <input type="checkbox" checked={settings} onChange={(e) => setSettings(e.target.checked)} />
        {tx("บันทึกแนวเรื่อง ชื่อเฉพาะ และระดับภาษาของงานนี้เป็นของโปรเจกต์ด้วย")}
      </label>
      {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
      <button type="button" className="btn small primary" style={{ alignSelf: "flex-start" }} disabled={busy} onClick={sync}>
        {busy ? tx("กำลังบันทึก...") : tx("บันทึกเข้าโปรเจกต์")}
      </button>
    </details>
  );
}
