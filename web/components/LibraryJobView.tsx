"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, fileUrl, type Gender, type Job, type LibraryVoice, type Mood, type SpeakerSave, type Utterance } from "@/lib/api";
import { GENDER_LABEL, MOODS, MOOD_LABEL, TONES, fmtDuration, fmtTime, langName, speakerColor } from "@/lib/format";
import { useAuth } from "@/lib/useAuth";
import { NEW_SPEAKER, useTranscript, type Transcript } from "@/lib/useTranscript";
import CategoryPicker from "./CategoryPicker";
import SpeakerLanes from "./SpeakerLanes";
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

  const { loaded, config, user } = useAuth();
  const canSave = loaded && (!config?.auth || !!user?.admin);
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
    const sec = solo[s] ?? 0;
    const why = !canSave ? "บันทึกลงคลังเสียงได้เฉพาะผู้ดูแลระบบ"
      : notThai ? "เสียงในคลังต้องเป็นภาษาไทย"
      : sec < MIN_SOLO_SEC ? `พูดคนเดียวแค่ ${sec.toFixed(1)} วินาที ต้องมีอย่างน้อย ${MIN_SOLO_SEC} วินาที` : "";
    return (
      <button type="button" className="btn small lane-voice-btn" disabled={!!why || !!busy} onClick={() => setSaving(s)}
        title={why || (saved ? "บันทึกลงคลังแล้ว กดเพื่อแทนที่เสียงหรือเพิ่มเป็นอารมณ์"
          : `บันทึกเสียงของ${tr.label(s)}ลงคลัง (พูดคนเดียว ${Math.round(sec)} วินาที)`)}>
        {saved ? "✓ ในคลัง" : "บันทึกลงคลัง"}
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
        <SaveDialog job={job} tr={tr} speaker={saving}
          onClose={() => setSaving(null)} onDone={() => { setSaving(null); onChanged(); }} />
      )}
    </main>
  );
}

const GOOD_SEC = 8; // พูดรวมน้อยกว่านี้ ระบบมีท่อนให้เลือกน้อย เสียงตัวอย่างมักไม่ดี
const LOW_QUALITY = 2; // คะแนนความสะอาดต่ำกว่านี้ = มีเพลงหรือเสียงรบกวนทับมาก (เต็ม 4.5)
const TARGETS: { value: SpeakerSave["target"]; label: string }[] = [
  { value: "new", label: "เสียงใหม่" },
  { value: "replace", label: "แทนที่เสียงเดิม" },
  { value: "mood", label: "เพิ่มเป็นอารมณ์" },
];

/** กล่องบันทึกเสียงของคนหนึ่งลงคลัง
 *  เลือกประโยคที่ใช้ (ฟังได้ทีละประโยค เห็นคะแนนความสะอาด) เลือกปลายทาง (เสียงใหม่ / แทนเสียงเดิม / อารมณ์ของเสียงเดิม)
 *  และลดเสียงรบกวน บันทึกการแก้ที่ค้างก่อน เพราะ API ตัดเสียงจากบทที่บันทึกแล้ว */
