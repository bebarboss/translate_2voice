"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, fileUrl, type Gender, type Job, type Utterance } from "@/lib/api";
import { GENDER_LABEL, fmtDuration, fmtTime, langName, speakerColor } from "@/lib/format";
import { NEW_SPEAKER, useTranscript, type Transcript } from "@/lib/useTranscript";
import SpeakerLanes from "./SpeakerLanes";
import { PreviewButton, usePreview } from "./VoicePreview";
import { ArrowLeft, XIcon } from "./Icons";

const GENDERS: Gender[] = ["", "male", "female"];
const MIN_SOLO_SEC = 3; // ตรงกับเกณฑ์ของ API (main.speaker_to_library)

/** เวลาที่แต่ละคนพูดคนเดียว (ไม่มีคนอื่นพูดทับเกิน 0.2 วินาที) ตามบทที่กำลังแก้ ส่วนนี้คือเสียงที่บันทึกลงคลังได้ */
function soloSeconds(tr: Transcript): Record<string, number> {
  const ds = tr.sorted.map((u) => tr.draftOf(u));
  const out: Record<string, number> = {};
  for (const d of ds) {
    const overlapped = ds.some((o) => o.speaker !== d.speaker && Math.min(d.end, o.end) - Math.max(d.start, o.start) > 0.2);
    if (!overlapped) out[d.speaker] = (out[d.speaker] ?? 0) + d.end - d.start;
  }
  return out;
}

/** งานเก็บเสียงเข้าคลัง: คลิปที่มีหลายคนพูด แสดงแบบหน้าตรวจบท (คลิป + เลเยอร์ของแต่ละคน + รายการประโยค)
 *  ผู้ใช้แก้การแยกผู้พูด (ลากบล็อก ตัด รวมตัวละคร) แล้วกดบันทึกเสียงของแต่ละคนลงคลังที่ท้ายเลเยอร์ */
