"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, fileUrl, uploadVoice, uploadVoiceMood, type Gender, type LibraryVoice, type Mood, type VoiceMood } from "@/lib/api";
import { GENDER_LABEL, MOODS, MOOD_LABEL, TONES, VOICE_STAGE_LABEL, fmtWhen } from "@/lib/format";
import { PreviewButton, usePreview } from "@/components/VoicePreview";
import { UploadIcon } from "@/components/Icons";

const ACCEPT = ".wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.wma,.mp4,.mov,.mkv,.webm";
const GENDERS: Gender[] = ["", "male", "female"];

function GenderPicker({ value, onChange, label }: { value: Gender; onChange: (g: Gender) => void; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label} style={{ alignSelf: "flex-start" }}>
      {GENDERS.map((g) => (
        <button key={g || "auto"} type="button" aria-pressed={value === g} onClick={() => onChange(g)}>
          {g ? GENDER_LABEL[g] : "ให้ระบบเดา"}
        </button>
      ))}
    </div>
  );
}

function UploadCard({ onUploaded }: { onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [name, setName] = useState("");
  const [gender, setGender] = useState<Gender>("");
  const [tone, setTone] = useState("");
  const [rights, setRights] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const abortRef = useRef<(() => void) | null>(null);

  const pickFile = (f: File | undefined | null) => {
    setError("");
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPT.split(",").includes(ext)) {
      setError("รองรับไฟล์เสียง WAV, MP3, M4A, FLAC, OGG หรือวิดีโอ MP4, MOV, MKV, WEBM");
      return;
    }
    setFile(f);
    if (!name) setName(f.name.slice(0, f.name.lastIndexOf(".")).slice(0, 80));
  };

  const ready = !!file && !!name.trim() && rights && progress === null;

  const submit = async () => {
    if (!ready || !file) return;
    setError("");
    setProgress(0);
    try {
      const up = uploadVoice(file, { name: name.trim(), gender, tone: tone.trim() }, setProgress);
      abortRef.current = up.abort;
      await up.promise;
      setFile(null);
      setName("");
      setTone("");
      setGender("");
      onUploaded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setProgress(null);
      abortRef.current = null;
    }
  };

  return (
    <section className="card" aria-labelledby="add-voice">
      <h2 id="add-voice">เพิ่มเสียงเข้าคลัง</h2>
      <div className="grid-2">
        <label className={`dropzone${drag ? " drag" : ""}`} style={{ minHeight: 0, padding: 24 }}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); pickFile(e.dataTransfer.files[0]); }}>
          <span className="icon"><UploadIcon color="#FF8A4C" /></span>
          {file ? (
            <>
              <span style={{ fontSize: 16, fontWeight: 500, wordBreak: "break-all" }}>{file.name}</span>
              <span className="muted">{(file.size / 1024 / 1024).toFixed(1)} MB · คลิกเพื่อเปลี่ยนไฟล์</span>
            </>
          ) : (
            <>
              <span style={{ fontSize: 17, fontWeight: 500 }}>ลากคลิปเสียงภาษาไทยมาวาง</span>
              <span className="muted">หรือ <span style={{ color: "var(--accent)", textDecoration: "underline" }}>เลือกไฟล์</span></span>
              <span className="dim">เสียงคนเดียวพูดต่อเนื่อง 10 วินาทีขึ้นไป · ใช้แค่ 5 นาทีแรก</span>
            </>
          )}
          <input type="file" accept={ACCEPT} aria-label="เลือกไฟล์เสียง" onChange={(e) => pickFile(e.target.files?.[0])}
            disabled={progress !== null} />
        </label>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="field">
            <label htmlFor="v-name">ชื่อเสียง</label>
            <input id="v-name" className="input" maxLength={80} placeholder="เช่น พี่ต้น ผู้ชายวัยทำงาน"
              value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field">
            <span className="label">เพศ</span>
            <GenderPicker value={gender} onChange={setGender} label="เพศของเสียง" />
          </div>
          <div className="field">
            <label htmlFor="v-tone">โทนเสียง</label>
            <input id="v-tone" className="input" list="tones" maxLength={80} placeholder="เช่น ทุ้มลึก นุ่มนวล สดใส"
              value={tone} onChange={(e) => setTone(e.target.value)} />
            <datalist id="tones">{TONES.map((t) => <option key={t} value={t} />)}</datalist>
          </div>
        </div>
      </div>

      <label className="check" style={{ justifyContent: "flex-start" }}>
        <input type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)} />
        <span>ฉันเป็นเจ้าของเสียงนี้ หรือได้รับอนุญาตจากเจ้าของเสียงให้นำไปใช้พากย์แล้ว</span>
      </label>
      {error && <div className="alert error" role="alert">{error}</div>}
      <div className="row" style={{ justifyContent: "space-between" }}>
        {progress !== null ? (
          <div style={{ flex: "1 1 260px", display: "flex", alignItems: "center", gap: 12 }}>
            <div className="progress" style={{ flex: 1 }}><div style={{ width: `${progress * 100}%` }} /></div>
            <span className="mono">{Math.round(progress * 100)}%</span>
            <button type="button" className="btn small" onClick={() => abortRef.current?.()}>ยกเลิก</button>
          </div>
        ) : (
          <span className="dim">ระบบจะแยกเสียงรบกวนออก ตัดท่อนที่ชัดที่สุด 3–10 วินาที และถอดข้อความให้อัตโนมัติ</span>
        )}
        <button type="button" className="btn primary" onClick={submit} disabled={!ready}>
          {progress !== null ? "กำลังอัปโหลด..." : "เพิ่มเสียง"}
        </button>
      </div>
    </section>
  );
}

