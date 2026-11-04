"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FolderIcon, PlusIcon } from "@/components/Icons";
import { api, type Project, type TargetLang } from "@/lib/api";
import { GENRES, TARGET_LABEL, fmtWhen } from "@/lib/format";
import { tx } from "@/lib/i18n";

/** โปรเจกต์: เรื่องหนึ่งเรื่องที่มีหลายตอน จำตัวละคร เสียงพากย์ และชื่อเฉพาะข้ามตอน */
export default function ProjectsPage() {
  const router = useRouter();
  const [list, setList] = useState<Project[] | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [genre, setGenre] = useState("");
  const [target, setTarget] = useState<TargetLang>("th");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.listProjects().then(setList).catch((e) => setError(e.message)); }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true); setError("");
    try {
      const p = await api.createProject({ name: name.trim(), genre: genre.trim(), glossary: "", speech_style: "", target_lang: target });
      router.push(`/projects/${p.id}`);
    } catch (err) { setError((err as Error).message); setBusy(false); }
  };

  return (
    <main className="page" style={{ maxWidth: 1200 }}>
      <div className="page-head">
        <div>
          <h1>{tx("โปรเจกต์")}</h1>
          <span className="muted">{tx("รวมคลิปหลายตอนของเรื่องเดียวกัน ระบบจำตัวละคร เสียงพากย์ และชื่อเฉพาะ แล้วใช้กับตอนถัดไปให้เอง")}</span>
        </div>
        {!creating && <button type="button" className="btn primary small" onClick={() => setCreating(true)}><PlusIcon />{tx("โปรเจกต์ใหม่")}</button>}
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}

      {creating && (
        <form className="card" onSubmit={create} aria-labelledby="new-proj">
          <h2 id="new-proj">{tx("โปรเจกต์ใหม่")}</h2>
          <div className="grid-3">
            <div className="field">
              <label htmlFor="pj-name">{tx("ชื่อเรื่อง")}</label>
              <input id="pj-name" className="input" required maxLength={80} autoFocus placeholder={tx("เช่น การแต่งงานครั้งใหม่ของจักรพรรดินี")}
                value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="pj-genre">{tx("แนวเรื่อง (ถ้ารู้)")}</label>
              <input id="pj-genre" className="input" list="pj-genres" maxLength={120} value={genre} onChange={(e) => setGenre(e.target.value)} />
              <datalist id="pj-genres">{GENRES.map((g) => <option key={g} value={tx(g)} />)}</datalist>
            </div>
            <div className="field">
              <span className="label">{tx("พากย์เป็นภาษา")}</span>
              <div className="seg" role="group" aria-label={tx("ภาษาพากย์")}>
                {(["th", "en"] as TargetLang[]).map((t) => (
                  <button key={t} type="button" aria-pressed={target === t} onClick={() => setTarget(t)}>{tx(TARGET_LABEL[t])}</button>
                ))}
              </div>
            </div>
          </div>
          <span className="dim">{tx("ตัวละครและชื่อเฉพาะจะเพิ่มเข้ามาเมื่อคุณกด “บันทึกเข้าโปรเจกต์” ในหน้าตรวจบทของตอนแรก")}</span>
          <div className="row">
            <button type="submit" className="btn primary small" disabled={busy || !name.trim()}>{busy ? tx("กำลังสร้าง...") : tx("สร้างโปรเจกต์")}</button>
            <button type="button" className="btn small" onClick={() => setCreating(false)}>{tx("ยกเลิก")}</button>
          </div>
        </form>
      )}

      {list === null ? <div className="empty">{tx("กำลังโหลด...")}</div> : list.length === 0 && !creating ? (
        <div className="card" style={{ alignItems: "center", textAlign: "center", padding: 40 }}>
          <FolderIcon size={28} />
          <strong>{tx("ยังไม่มีโปรเจกต์")}</strong>
          <span className="muted">{tx("พากย์ซีรีส์หรือการ์ตูนหลายตอน? สร้างโปรเจกต์ไว้ ตอนถัดไปไม่ต้องตั้งชื่อตัวละครและเลือกเสียงใหม่")}</span>
          <button type="button" className="btn primary small" onClick={() => setCreating(true)}><PlusIcon />{tx("โปรเจกต์ใหม่")}</button>
        </div>
      ) : (
        <div className="job-grid">
          {list.map((p) => (
            <Link key={p.id} href={`/projects/${p.id}`} className="project-card">
              <div className="project-icon"><FolderIcon size={26} /></div>
              <b>{p.name}</b>
              <span className="dim">{p.genre || tx("ยังไม่ระบุแนวเรื่อง")}</span>
              <span className="dim">
                {tx("{0} ตอน · ตัวละคร {1} · พากย์{2}", { 0: p.episodes, 1: p.characters.length, 2: tx(TARGET_LABEL[p.target_lang]) })}
                {" · "}{tx("แก้ไขเมื่อ {0}", { 0: fmtWhen(p.updated_at) })}
              </span>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