export default function LibraryJobView({ job, onChanged }: { job: Job; onChanged: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const tr = useTranscript(job, onChanged, () => videoRef.current?.currentTime ?? 0);
  const { lines, sorted, speakers, dirty, busy, setBusy, message, setMessage } = tr;
  const [t, setT] = useState(0);
  const [duration, setDuration] = useState(job.duration ?? 0);
  const [follow, setFollow] = useState(true);
  const [picked, setPicked] = useState<number | null>(null);
  const [saving, setSaving] = useState<string | null>(null); // ตัวละครที่เปิดกล่องบันทึกลงคลังอยู่
  const listRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<Record<number, HTMLDivElement | null>>({});

  const lang = job.detected_lang || job.source_lang;
  const notThai = !!lang && lang !== "th";
  const total = duration || (sorted.length ? sorted[sorted.length - 1].end + 1 : 1);
  const solo = useMemo(() => soloSeconds(tr), [tr]);

  const active = useMemo(() => {
    let cur: Utterance | null = null;
    for (const u of sorted) if (t >= u.start) cur = u;
    return cur;
  }, [sorted, t]);
  const speaking = active && t <= active.end ? active : null;

  useEffect(() => {
    if (!dirty.length) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty.length]);

  // เลื่อนรายการให้ประโยคที่กำลังพูดอยู่ในกรอบ (เลื่อนเฉพาะกล่องรายการ)
  useEffect(() => {
    if (!follow || !active || !listRef.current) return;
    const box = listRef.current;
    const el = lineRefs.current[active.id];
    if (!el) return;
    const top = el.offsetTop - box.offsetTop;
    if (top < box.scrollTop || top + el.offsetHeight > box.scrollTop + box.clientHeight) {
      box.scrollTo({ top: Math.max(0, top - 12), behavior: "smooth" });
    }
  }, [active, follow]);

  const seek = useCallback((sec: number) => {
    const v = videoRef.current;
    if (v) v.currentTime = sec + 0.01;
    setT(sec + 0.01);
  }, []);

  const onSave = async () => {
    setBusy("save");
    setMessage(null);
    try {
      const n = dirty.length;
      await tr.saveLines();
      setMessage({ kind: "info", text: n ? `บันทึกการแก้ ${n} ประโยคแล้ว` : "ไม่มีอะไรเปลี่ยน" });
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally { setBusy(""); }
  };

  const slot = (s: string) => {
    const saved = job.saved_voices?.[s];
    if (saved) {
      return <Link href="/voices" className="btn small lane-voice-btn" title="บันทึกเสียงนี้ลงคลังแล้ว ดูในคลังเสียง">✓ ในคลัง</Link>;
    }
    const sec = solo[s] ?? 0;
    const why = notThai ? "เสียงในคลังต้องเป็นภาษาไทย"
      : sec < MIN_SOLO_SEC ? `พูดคนเดียวแค่ ${sec.toFixed(1)} วินาที ต้องมีอย่างน้อย ${MIN_SOLO_SEC} วินาที` : "";
    return (
      <button type="button" className="btn small lane-voice-btn" disabled={!!why || !!busy} onClick={() => setSaving(s)}
        title={why || `บันทึกเสียงของ${tr.label(s)}ลงคลัง (ใช้ช่วงที่พูดคนเดียว ${Math.round(sec)} วินาที)`}>
        บันทึกลงคลัง
      </button>
    );
  };

  return (
    <main className="page wide">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row" style={{ gap: 14 }}>
          <Link href="/voices" className="btn small" aria-label="กลับหน้าคลังเสียง"><ArrowLeft /></Link>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
            <span style={{ fontSize: 17, fontWeight: 600, wordBreak: "break-all" }}>แยกเสียงเข้าคลัง · {job.filename}</span>
            <span className="dim">
              {langName(lang)} · {speakers.length} คน · {sorted.length} ประโยค · {fmtDuration(job.duration)}
            </span>
          </div>
        </div>
        <button type="button" className="btn" onClick={onSave} disabled={!!busy || !dirty.length}>
          {busy === "save" ? "กำลังบันทึก..." : `บันทึกการแก้${dirty.length ? ` (${dirty.length})` : ""}`}
        </button>
      </div>

      <div className="alert info">
        ฟังแล้วแก้ให้แต่ละเลเยอร์เป็นเสียงของคนเดียว (ลากบล็อกไปเลเยอร์อื่น ตัด หรือรวมตัวละคร) ตั้งชื่อจากชื่อเลเยอร์
        แล้วกด &ldquo;บันทึกลงคลัง&rdquo; ท้ายเลเยอร์ของคนที่ต้องการ ระบบใช้เฉพาะช่วงที่คนนั้นพูดคนเดียว
      </div>
      {notThai && (
        <div className="alert error" role="alert">
          คลิปนี้เป็นภาษา{langName(lang)} เสียงในคลังต้องเป็นภาษาไทย (ระบบพากย์ต้องรู้ว่าเสียงตัวอย่างพูดอะไร) ใช้คลิปภาษาไทยแทน
        </div>
      )}
      {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}

      <div className="split">
        <section className="main" aria-label="คลิป">
          <div className="video-box">
            <video ref={videoRef} src={fileUrl.source(job.id)} controls preload="metadata" playsInline
              onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
              onSeeked={(e) => setT(e.currentTarget.currentTime)}
              onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
              onPlay={() => setPicked(null)} />
            {speaking && speaking.source && (
              <div className="caption"><span>{tr.label(tr.draftOf(speaking).speaker)}: {speaking.source}</span></div>
            )}
          </div>
          <div className="row dim" style={{ justifyContent: "space-between" }}>
            <span>ซับบนภาพคือคำที่ถอดได้ และคนที่พูดตามเลเยอร์ปัจจุบัน</span>
            <span className="mono">{fmtTime(t)} / {fmtTime(total)}</span>
          </div>

          <SpeakerLanes job={job} tr={tr} total={total} t={t} highlight={picked ?? speaking?.id ?? null}
            onPick={(u) => { setPicked(u.id); seek(u.start); }} onRetimed={(sec) => seek(Math.max(0, sec - 1))} onSeek={seek}
            voiceSlot={slot} voiceHead={<span className="dim lane-voice-btn">เสียงในคลัง</span>} />
        </section>

        <aside className="side card" aria-label="ประโยคที่ถอดได้" style={{ padding: 0, gap: 0, overflow: "hidden" }}>
          <div className="row" style={{ justifyContent: "space-between", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
            <h2 style={{ fontSize: 16 }}>ประโยคที่ถอดได้</h2>
            <label className="row" style={{ gap: 8, fontSize: 13, color: "var(--text-2)", cursor: "pointer" }}>
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)}
                style={{ width: 18, height: 18, accentColor: "var(--accent)" }} />
              เลื่อนตามคลิป
            </label>
          </div>
          <div className="lines" ref={listRef}>
            {lines === null ? <div className="empty">กำลังโหลด...</div>
              : sorted.length === 0 ? <div className="empty">ไม่พบเสียงพูดในคลิปนี้</div>
              : sorted.map((u) => {
                const d = tr.draftOf(u);
                return (
                  <div key={u.id} ref={(el) => { lineRefs.current[u.id] = el; }}
                    className={`line${active?.id === u.id ? " active" : ""}${speaking?.id === u.id ? " speaking" : ""}`}>
                    <div className="row" style={{ gap: 8 }}>
                      <button type="button" className="time-btn" onClick={() => seek(u.start)} aria-label={`ไปที่ ${fmtTime(u.start)}`}>
                        {fmtTime(u.start)}
                      </button>
                      <span className="swatch" style={{ background: speakerColor(d.speaker, speakers) }} />
                      <label className="sr-only" htmlFor={`lspk-${u.id}`}>คนพูดประโยคที่ {u.id}</label>
                      <select id={`lspk-${u.id}`} className="spk-select" value={d.speaker} disabled={busy === "edit"}
                        onChange={(e) => tr.changeSpeaker(u, e.target.value)}>
                        {speakers.map((s) => <option key={s} value={s}>{tr.label(s)}</option>)}
                        <option value={NEW_SPEAKER}>+ คนใหม่</option>
                      </select>
                      <span className="dim" style={{ marginLeft: "auto" }}>{(d.end - d.start).toFixed(1)} วิ</span>
                    </div>
                    <span>{u.source || <span className="dim">(ไม่มีคำที่ถอดได้)</span>}</span>
                  </div>
                );
              })}
          </div>
        </aside>
      </div>

      {saving && (
        <SaveDialog job={job} tr={tr} speaker={saving} solo={solo[saving] ?? 0}
          onClose={() => setSaving(null)} onDone={() => { setSaving(null); onChanged(); }} />
      )}
    </main>
  );
}

/** กล่องบันทึกเสียงของคนหนึ่งลงคลัง: ตั้งชื่อ เลือกเพศ ฟังเสียงที่แยกได้ แล้วยืนยัน
 *  บันทึกการแก้ที่ค้างก่อน เพราะ API ตัดเสียงจากบทที่บันทึกแล้ว */
function SaveDialog({ job, tr, speaker, solo, onClose, onDone }: {
  job: Job;
  tr: Transcript;
  speaker: string;
  solo: number;
  onClose: () => void;
  onDone: () => void;
}) {
  const [name, setName] = useState(tr.names[speaker] ?? "");
  const [gender, setGender] = useState<Gender>("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const preview = usePreview();
  const label = tr.label(speaker);

  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, []);

  const confirm = async () => {
    const n = name.trim();
    if (!n) return;
    setWorking(true);
    setError("");
    try {
      await tr.saveLines();
      if (n !== (tr.names[speaker] ?? "")) await tr.renameSpeaker(speaker, n);
      await api.speakerToLibrary(job.id, speaker, { name: n, gender, tone: "", description: "", categories: [] });
      tr.setMessage({ kind: "info", text: `เพิ่ม "${n}" เข้าคลังแล้ว กำลังเตรียมเสียง ดูสถานะได้ที่หน้าคลังเสียง` });
      onDone();
    } catch (e) {
      setError((e as Error).message);
      setWorking(false);
    }
  };

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="save-title" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <h2 id="save-title" className="row" style={{ gap: 8, fontSize: 17 }}>
            <span className="swatch" style={{ background: speakerColor(speaker, tr.speakers) }} />บันทึกเสียงของ{label}ลงคลัง
          </h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="ปิด"><XIcon /></button>
        </div>
        <div className="drawer-tools" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <span className="dim">ใช้ช่วงที่พูดคนเดียว {Math.round(solo)} วินาที ระบบเลือกท่อนที่ชัดที่สุด 3–10 วินาทีเป็นเสียงตัวอย่าง และถอดข้อความให้</span>
          <PreviewButton url={fileUrl.stem(job.id, speaker)} playing={preview.playing} onToggle={preview.toggle}
            label="ฟังเสียงที่แยกได้ตอนแรก" />
          <div className="field">
            <label htmlFor="save-name">ชื่อเสียง</label>
            <input id="save-name" className="input" maxLength={80} autoFocus placeholder="เช่น โดราเอมอน"
              value={name} onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") confirm(); }} />
          </div>
          <div className="field">
            <span className="label">เพศ</span>
            <div className="seg" role="group" aria-label="เพศของเสียง" style={{ alignSelf: "flex-start" }}>
              {GENDERS.map((g) => (
                <button key={g || "auto"} type="button" aria-pressed={gender === g} onClick={() => setGender(g)}>
                  {g ? GENDER_LABEL[g] : "ให้ระบบเดา"}
                </button>
              ))}
            </div>
          </div>
          {tr.dirty.length > 0 && <span className="dim">มีการแก้ {tr.dirty.length} ประโยคที่ยังไม่บันทึก ระบบจะบันทึกให้ก่อน</span>}
          {error && <div className="alert error" role="alert">{error}</div>}
          <button type="button" className="btn primary" onClick={confirm} disabled={working || !name.trim()}>
            {working ? "กำลังบันทึก..." : "บันทึกลงคลัง"}
          </button>
        </div>
      </aside>
    </div>
  );
}