/** เสียงอารมณ์หนึ่ง: ฟัง แก้ข้อความ ลองใหม่ ลบ */
function MoodRow({ v, m, preview, run }: {
  v: LibraryVoice;
  m: VoiceMood;
  preview: ReturnType<typeof usePreview>;
  run: (fn: () => Promise<unknown>) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(m.text);
  useEffect(() => { if (!editing) setText(m.text); }, [m.text, editing]);
  const save = async () => {
    if (text.trim() && await run(() => api.updateVoiceMood(v.id, m.mood, text.trim()))) setEditing(false);
  };
  return (
    <div className="mood-row">
      <div className="row" style={{ gap: 8 }}>
        <span className="badge awaiting_review">{MOOD_LABEL[m.mood]}</span>
        {m.status === "processing" && <span className="badge running">{VOICE_STAGE_LABEL[m.stage] ?? m.stage}...</span>}
        {m.status === "failed" && <span className="badge failed">เตรียมเสียงไม่สำเร็จ</span>}
        {m.status === "ready" && m.quality != null && m.quality < 2.3 && <span className="badge warn">มีเสียงรบกวน</span>}
        <span className="row" style={{ marginLeft: "auto", gap: 6 }}>
          {m.status === "ready" && !editing && <button type="button" className="icon-btn" onClick={() => setEditing(true)}>แก้ข้อความ</button>}
          {m.status === "failed" && <button type="button" className="icon-btn" onClick={() => run(() => api.retryVoiceMood(v.id, m.mood))}>ลองใหม่</button>}
          {!(m.status === "processing" && m.stage !== "queued") && (
            <button type="button" className="icon-btn" aria-label={`ลบอารมณ์${MOOD_LABEL[m.mood]}`}
              onClick={() => window.confirm(`ลบเสียงอารมณ์${MOOD_LABEL[m.mood]}? ประโยคที่เลือกอารมณ์นี้จะกลับไปใช้เสียงปกติ`)
                && run(() => api.deleteVoiceMood(v.id, m.mood))}>ลบ</button>
          )}
          {m.status === "ready" && (
            <PreviewButton url={fileUrl.voiceMood(v.id, m.mood, v.updated_at)} playing={preview.playing} onToggle={preview.toggle} />
          )}
        </span>
      </div>
      {m.status === "failed" && m.error && <div className="alert error">{m.error}</div>}
      {editing ? (
        <div className="field">
          <label className="sr-only" htmlFor={`mx-${v.id}-${m.mood}`}>ข้อความที่พูดในเสียงอารมณ์นี้</label>
          <textarea id={`mx-${v.id}-${m.mood}`} className="textarea" rows={2} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row" style={{ gap: 6 }}>
            <button type="button" className="btn small primary" onClick={save}>บันทึก</button>
            <button type="button" className="btn small" onClick={() => setEditing(false)}>ยกเลิก</button>
          </div>
        </div>
      ) : m.status === "ready" && (
        <span className="dim">“{m.text}” · {m.duration?.toFixed(1)} วินาที</span>
      )}
    </div>
  );
}

/** เสียงตัวอย่างอารมณ์อื่นของเสียงนี้ เลือกใช้ทีละประโยคในหน้าแก้บท */
function MoodSection({ v, preview, run }: {
  v: LibraryVoice;
  preview: ReturnType<typeof usePreview>;
  run: (fn: () => Promise<unknown>) => Promise<boolean>;
}) {
  const missing = MOODS.filter((m) => !v.moods.some((x) => x.mood === m));
  const [mood, setMood] = useState<Mood | "">("");
  const [progress, setProgress] = useState<number | null>(null);
  const pick = missing.includes(mood as Mood) ? (mood as Mood) : missing[0];
  const add = (file: File | undefined) => {
    if (!file || !pick) return;
    setProgress(0);
    run(() => uploadVoiceMood(v.id, file, pick, setProgress).promise).finally(() => setProgress(null));
  };
  return (
    <div className="moods">
      <span className="label">เสียงอารมณ์อื่น</span>
      {v.moods.map((m) => <MoodRow key={m.mood} v={v} m={m} preview={preview} run={run} />)}
      {missing.length > 0 && (
        <div className="row" style={{ gap: 8 }}>
          <label className="sr-only" htmlFor={`am-${v.id}`}>อารมณ์ที่จะเพิ่ม</label>
          <select id={`am-${v.id}`} className="spk-select" value={pick} onChange={(e) => setMood(e.target.value as Mood)}
            disabled={progress !== null}>
            {missing.map((m) => <option key={m} value={m}>{MOOD_LABEL[m]}</option>)}
          </select>
          {progress !== null ? (
            <span className="mono">กำลังอัปโหลด {Math.round(progress * 100)}%</span>
          ) : (
            <label className="btn small" style={{ cursor: "pointer" }}>
              เพิ่มคลิปอารมณ์นี้
              <input type="file" accept={ACCEPT} className="sr-only"
                onChange={(e) => { add(e.target.files?.[0]); e.target.value = ""; }} />
            </label>
          )}
        </div>
      )}
      <span className="dim">ใช้คนพากย์คนเดิม พูดด้วยอารมณ์นั้น 10 วินาทีขึ้นไป แล้วเลือกอารมณ์ให้แต่ละประโยคในหน้าแก้บท</span>
    </div>
  );
}

function VoiceCard({ v, preview, onChanged }: {
  v: LibraryVoice;
  preview: ReturnType<typeof usePreview>;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(v.name);
  const [gender, setGender] = useState<Gender>(v.gender);
  const [tone, setTone] = useState(v.tone);
  const [text, setText] = useState(v.text);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (editing) return;
    setName(v.name); setGender(v.gender); setTone(v.tone); setText(v.text);
  }, [v, editing]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
      onChanged();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally { setBusy(false); }
  };

  const save = async () => {
    if (!name.trim() || !text.trim()) return setError("ชื่อและข้อความในเสียงต้องไม่ว่าง");
    const ok = await run(() => api.updateVoice(v.id, { name: name.trim(), gender, tone: tone.trim(), text: text.trim() }));
    if (ok) setEditing(false);
  };

  const remove = () => {
    if (window.confirm(`ลบเสียง "${v.name}" ออกจากคลัง? ตัวละครที่ใช้เสียงนี้จะกลับไปใช้เสียงต้นฉบับ`)) run(() => api.deleteVoice(v.id));
  };

  const audioUrl = fileUrl.voice(v.id, v.updated_at);
  return (
    <article className="card" style={{ gap: 12 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
          <span style={{ fontSize: 17, fontWeight: 600, wordBreak: "break-word" }}>{v.name}</span>
          <div className="row" style={{ gap: 6 }}>
            {v.gender && <span className="badge queued">{GENDER_LABEL[v.gender]}</span>}
            {v.tone && <span className="badge awaiting_review">{v.tone}</span>}
            {v.status === "processing" && <span className="badge running">{VOICE_STAGE_LABEL[v.stage] ?? v.stage}...</span>}
            {v.status === "failed" && <span className="badge failed">เตรียมเสียงไม่สำเร็จ</span>}
            {v.status === "ready" && v.quality != null && v.quality < 2.3 && <span className="badge warn">มีเสียงรบกวน</span>}
          </div>
        </div>
        {v.status === "ready" && <PreviewButton url={audioUrl} playing={preview.playing} onToggle={preview.toggle} />}
      </div>

      {v.status === "failed" && v.error && <div className="alert error">{v.error}</div>}

      {editing ? (
        <>
          <div className="field">
            <label htmlFor={`n-${v.id}`}>ชื่อเสียง</label>
            <input id={`n-${v.id}`} className="input" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field">
            <span className="label">เพศ</span>
            <div className="seg" role="group" aria-label="เพศของเสียง" style={{ alignSelf: "flex-start" }}>
              {(["male", "female", ""] as Gender[]).map((g) => (
                <button key={g || "none"} type="button" aria-pressed={gender === g} onClick={() => setGender(g)}>{GENDER_LABEL[g]}</button>
              ))}
            </div>
          </div>
          <div className="field">
            <label htmlFor={`t-${v.id}`}>โทนเสียง</label>
            <input id={`t-${v.id}`} className="input" list="tones-edit" maxLength={80} value={tone} onChange={(e) => setTone(e.target.value)} />
            <datalist id="tones-edit">{TONES.map((t) => <option key={t} value={t} />)}</datalist>
          </div>
          {v.status === "ready" && (
            <div className="field">
              <label htmlFor={`x-${v.id}`}>ข้อความที่พูดในเสียงตัวอย่าง</label>
              <textarea id={`x-${v.id}`} className="textarea" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
              <span className="dim">ฟังตัวอย่างแล้วแก้ให้ตรงทุกคำ ระบบพากย์จะเลียนเสียงได้แม่นขึ้น</span>
            </div>
          )}
        </>
      ) : v.status === "ready" && (
        <p style={{ margin: 0, fontSize: 15, lineHeight: 1.6 }}>“{v.text}”</p>
      )}

      {v.status === "ready" && (
        <span className="dim">
          {v.duration?.toFixed(1)} วินาที{v.pitch_hz ? ` · ระดับเสียง ${Math.round(v.pitch_hz)} Hz` : ""}
          {v.quality != null ? ` · ความชัด ${v.quality.toFixed(1)}/4.5` : ""} · เพิ่มเมื่อ {fmtWhen(v.created_at)}
        </span>
      )}
      {v.status === "ready" && !editing && <MoodSection v={v} preview={preview} run={run} />}
      {error && <div className="alert error" role="alert">{error}</div>}

      <div className="row" style={{ gap: 8 }}>
        {editing ? (
          <>
            <button type="button" className="btn small primary" onClick={save} disabled={busy}>{busy ? "กำลังบันทึก..." : "บันทึก"}</button>
            <button type="button" className="btn small" onClick={() => setEditing(false)} disabled={busy}>ยกเลิก</button>
          </>
        ) : (
          <>
            {v.status !== "processing" && <button type="button" className="btn small" onClick={() => setEditing(true)}>แก้ไข</button>}
            {v.status === "failed" && <button type="button" className="btn small" onClick={() => run(() => api.retryVoice(v.id))} disabled={busy}>ลองใหม่</button>}
            {!(v.status === "processing" && v.stage !== "queued") && (
              <button type="button" className="btn small danger" style={{ marginLeft: "auto" }} onClick={remove} disabled={busy}>ลบ</button>
            )}
          </>
        )}
      </div>
    </article>
  );
}

export default function VoicesPage() {
  const [voices, setVoices] = useState<LibraryVoice[] | null>(null);
  const [error, setError] = useState("");
  const preview = usePreview();

  const refresh = useCallback(() => {
    api.listVoices().then((v) => { setVoices(v); setError(""); }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // ระหว่างมีเสียงกำลังเตรียม ถามสถานะทุก 2 วินาที
  const processing = voices?.some((v) => v.status === "processing" || v.moods.some((m) => m.status === "processing")) ?? false;
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [processing, refresh]);

  return (
    <main className="page" style={{ maxWidth: 1100 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 600 }}>คลังเสียง</h1>
        <p className="muted" style={{ margin: 0 }}>
          เก็บเสียงพากย์ภาษาไทยไว้ใช้ซ้ำ แล้วเลือกให้ตัวละครแต่ละตัวในหน้าตรวจบท แทนการเลียนเสียงนักแสดงต้นฉบับ
        </p>
      </div>

      <UploadCard onUploaded={refresh} />

      {error && <div className="alert error" role="alert">{error}</div>}
      <section aria-label="เสียงในคลัง" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 500 }}>เสียงในคลัง {voices?.length ? `(${voices.length})` : ""}</h2>
        {voices === null ? <div className="empty">กำลังโหลด...</div>
          : voices.length === 0 ? <div className="empty">ยังไม่มีเสียงในคลัง</div>
          : (
            <div className="grid-2">
              {voices.map((v) => <VoiceCard key={v.id} v={v} preview={preview} onChanged={refresh} />)}
            </div>
          )}
      </section>
    </main>
  );
}