function SaveDialog({ job, tr, speaker, onClose, onDone }: {
  job: Job;
  tr: Transcript;
  speaker: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const saved = job.saved_voices?.[speaker];
  const label = tr.label(speaker);
  const [target, setTarget] = useState<SpeakerSave["target"]>(saved ? "replace" : "new");
  const [voiceId, setVoiceId] = useState(saved ?? "");
  const [mood, setMood] = useState<Mood>("happy");
  const [name, setName] = useState(tr.names[speaker] ?? "");
  const [gender, setGender] = useState<Gender>("");
  const [tone, setTone] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const [description, setDescription] = useState("");
  const [denoise, setDenoise] = useState(false);
  const [voices, setVoices] = useState<LibraryVoice[]>([]);
  const [quality, setQuality] = useState<Record<string, number | null>>({});
  const [playing, setPlaying] = useState<number | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // ประโยคของคนนี้ตามบทที่กำลังแก้ ประโยคที่คนอื่นพูดทับใช้ไม่ได้ (เกณฑ์เดียวกับ API)
  const rows = useMemo(() => {
    const all = tr.sorted.map((u) => ({ u, d: tr.draftOf(u) }));
    return all.filter((x) => x.d.speaker === speaker).map((x) => ({
      ...x,
      overlapped: all.some((o) => o.d.speaker !== speaker && Math.min(x.d.end, o.d.end) - Math.max(x.d.start, o.d.start) > 0.2),
    }));
  }, [tr, speaker]);
  const [picked, setPicked] = useState<Set<number>>(() => new Set(rows.filter((r) => !r.overlapped).map((r) => r.u.id)));

  useEffect(() => {
    api.listVoices().then((v) => setVoices(v.sort((a, b) => a.name.localeCompare(b.name, "th")))).catch(() => {});
    api.lineQuality(job.id).then(setQuality).catch(() => {});
  }, [job.id]);

  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("keydown", esc); audioRef.current?.pause(); };
  }, []);

  const chosen = rows.filter((r) => picked.has(r.u.id) && !r.overlapped);
  const seconds = chosen.reduce((a, r) => a + r.d.end - r.d.start, 0);
  const scores = chosen.map((r) => quality[String(r.u.id)]).filter((q): q is number => q != null);
  const avgQ = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;

  const toggle = (id: number) => setPicked((p) => {
    const n = new Set(p);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

  // ฟังทีละประโยคจากเสียงพูดที่แยกเพลงออกแล้ว (#t=เริ่ม,จบ ให้เบราว์เซอร์หยุดเองที่ปลายประโยค)
  const play = (id: number, start: number, end: number) => {
    audioRef.current?.pause();
    if (playing === id) { setPlaying(null); return; }
    const a = new Audio(`${fileUrl.stem(job.id, "vocals")}#t=${start.toFixed(2)},${end.toFixed(2)}`);
    a.onpause = () => setPlaying((p) => (p === id ? null : p));
    audioRef.current = a;
    setPlaying(id);
    a.play().catch(() => setPlaying(null));
  };

  const voice = voices.find((v) => v.id === voiceId);
  const ready = !working && seconds >= MIN_SOLO_SEC
    && (target === "new" ? !!name.trim() : !!voice);

  const confirm = async () => {
    if (!ready) return;
    setWorking(true);
    setError("");
    try {
      await tr.saveLines();
      const n = name.trim();
      if (target === "new" && n !== (tr.names[speaker] ?? "")) await tr.renameSpeaker(speaker, n);
      await api.speakerToLibrary(job.id, speaker, {
        target, voice_id: target === "new" ? undefined : voiceId, mood: target === "mood" ? mood : undefined,
        lines: chosen.map((r) => r.u.id), denoise,
        name: n, gender, tone: tone.trim(), description: description.trim(), categories,
      });
      const what = target === "new" ? `เพิ่ม "${n}" เข้าคลังแล้ว`
        : target === "replace" ? `แทนที่เสียงของ "${voice?.name}" แล้ว`
        : `เพิ่มอารมณ์${MOOD_LABEL[mood]}ให้ "${voice?.name}" แล้ว`;
      tr.setMessage({ kind: "info", text: `${what} กำลังเตรียมเสียง ดูสถานะได้ที่หน้าคลังเสียง` });
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

        <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: "0 20px 20px", overflowY: "auto" }}>
          <div className="seg" role="group" aria-label="บันทึกเป็น" style={{ alignSelf: "flex-start" }}>
            {TARGETS.map((x) => (
              <button key={x.value} type="button" aria-pressed={target === x.value} onClick={() => setTarget(x.value)}>{x.label}</button>
            ))}
          </div>

          {target === "new" ? (
            <>
              <div className="field">
                <label htmlFor="save-name">ชื่อเสียง</label>
                <input id="save-name" className="input" maxLength={80} placeholder="เช่น โดราเอมอน"
                  value={name} onChange={(e) => setName(e.target.value)} />
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
              <div className="field">
                <label htmlFor="save-tone">โทนเสียง</label>
                <input id="save-tone" className="input" list="save-tones" maxLength={80} placeholder="เช่น สดใส เสียงเด็ก"
                  value={tone} onChange={(e) => setTone(e.target.value)} />
                <datalist id="save-tones">{TONES.map((t) => <option key={t} value={t} />)}</datalist>
              </div>
              <div className="field">
                <span className="label" id="save-cat">หมวดหมู่</span>
                <CategoryPicker id="save-cat" value={categories} onChange={setCategories}
                  known={[...new Set(voices.flatMap((v) => v.categories ?? []))]} />
              </div>
              <div className="field">
                <label htmlFor="save-desc">รายละเอียด (ไม่ใส่ก็ได้)</label>
                <textarea id="save-desc" className="textarea" rows={2} maxLength={1000}
                  value={description} onChange={(e) => setDescription(e.target.value)} />
              </div>
            </>
          ) : (
            <>
              <div className="field">
                <label htmlFor="save-voice">เสียงในคลัง</label>
                <select id="save-voice" className="input" value={voiceId} onChange={(e) => setVoiceId(e.target.value)}>
                  <option value="">เลือกเสียง…</option>
                  {voices.map((v) => <option key={v.id} value={v.id}>{v.name}{v.id === saved ? " (บันทึกจากเลเยอร์นี้)" : ""}</option>)}
                </select>
              </div>
              {target === "mood" ? (
                <div className="field">
                  <label htmlFor="save-mood">อารมณ์</label>
                  <select id="save-mood" className="input" value={mood} onChange={(e) => setMood(e.target.value as Mood)}>
                    {MOODS.map((m) => (
                      <option key={m} value={m}>
                        {MOOD_LABEL[m]}{voice?.moods?.some((x) => x.mood === m) ? " (มีอยู่แล้ว จะแทนที่)" : ""}
                      </option>
                    ))}
                  </select>
                  <span className="dim">เลือกเฉพาะประโยคที่พูดด้วยอารมณ์นี้</span>
                </div>
              ) : (
                <span className="dim">เตรียมเสียงตัวอย่างใหม่จากประโยคที่เลือก ชื่อ รูป และรายละเอียดเดิมไม่เปลี่ยน งานที่ใช้เสียงนี้ไม่ต้องเลือกใหม่</span>
              )}
            </>
          )}

          <div className="field">
            <span className="label">ประโยคที่ใช้ ({chosen.length}/{rows.length} · {seconds.toFixed(1)} วินาที)</span>
            <span className="dim">เอาติ๊กออกจากประโยคที่ไม่ใช่เสียงคนนี้ หรือมีเพลงดังทับ · ความสะอาดเต็ม 4.5 ต่ำกว่า {LOW_QUALITY} = มีเพลงทับมาก</span>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 280, overflowY: "auto" }}>
              {rows.map(({ u, d, overlapped }) => {
                const q = quality[String(u.id)];
                return (
                  <div key={u.id} className="row" style={{ gap: 8, alignItems: "flex-start", opacity: overlapped ? 0.5 : 1 }}>
                    <input type="checkbox" style={{ marginTop: 6 }} checked={!overlapped && picked.has(u.id)} disabled={overlapped}
                      onChange={() => toggle(u.id)} aria-label={`ใช้ประโยค ${fmtTime(d.start)}`} />
                    <button type="button" className="btn small" onClick={() => play(u.id, d.start, d.end)}
                      aria-label={playing === u.id ? "หยุด" : `ฟังประโยค ${fmtTime(d.start)}`}>{playing === u.id ? "■" : "▶"}</button>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <span className="mono dim">{fmtTime(d.start)} · {(d.end - d.start).toFixed(1)} วิ </span>
                      {q != null && <span className={`badge ${q < LOW_QUALITY ? "warn" : "done"}`}>สะอาด {q.toFixed(1)}</span>}
                      {overlapped && <span className="badge queued">มีคนพูดทับ</span>}
                      <span style={{ display: "block" }}>{u.source || <span className="dim">(ไม่มีคำที่ถอดได้)</span>}</span>
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {seconds < MIN_SOLO_SEC ? (
            <div className="alert error">ประโยคที่เลือกยาวรวม {seconds.toFixed(1)} วินาที ต้องมีอย่างน้อย {MIN_SOLO_SEC} วินาที</div>
          ) : seconds < GOOD_SEC && (
            <div className="alert warn">เสียงรวมแค่ {seconds.toFixed(1)} วินาที ระบบมีท่อนให้เลือกน้อย เสียงตัวอย่างอาจไม่ดี ถ้ามีคลิปที่คนนี้พูดยาวกว่านี้จะดีกว่า</div>
          )}
          {avgQ != null && avgQ < LOW_QUALITY && (
            <div className="alert warn">
              ประโยคที่เลือกมีเสียงอื่นทับมาก (ความสะอาดเฉลี่ย {avgQ.toFixed(1)}) เสียงพากย์จะติดมาด้วย
              เอาติ๊กออกจากประโยคที่คะแนนต่ำ ให้เหลือเฉพาะประโยคที่สะอาด (3 ขึ้นไป) ได้ผลกว่าการลดเสียงรบกวน
            </div>
          )}

          <label className="check" style={{ justifyContent: "flex-start" }}>
            <input type="checkbox" checked={denoise} onChange={(e) => setDenoise(e.target.checked)} />
            <span>ลดเสียงรบกวนเพิ่ม (ช่วยกับเสียงซ่าหรือลม ไม่ช่วยเพลง เอฟเฟกต์ หรือเสียงคนอื่นที่ทับอยู่)</span>
          </label>

          {tr.dirty.length > 0 && <span className="dim">มีการแก้ {tr.dirty.length} ประโยคที่ยังไม่บันทึก ระบบจะบันทึกให้ก่อน</span>}
          {error && <div className="alert error" role="alert">{error}</div>}
          <button type="button" className="btn primary" onClick={confirm} disabled={!ready}>
            {working ? "กำลังบันทึก..." : target === "new" ? "บันทึกเป็นเสียงใหม่" : target === "replace" ? "แทนที่เสียง" : "เพิ่มอารมณ์"}
          </button>
        </div>
      </aside>
    </div>
  );
}
