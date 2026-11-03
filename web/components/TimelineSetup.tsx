"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, uploadTimelineMedia, type Job, type LibraryVoice, type TimelineInfo, type TimelineTrack, type TrackSetup } from "@/lib/api";
import { GENDER_LABEL, speakerColor } from "@/lib/format";
import { ArrowLeft, ArrowRight } from "./Icons";

import { tx } from "@/lib/i18n";
const FORMAT_LABEL: Record<string, string> = {
  fcp_xml: "Final Cut Pro XML (Premiere / Resolve)", fcpx_xml: "FCPXML", edl: "EDL (CMX 3600)", otio: "OpenTimelineIO",
};
type Draft = { enabled: boolean; speaker_name: string; voice_id: string };
const draftOf = (t: TimelineTrack): Draft => ({ enabled: t.enabled, speaker_name: t.speaker_name || t.name, voice_id: t.voice_id ?? "" });

/** งานไทม์ไลน์ที่เพิ่งนำเข้า: อัปโหลดไฟล์ที่ขาด เลือกว่าแทร็กไหนเป็นบทพูด ตั้งชื่อผู้พูด (ชื่อเดียวกัน = คนเดียวกัน)
 * และเสียงพากย์จากคลัง แล้วเริ่มถอดเสียง */
export default function TimelineSetup({ job, onChanged }: { job: Job; onChanged: () => void }) {
  const [info, setInfo] = useState<TimelineInfo | null>(null);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [voices, setVoices] = useState<LibraryVoice[]>([]);
  const [busy, setBusy] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [message, setMessage] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const mediaRef = useRef<HTMLInputElement>(null);

  const apply = (tl: TimelineInfo) => {
    setInfo(tl);
    setDrafts(Object.fromEntries(tl.tracks.map((t) => [t.index, draftOf(t)])));
  };
  useEffect(() => {
    api.getTimeline(job.id).then((s) => apply(s.timeline)).catch((e) => setMessage({ kind: "error", text: e.message }));
    api.listVoices().then((v) => setVoices(v.filter((x) => x.status === "ready"))).catch(() => setVoices([]));
  }, [job.id]);

  if (!info) {
    return <main className="page">{message ? <div className="alert error" role="alert">{message.text}</div> : <div className="empty">{tx("กำลังโหลด...")}</div>}</main>;
  }
  const tracks = info.tracks.filter((t) => t.clips.length > 0);
  const set = (i: number, patch: Partial<Draft>) => setDrafts({ ...drafts, [i]: { ...drafts[i], ...patch } });
  const changed = tracks.filter((t) => JSON.stringify(drafts[t.index]) !== JSON.stringify(draftOf(t)));
  const enabled = tracks.filter((t) => drafts[t.index]?.enabled);
  // ชื่อเดียวกัน = ผู้พูดคนเดียวกัน (ตาม API) สีตามลำดับชื่อที่เจอ
  const names = [...new Set(enabled.map((t) => drafts[t.index].speaker_name.trim()))];

  const save = async (): Promise<boolean> => {
    if (!changed.length) return true;
    const body: TrackSetup[] = changed.map((t) => {
      const d = drafts[t.index];
      return { index: t.index, enabled: d.enabled, speaker_name: d.speaker_name.trim(), voice_id: d.voice_id || "" };
    });
    try {
      apply((await api.setupTimeline(job.id, body)).timeline);
      return true;
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
      return false;
    }
  };
  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key); setMessage(null);
    try { await fn(); } finally { setBusy(""); }
  };
  const uploadMissing = (files: File[]) => run("media", async () => {
    if (!files.length) return;
    setProgress(0);
    try {
      const s = await uploadTimelineMedia(job.id, files, setProgress).promise;
      setInfo(s.timeline);
      setMessage({ kind: "info", text: s.timeline.missing.length ? tx("ยังขาดอีก {0} ไฟล์", { 0: s.timeline.missing.length }) : tx("ไฟล์สื่อครบแล้ว") });
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally {
      setProgress(null);
      if (mediaRef.current) mediaRef.current.value = "";
    }
  });
  const start = () => run("start", async () => {
    if (!(await save())) return;
    try { await api.startTimeline(job.id); onChanged(); }
    catch (e) { setMessage({ kind: "error", text: (e as Error).message }); }
  });

  return (
    <main className="page" style={{ maxWidth: 1080 }}>
      <div className="page-head">
        <div>
          <Link href="/jobs" className="dim" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><ArrowLeft />{tx("งานทั้งหมด")}</Link>
          <h1 style={{ margin: "6px 0 0" }}>{info.name || job.filename}</h1>
          <span className="muted">
            {FORMAT_LABEL[info.format] ?? info.format} · {info.fps} fps{info.drop_frame ? " drop-frame" : ""} · {info.sample_rate / 1000}  {tx("kHz · เริ่ม")} {info.start_tc}  {tx("· ยาว")} {info.duration_tc}
          </span>
        </div>
        <div className="row" style={{ gap: 10 }}>
          {changed.length > 0 && <button type="button" className="btn" disabled={!!busy} onClick={() => run("save", async () => { await save(); })}>{tx("บันทึก")}</button>}
          <button type="button" className="btn primary" disabled={!!busy || info.missing.length > 0 || enabled.length === 0} onClick={start}
            title={info.missing.length ? tx("อัปโหลดไฟล์สื่อให้ครบก่อน") : enabled.length === 0 ? tx("เปิดอย่างน้อยหนึ่งแทร็กเป็นบทพูด") : undefined}>
            {busy === "start" ? tx("กำลังเริ่ม...") : tx("เริ่มถอดเสียงและแปล")}<ArrowRight />
          </button>
        </div>
      </div>

      {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
      {info.warnings.map((w) => <div key={w} className="alert info">{w}</div>)}

      {info.missing.length > 0 && (
        <section className="card" aria-labelledby="missing-title">
          <h2 id="missing-title" style={{ margin: 0 }}>{tx("ขาดไฟล์สื่อ")} {info.missing.length}  {tx("ไฟล์")}</h2>
          <span className="muted">{tx("อัปโหลดไฟล์ชื่อตรงกับที่ไทม์ไลน์อ้างถึง (หรือ zip ที่รวมไว้) ระบบจับคู่จากชื่อไฟล์")}</span>
          <ul className="mono" style={{ margin: 0, paddingLeft: 20, fontSize: 13 }}>{info.missing.map((m) => <li key={m}>{m}</li>)}</ul>
          <div className="row" style={{ gap: 12 }}>
            <input ref={mediaRef} type="file" multiple aria-label={tx("อัปโหลดไฟล์สื่อที่ขาด")} disabled={!!busy}
              onChange={(e) => uploadMissing(Array.from(e.target.files ?? []))} />
            {progress !== null && (
              <div style={{ flex: "1 1 200px", display: "flex", alignItems: "center", gap: 10 }}>
                <div className="progress" style={{ flex: 1 }}><div style={{ width: `${progress * 100}%` }} /></div>
                <span className="mono">{Math.round(progress * 100)}%</span>
              </div>
            )}
          </div>
        </section>
      )}

      <section className="card" aria-labelledby="tracks-title">
        <h2 id="tracks-title" style={{ margin: 0 }}>{tx("แทร็กเสียง")}</h2>
        <span className="muted" style={{ fontSize: 14 }}>
          
          {tx("เปิดเฉพาะแทร็กที่เป็นบทพูด (เพลงและเสียงประกอบปิดไว้ จะอยู่ในเสียงรวมตามเดิม) · ตั้งชื่อเดียวกันให้แทร็กที่เป็นคนเดียวกัน · ไม่เลือกเสียง = โคลนเสียงต้นฉบับของแทร็กนั้น")}
        </span>
        <div className="table-wrap">
          <table className="ledger">
            <thead><tr><th>{tx("แทร็ก")}</th><th>{tx("บทพูด")}</th><th>{tx("ผู้พูด")}</th><th>{tx("เสียงพากย์")}</th><th>{tx("คลิป")}</th></tr></thead>
            <tbody>
              {tracks.map((t) => {
                const d = drafts[t.index];
                const missing = t.clips.filter((c) => !c.file).length;
                const color = d.enabled ? speakerColor(d.speaker_name.trim(), names) : "var(--line)";
                return (
                  <tr key={t.index}>
                    <td>
                      <span className="mono" style={{ borderLeft: `4px solid ${color}`, paddingLeft: 8 }}>A{t.index}</span>
                      <div className="dim">{t.name}</div>
                      {t.duplicate_of && <div className="dim">{tx("ซ้ำกับ A")}{t.duplicate_of}  {tx("(สเตอริโอ)")}</div>}
                    </td>
                    <td><input type="checkbox" aria-label={tx("A{0} เป็นบทพูด", { 0: t.index })} checked={d.enabled}
                      onChange={(e) => set(t.index, { enabled: e.target.checked })} /></td>
                    <td><input className="input" aria-label={tx("ชื่อผู้พูดของ A{0}", { 0: t.index })} value={d.speaker_name} disabled={!d.enabled}
                      maxLength={60} list="tl-speakers" onChange={(e) => set(t.index, { speaker_name: e.target.value })} /></td>
                    <td>
                      <select className="select" aria-label={tx("เสียงพากย์ของ A{0}", { 0: t.index })} value={d.voice_id} disabled={!d.enabled}
                        onChange={(e) => set(t.index, { voice_id: e.target.value })}>
                        <option value="">{tx("โคลนเสียงต้นฉบับ")}</option>
                        {voices.map((v) => <option key={v.id} value={v.id}>{v.name}{v.gender ? ` (${tx(GENDER_LABEL[v.gender])})` : ""}{v.actor ? ` · ${v.actor}` : ""}</option>)}
                      </select>
                    </td>
                    <td>
                      {t.clips.length}  {tx("คลิป")}
                      <div className="dim">{t.clips[0].start_tc} – {t.clips[t.clips.length - 1].end_tc}</div>
                      {missing > 0 && <div style={{ color: "var(--danger)" }}>{tx("ไฟล์หาย")} {missing}  {tx("คลิป")}</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <datalist id="tl-speakers">{names.map((n) => <option key={n} value={n} />)}</datalist>
        <span className="dim">{tx("ผู้พูด")} {names.length}  {tx("คน จาก")} {enabled.length}  {tx("แทร็ก")}</span>
      </section>
    </main>
  );
}
