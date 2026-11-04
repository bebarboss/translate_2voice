"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import JobCard from "@/components/JobCard";
import { ArrowLeft, PlusIcon, TrashIcon } from "@/components/Icons";
import { api, type Job, type LibraryVoice, type Project, type ProjectCharacter, type TargetLang } from "@/lib/api";
import { GENDER_LABEL, GENRES, TARGET_LABEL } from "@/lib/format";
import { tx } from "@/lib/i18n";

type Message = { kind: "error" | "info"; text: string } | null;

/** ตัวละครหนึ่งตัว: แก้ชื่อ ข้อมูลให้ผู้แปล และเสียงพากย์ (มีผลกับตอนที่ส่งเข้ามาหลังจากนี้) */
function CharacterRow({ p, c, voices, onSaved, onError }: {
  p: Project; c: ProjectCharacter; voices: LibraryVoice[]; onSaved: (p: Project) => void; onError: (m: string) => void;
}) {
  const [draft, setDraft] = useState({ name: c.name, role: c.role, self: c.self, addresses: c.addresses });
  const dirty = draft.name !== c.name || draft.role !== c.role || draft.self !== c.self || draft.addresses !== c.addresses;
  const save = (patch: Parameters<typeof api.updateCharacter>[2]) =>
    api.updateCharacter(p.id, c.id, patch).then(onSaved).catch((e) => onError(e.message));
  const set = (k: keyof typeof draft) => (e: { target: { value: string } }) => setDraft({ ...draft, [k]: e.target.value });
  return (
    <div className="set-row" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
      <div style={{ flex: "1 1 320px", display: "grid", gap: 8 }}>
        <div className="row" style={{ gap: 8 }}>
          <input className="input" style={{ maxWidth: 220, fontWeight: 600 }} aria-label={tx("ชื่อตัวละคร")} value={draft.name} onChange={set("name")} maxLength={60} />
          {c.gender && <span className="badge queued">{tx(GENDER_LABEL[c.gender as "male" | "female"] ?? c.gender)}</span>}
          <span className={`badge ${c.learned ? "done" : "warn"}`} title={tx("ใช้ลายเสียงนี้จับคู่ตัวละครในตอนถัดไป")}>
            {c.learned ? tx("จำเสียงจาก {0} ตอน", { 0: c.samples }) : tx("ยังไม่มีลายเสียง")}
          </span>
        </div>
        <input className="input" aria-label={tx("บทบาท")} placeholder={tx("บทบาท เช่น จักรพรรดินี ตัวเอก")} value={draft.role} onChange={set("role")} maxLength={200} />
        <div className="row" style={{ gap: 8 }}>
          <input className="input" style={{ flex: "1 1 140px" }} aria-label={tx("แทนตัวเอง")} placeholder={tx("แทนตัวเอง เช่น หม่อมฉัน")} value={draft.self} onChange={set("self")} maxLength={40} />
          <input className="input" style={{ flex: "2 1 200px" }} aria-label={tx("เรียกคนอื่น")} placeholder={tx("เรียกคนอื่น เช่น ฝ่าบาท")} value={draft.addresses} onChange={set("addresses")} maxLength={120} />
        </div>
        {dirty && <button type="button" className="btn small primary" style={{ alignSelf: "flex-start" }} onClick={() => save(draft)}>{tx("บันทึก")}</button>}
      </div>
      <div className="v" style={{ display: "grid", gap: 8, minWidth: 220 }}>
        <select className="select" aria-label={tx("เสียงพากย์ของ {0}", { 0: c.name })} value={c.voice_id ?? ""}
          onChange={(e) => save({ voice_id: e.target.value })}>
          <option value="">{tx("เสียงต้นฉบับ (เลียนเสียงนักแสดง)")}</option>
          {voices.map((v) => <option key={v.id} value={v.id}>{v.name}{v.gender ? ` (${tx(GENDER_LABEL[v.gender])})` : ""}</option>)}
        </select>
        <button type="button" className="btn small danger" style={{ justifySelf: "end" }}
          onClick={() => window.confirm(tx("ลบตัวละคร {0} ออกจากโปรเจกต์? ตอนที่พากย์ไปแล้วไม่เปลี่ยน", { 0: c.name }))
            && api.deleteCharacter(p.id, c.id).then(onSaved).catch((e) => onError(e.message))}>
          <TrashIcon />{tx("ลบตัวละคร")}
        </button>
      </div>
    </div>
  );
}

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [p, setP] = useState<(Project & { jobs: Job[] }) | null>(null);
  const [voices, setVoices] = useState<LibraryVoice[]>([]);
  const [others, setOthers] = useState<Job[]>([]);
  const [form, setForm] = useState({ name: "", genre: "", speech_style: "", glossary: "", target_lang: "th" as TargetLang });
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    api.getProject(id).then((x) => {
      setP(x);
      setForm({ name: x.name, genre: x.genre, speech_style: x.speech_style, glossary: x.glossary, target_lang: x.target_lang });
    }).catch((e) => setMessage({ kind: "error", text: e.message }));
    api.listJobs().then((j) => setOthers(j.filter((x) => !x.project_id && !x.library))).catch(() => setOthers([]));
  }, [id]);
  useEffect(() => {
    load();
    api.listVoices().then((v) => setVoices(v.filter((x) => x.status === "ready"))).catch(() => setVoices([]));
  }, [load]);

  if (!p) return <main className="page">{message ? <div className="alert error" role="alert">{message.text}</div> : <div className="empty">{tx("กำลังโหลด...")}</div>}</main>;
  const saved = (x: Project) => { setP({ ...p, ...x }); setMessage({ kind: "info", text: tx("บันทึกแล้ว มีผลกับตอนที่ส่งเข้ามาหลังจากนี้") }); };
  const dirty = form.name !== p.name || form.genre !== p.genre || form.speech_style !== p.speech_style || form.glossary !== p.glossary || form.target_lang !== p.target_lang;
  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key); setMessage(null);
    try { await fn(); load(); } catch (e) { setMessage({ kind: "error", text: (e as Error).message }); } finally { setBusy(""); }
  };

  return (
    <main className="page" style={{ maxWidth: 1200 }}>
      <div className="page-head">
        <div>
          <Link href="/projects" className="dim" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><ArrowLeft />{tx("โปรเจกต์ทั้งหมด")}</Link>
          <h1 style={{ margin: "6px 0 0" }}>{p.name}</h1>
          <span className="muted">{tx("{0} ตอน · ตัวละคร {1}", { 0: p.episodes, 1: p.characters.length })}</span>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <Link href={`/?project=${p.id}`} className="btn primary small"><PlusIcon />{tx("ส่งคลิปเข้าโปรเจกต์")}</Link>
          <button type="button" className="btn small danger" disabled={!!busy}
            onClick={() => window.confirm(tx("ลบโปรเจกต์ {0}? งานทุกตอนยังอยู่ แค่ไม่อยู่ในโปรเจกต์แล้ว", { 0: p.name }))
              && act("del", async () => { await api.deleteProject(p.id); router.push("/projects"); })}>{tx("ลบโปรเจกต์")}</button>
        </div>
      </div>
      {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}

      <section className="card" aria-labelledby="pj-story">
        <h2 id="pj-story">{tx("ข้อมูลเรื่อง")}</h2>
        <span className="dim">{tx("ใช้เป็นค่าตั้งต้นของทุกตอน ถ้าตั้งในงานไหนไว้เอง งานนั้นใช้ค่าของงาน")}</span>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="pf-name">{tx("ชื่อเรื่อง")}</label>
            <input id="pf-name" className="input" maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="pf-genre">{tx("แนวเรื่อง")}</label>
            <input id="pf-genre" className="input" list="pf-genres" maxLength={120} value={form.genre} onChange={(e) => setForm({ ...form, genre: e.target.value })} />
            <datalist id="pf-genres">{GENRES.map((g) => <option key={g} value={tx(g)} />)}</datalist>
          </div>
          <div className="field">
            <label htmlFor="pf-style">{tx("ระดับภาษา")}</label>
            <input id="pf-style" className="input" maxLength={400} placeholder={tx("เช่น ราชาศัพท์ หม่อมฉัน/เพคะ/ฝ่าบาท")}
              value={form.speech_style} onChange={(e) => setForm({ ...form, speech_style: e.target.value })} />
          </div>
          <div className="field">
            <span className="label">{tx("พากย์เป็นภาษา")}</span>
            <div className="seg" role="group" aria-label={tx("ภาษาพากย์")}>
              {(["th", "en"] as TargetLang[]).map((t) => (
                <button key={t} type="button" aria-pressed={form.target_lang === t} onClick={() => setForm({ ...form, target_lang: t })}>{tx(TARGET_LABEL[t])}</button>
              ))}
            </div>
          </div>
        </div>
        <div className="field">
          <label htmlFor="pf-gloss">{tx("ชื่อเฉพาะ (บรรทัดละคำ)")}</label>
          <textarea id="pf-gloss" className="textarea" rows={4} maxLength={4000} placeholder={tx("ドラえもん = โดราเอมอน\nのび太 = โนบิตะ")}
            value={form.glossary} onChange={(e) => setForm({ ...form, glossary: e.target.value })} />
        </div>
        {dirty && (
          <button type="button" className="btn primary small" style={{ alignSelf: "flex-start" }} disabled={!!busy || !form.name.trim()}
            onClick={() => act("save", () => api.updateProject(p.id, form))}>{busy === "save" ? tx("กำลังบันทึก...") : tx("บันทึก")}</button>
        )}
      </section>

      <section aria-labelledby="pj-chars" style={{ display: "grid", gap: 12 }}>
        <div className="set-head">
          <h2 id="pj-chars">{tx("ตัวละคร")}</h2>
          <p>{tx("ตอนใหม่ที่ส่งเข้าโปรเจกต์ ระบบจับคู่ผู้พูดกับตัวละครด้วยลายเสียง แล้วตั้งชื่อและเสียงพากย์ให้เอง เพิ่มตัวละครได้จากปุ่ม “บันทึกเข้าโปรเจกต์” ในหน้าตรวจบท")}</p>
        </div>
        {p.characters.length === 0 ? <div className="card"><span className="dim">{tx("ยังไม่มีตัวละคร ส่งตอนแรกเข้าโปรเจกต์ ตั้งชื่อตัวละครในหน้าตรวจบท แล้วกด “บันทึกเข้าโปรเจกต์”")}</span></div> : (
          <div className="set-group">
            {p.characters.map((c) => (
              <CharacterRow key={`${c.id}-${c.updated_at}`} p={p} c={c} voices={voices} onSaved={saved}
                onError={(m) => setMessage({ kind: "error", text: m })} />
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="pj-eps" style={{ display: "grid", gap: 12 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 id="pj-eps" style={{ margin: 0, fontSize: 17 }}>{tx("ตอนทั้งหมด")}</h2>
          {others.length > 0 && (
            <select className="select pill-select" aria-label={tx("เพิ่มงานที่มีอยู่เข้าโปรเจกต์")} value="" disabled={!!busy}
              onChange={(e) => e.target.value && act("add", () => api.setJobProject(e.target.value, p.id))}>
              <option value="">{tx("+ เพิ่มงานที่มีอยู่")}</option>
              {others.map((j) => <option key={j.id} value={j.id}>{j.filename}</option>)}
            </select>
          )}
        </div>
        {p.jobs.length === 0 ? <span className="dim">{tx("ยังไม่มีตอนในโปรเจกต์นี้")}</span> : (
          <div className="job-grid">
            {p.jobs.map((j) => (
              <JobCard key={j.id} job={j} busy={busy === j.id}
                onRetry={() => act(j.id, () => api.retry(j.id))}
                onCancel={() => act(j.id, () => api.cancel(j.id))}
                onDelete={() => { if (window.confirm(tx("ลบงาน {0} และไฟล์ทั้งหมด?", { 0: j.filename }))) act(j.id, () => api.deleteJob(j.id)); }} />
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
