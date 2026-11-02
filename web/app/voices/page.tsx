"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, fileUrl, uploadJob, uploadVoice, uploadVoiceImage, uploadVoiceMood, type Gender, type LibraryVoice, type Mood, type VoiceAnalysis, type VoiceMood } from "@/lib/api";
import { GENDER_LABEL, MOODS, MOOD_LABEL, TONES, VOICE_CATEGORIES, VOICE_STAGE_LABEL, fmtWhen } from "@/lib/format";
import { PreviewButton, usePreview } from "@/components/VoicePreview";
import { UploadIcon } from "@/components/Icons";
import VoiceAvatar from "@/components/VoiceAvatar";
import { useAuth } from "@/lib/useAuth";

const ACCEPT = ".wav,.mp3,.m4a,.aac,.flac,.ogg,.oga,.opus,.wma,.mp4,.mov,.mkv,.webm";
const GENDERS: Gender[] = ["", "male", "female"];
const IMAGE_ACCEPT = "image/jpeg,image/png,image/webp";

/** เลือกหมวดหมู่ได้หลายหมวด: หมวดตั้งต้น หมวดที่ใช้อยู่ในคลัง และพิมพ์หมวดใหม่เองได้ */
function CategoryPicker({ value, onChange, known, id }: {
  value: string[];
  onChange: (v: string[]) => void;
  known: string[];
  id: string;
}) {
  const [custom, setCustom] = useState("");
  const options = [...new Set([...VOICE_CATEGORIES, ...known, ...value])];
  const toggle = (c: string) => onChange(value.includes(c) ? value.filter((x) => x !== c) : [...value, c]);
  const addCustom = () => {
    const c = custom.trim().replace(/\s+/g, " ").slice(0, 30);
    if (c && !value.includes(c) && value.length < 10) onChange([...value, c]);
    setCustom("");
  };
  return (
    <div className="chips" role="group" aria-labelledby={id}>
      {options.map((c) => (
        <button key={c} type="button" className="chip" aria-pressed={value.includes(c)} onClick={() => toggle(c)}>{c}</button>
      ))}
      <input className="chip-input" maxLength={30} placeholder="+ หมวดใหม่" aria-label="เพิ่มหมวดหมู่ใหม่" value={custom}
        onChange={(e) => setCustom(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCustom(); } }}
        onBlur={addCustom} />
    </div>
  );
}

const OTHER_VOICES_WARN = 0.2; // ท่อนเสียงคนอื่นเกินสัดส่วนนี้ เตือนว่าไฟล์มีหลายคนพูด

const fmtMin = (sec: number) => (sec >= 90 ? `${(sec / 60).toFixed(1)} นาที` : `${Math.round(sec)} วินาที`);

/** ผลประเมินไฟล์ที่อัปโหลดทั้งไฟล์: ประเมินกี่ท่อน และมีเสียงคนอื่นปนแค่ไหน */
function AnalysisNote({ a }: { a: VoiceAnalysis }) {
  const other = a.other_voices ?? 0;
  return (
    <>
      <span className="dim">
        ประเมินทั้งไฟล์{a.source_sec ? ` ${fmtMin(a.source_sec)}` : ""}
        {a.speech_sec ? ` · เสียงพูด ${fmtMin(a.speech_sec)}` : ""}
        {a.windows ? ` · ${a.windows} ท่อน เลือกท่อนที่ชัดที่สุด` : ""}
      </span>
      {other >= OTHER_VOICES_WARN && (
        <div className="alert warn">
          พบเสียงคนอื่นปนราว {Math.round(other * 100)}% ของไฟล์ ระบบเลือกเฉพาะเสียงของคนที่พูดมากที่สุด
          ถ้าเสียงตัวอย่างไม่ใช่คนที่ต้องการ ใช้ไฟล์ที่มีแค่เสียงคนนั้น
        </div>
      )}
    </>
  );
}

/** ปุ่มเลือกรูป (input file ซ่อนอยู่ในปุ่ม) */
function ImagePickButton({ label, onPick, disabled }: { label: string; onPick: (f: File) => void; disabled?: boolean }) {
  return (
    <label className={`btn small${disabled ? " disabled" : ""}`} style={{ cursor: disabled ? "default" : "pointer" }}>
      {label}
      <input type="file" accept={IMAGE_ACCEPT} className="sr-only" disabled={disabled}
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onPick(f); }} />
    </label>
  );
}

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

type AddMode = "single" | "multi";

/** เพิ่มเสียงเข้าคลังจากไฟล์หรือลิงก์
 *  single: คลิปที่มีคนเดียวพูด เพิ่มเป็นเสียงเลย
 *  multi : คลิปที่มีหลายคนพูด ส่งเป็นงานแยกผู้พูด (ไม่แปลไม่พากย์) แล้วไปหน้าเลือกบันทึกเสียงของแต่ละคน */
function UploadCard({ onUploaded, known }: { onUploaded: () => void; known: string[] }) {
  const router = useRouter();
  const [mode, setMode] = useState<AddMode>("single");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [count, setCount] = useState("");
  const [drag, setDrag] = useState(false);
  const [name, setName] = useState("");
  const [gender, setGender] = useState<Gender>("");
  const [tone, setTone] = useState("");
  const [description, setDescription] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const [image, setImage] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState("");
  const [rights, setRights] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const abortRef = useRef<(() => void) | null>(null);
  const multi = mode === "multi";
  const busy = progress !== null;

  const pickFile = (f: File | undefined | null) => {
    setError("");
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPT.split(",").includes(ext)) {
      setError("รองรับไฟล์เสียง WAV, MP3, M4A, FLAC, OGG, OGA หรือวิดีโอ MP4, MOV, MKV, WEBM");
      return;
    }
    setFile(f);
    setUrl("");
    if (!name) setName(f.name.slice(0, f.name.lastIndexOf(".")).slice(0, 80));
  };

  const hasSource = !!file || !!url.trim();
  const ready = hasSource && rights && !busy && (multi || !!name.trim());

  useEffect(() => {
    if (!image) { setImagePreview(""); return; }
    const objectUrl = URL.createObjectURL(image);
    setImagePreview(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [image]);

  const submitMulti = async () => {
    const n = parseInt(count, 10);
    const opts = { sourceLang: "", targetLang: "th" as const, numSpeakers: n >= 2 && n <= 20 ? n : null,
      review: true, burnSubs: false, genre: "", glossary: "", library: true };
    let id: string;
    if (file) {
      const up = uploadJob(file, opts, setProgress);
      abortRef.current = up.abort;
      id = (await up.promise).id;
    } else {
      id = (await api.createFromUrl(url.trim(), opts)).id;
    }
    router.push(`/jobs/${id}`);
  };

  const submitSingle = async () => {
    const meta = { name: name.trim(), gender, tone: tone.trim(), description: description.trim(), categories };
    let v: LibraryVoice;
    if (file) {
      const up = uploadVoice(file, meta, setProgress);
      abortRef.current = up.abort;
      v = await up.promise;
    } else {
      v = await api.createVoiceFromUrl(url.trim(), meta);
    }
    let imageError = "";
    if (image) {
      await uploadVoiceImage(v.id, image).catch((e) => { imageError = `เพิ่มเสียงแล้ว แต่ตั้งรูปไม่สำเร็จ: ${(e as Error).message}`; });
    }
    setFile(null);
    setUrl("");
    setName("");
    setTone("");
    setGender("");
    setDescription("");
    setCategories([]);
    setImage(null);
    setError(imageError);
    onUploaded();
  };

  const submit = async () => {
    if (!ready) return;
    setError("");
    setProgress(0);
    try {
      await (multi ? submitMulti() : submitSingle());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setProgress(null);
      abortRef.current = null;
    }
  };

  return (
    <section className="card" aria-labelledby="add-voice">
      <div className="row" style={{ justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h2 id="add-voice" style={{ margin: 0 }}>เพิ่มเสียงเข้าคลัง</h2>
        <div className="seg" role="group" aria-label="ชนิดคลิป">
          <button type="button" aria-pressed={!multi} onClick={() => setMode("single")} disabled={busy}>เสียงคนเดียว</button>
          <button type="button" aria-pressed={multi} onClick={() => setMode("multi")} disabled={busy}>คลิปหลายคนพูด</button>
        </div>
      </div>
      <div className="grid-2">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <label className={`dropzone${drag ? " drag" : ""}`} style={{ minHeight: 0, padding: 24, flex: 1 }}
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
                <span className="dim">
                  {multi
                    ? "คลิปที่มีหลายคนพูด เช่น ละคร รายการ · ระบบแยกเสียงของแต่ละคนให้"
                    : "เสียงคนเดียวพูด 10 วินาทีขึ้นไป · ระบบประเมินทั้งไฟล์ (ไม่เกิน 60 นาที) ยิ่งยาวยิ่งได้ท่อนที่ดี"}
                </span>
              </>
            )}
            <input type="file" accept={ACCEPT} aria-label="เลือกไฟล์เสียง" disabled={busy}
              onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
          <input className="input" type="url" placeholder="หรือวางลิงก์ YouTube, TikTok, Facebook ฯลฯ" aria-label="ลิงก์คลิป"
            value={url} disabled={busy} onChange={(e) => { setUrl(e.target.value); if (e.target.value) setFile(null); }} />
        </div>

        {multi ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <p className="muted" style={{ margin: 0 }}>
              ระบบแยกเพลงออก แยกเสียงของแต่ละคน และถอดเสียงให้ (ไม่แปล ไม่พากย์) แล้วพาไปหน้าที่ให้ฟังเสียงแต่ละคน
              ตั้งชื่อว่าเป็นเสียงของใคร และเลือกบันทึกลงคลังทีละคน
            </p>
            <div className="field">
              <label htmlFor="v-count">จำนวนคนในคลิป (ถ้ารู้ ช่วยให้แยกแม่นขึ้น)</label>
              <input id="v-count" className="input" type="number" min={2} max={20} placeholder="ไม่ระบุ = ให้ระบบนับเอง"
                value={count} onChange={(e) => setCount(e.target.value)} disabled={busy} />
            </div>
            <span className="dim">ใช้เครดิตตามความยาวคลิปเหมือนงานพากย์</span>
          </div>
        ) : (
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
            <div className="field">
              <span className="label">รูป (ไม่ใส่ก็ได้)</span>
              <div className="row" style={{ gap: 10 }}>
                <VoiceAvatar name={name} url={imagePreview} />
                <ImagePickButton label={image ? "เปลี่ยนรูป" : "เลือกรูป"} onPick={setImage} disabled={busy} />
                {image && <button type="button" className="btn small" onClick={() => setImage(null)} disabled={busy}>เอารูปออก</button>}
              </div>
            </div>
          </div>
        )}
      </div>

      {!multi && (
        <>
          <div className="field">
            <span className="label" id="v-cat">หมวดหมู่ (เลือกได้หลายหมวด)</span>
            <CategoryPicker id="v-cat" value={categories} onChange={setCategories} known={known} />
          </div>
          <div className="field">
            <label htmlFor="v-desc">รายละเอียด (ไม่ใส่ก็ได้)</label>
            <textarea id="v-desc" className="textarea" rows={3} maxLength={1000}
              placeholder="เช่น คนพากย์ บทที่เหมาะ อายุตัวละคร สไตล์การพูด"
              value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
        </>
      )}

      <label className="check" style={{ justifyContent: "flex-start" }}>
        <input type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)} />
        <span>
          {multi ? "ฉันเป็นเจ้าของเสียงในคลิปนี้ หรือได้รับอนุญาตจากเจ้าของเสียงให้นำไปใช้พากย์แล้ว"
            : "ฉันเป็นเจ้าของเสียงนี้ หรือได้รับอนุญาตจากเจ้าของเสียงให้นำไปใช้พากย์แล้ว"}
        </span>
      </label>
      {error && <div className="alert error" role="alert">{error}</div>}
      <div className="row" style={{ justifyContent: "space-between" }}>
        {busy && file ? (
          <div style={{ flex: "1 1 260px", display: "flex", alignItems: "center", gap: 12 }}>
            <div className="progress" style={{ flex: 1 }}><div style={{ width: `${(progress ?? 0) * 100}%` }} /></div>
            <span className="mono">{Math.round((progress ?? 0) * 100)}%</span>
            <button type="button" className="btn small" onClick={() => abortRef.current?.()}>ยกเลิก</button>
          </div>
        ) : (
          <span className="dim">
            {multi ? "แยกเสียงเสร็จแล้วจะพาไปหน้าเลือกบันทึกเสียงของแต่ละคน"
              : "ระบบจะแยกเสียงรบกวนออก ตัดท่อนที่ชัดที่สุด 3–10 วินาที และถอดข้อความให้อัตโนมัติ"}
          </span>
        )}
        <button type="button" className="btn primary" onClick={submit} disabled={!ready}>
          {busy ? (file ? "กำลังอัปโหลด..." : "กำลังส่ง...") : multi ? "แยกเสียง" : "เพิ่มเสียง"}
        </button>
      </div>
    </section>
  );
}

/** เสียงอารมณ์หนึ่ง: ฟัง แก้ข้อความ ลองใหม่ ลบ */
function MoodRow({ v, m, preview, run, canEdit }: {
  v: LibraryVoice;
  m: VoiceMood;
  canEdit: boolean;
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
        {m.status === "ready" && (m.analysis?.other_voices ?? 0) >= OTHER_VOICES_WARN && <span className="badge warn">มีเสียงคนอื่นปน</span>}
        <span className="row" style={{ marginLeft: "auto", gap: 6 }}>
          {canEdit && m.status === "ready" && !editing && <button type="button" className="icon-btn" onClick={() => setEditing(true)}>แก้ข้อความ</button>}
          {canEdit && m.status === "failed" && <button type="button" className="icon-btn" onClick={() => run(() => api.retryVoiceMood(v.id, m.mood))}>ลองใหม่</button>}
          {canEdit && !(m.status === "processing" && m.stage !== "queued") && (
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
function MoodSection({ v, preview, run, canEdit }: {
  v: LibraryVoice;
  canEdit: boolean;
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
      {v.moods.map((m) => <MoodRow key={m.mood} v={v} m={m} preview={preview} run={run} canEdit={canEdit} />)}
      {canEdit && missing.length > 0 && (
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
      <span className="dim">{canEdit ? "ใช้คนพากย์คนเดิม พูดด้วยอารมณ์นั้น 10 วินาทีขึ้นไป แล้ว" : ""}เลือกอารมณ์ให้แต่ละประโยคในหน้าแก้บท</span>
    </div>
  );
}

function VoiceCard({ v, preview, onChanged, known, canEdit }: {
  v: LibraryVoice;
  canEdit: boolean;
  preview: ReturnType<typeof usePreview>;
  onChanged: () => void;
  known: string[];
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(v.name);
  const [gender, setGender] = useState<Gender>(v.gender);
  const [tone, setTone] = useState(v.tone);
  const [description, setDescription] = useState(v.description ?? "");
  const [categories, setCategories] = useState<string[]>(v.categories ?? []);
  const [text, setText] = useState(v.text);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (editing) return;
    setName(v.name); setGender(v.gender); setTone(v.tone); setDescription(v.description ?? ""); setCategories(v.categories ?? []);
    setText(v.text);
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
    // ข้อความในเสียงตัวอย่างมีเฉพาะเสียงที่เตรียมเสร็จ เสียงที่ยังไม่เสร็จแก้ได้แค่ข้อมูลอื่น
    const ready = v.status === "ready";
    if (!name.trim() || (ready && !text.trim())) return setError("ชื่อและข้อความในเสียงต้องไม่ว่าง");
    const ok = await run(() => api.updateVoice(v.id, {
      name: name.trim(), gender, tone: tone.trim(), description: description.trim(), categories,
      ...(ready ? { text: text.trim() } : {}),
    }));
    if (ok) setEditing(false);
  };

  const remove = () => {
    if (window.confirm(`ลบเสียง "${v.name}" ออกจากคลัง? ตัวละครที่ใช้เสียงนี้จะกลับไปใช้เสียงต้นฉบับ`)) run(() => api.deleteVoice(v.id));
  };

  const audioUrl = fileUrl.voice(v.id, v.updated_at);
  return (
    <article className="card" style={{ gap: 12 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "nowrap" }}>
        <VoiceAvatar name={v.name} url={v.image ? fileUrl.voiceImage(v.id, v.updated_at) : ""} />
        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0, flex: 1 }}>
          <span style={{ fontSize: 17, fontWeight: 600, wordBreak: "break-word" }}>{v.name}</span>
          <div className="row" style={{ gap: 6 }}>
            {(v.categories ?? []).map((c) => <span key={c} className="badge category">{c}</span>)}
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
      {!editing && v.description && (
        <p className="muted" style={{ margin: 0, fontSize: 14, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{v.description}</p>
      )}

      {editing ? (
        <>
          <div className="field">
            <span className="label">รูป</span>
            <div className="row" style={{ gap: 10 }}>
              <ImagePickButton label={v.image ? "เปลี่ยนรูป" : "เพิ่มรูป"} disabled={busy}
                onPick={(f) => run(() => uploadVoiceImage(v.id, f))} />
              {v.image && (
                <button type="button" className="btn small" disabled={busy}
                  onClick={() => run(() => api.deleteVoiceImage(v.id))}>ลบรูป</button>
              )}
            </div>
          </div>
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
          <div className="field">
            <span className="label" id={`c-${v.id}`}>หมวดหมู่</span>
            <CategoryPicker id={`c-${v.id}`} value={categories} onChange={setCategories} known={known} />
          </div>
          <div className="field">
            <label htmlFor={`d-${v.id}`}>รายละเอียด</label>
            <textarea id={`d-${v.id}`} className="textarea" rows={3} maxLength={1000} value={description}
              onChange={(e) => setDescription(e.target.value)} />
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
      {v.status === "ready" && v.analysis && <AnalysisNote a={v.analysis} />}
      {v.status === "ready" && !editing && (canEdit || v.moods.length > 0) && <MoodSection v={v} preview={preview} run={run} canEdit={canEdit} />}
      {error && <div className="alert error" role="alert">{error}</div>}

      {canEdit && <div className="row" style={{ gap: 8 }}>
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
      </div>}
    </article>
  );
}

export default function VoicesPage() {
  const [voices, setVoices] = useState<LibraryVoice[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState(""); // "" = ทุกหมวด
  const preview = usePreview();
  const { config, user, loaded } = useAuth();
  // เปิดระบบบัญชีแล้ว เพิ่ม แก้ และลบเสียงได้เฉพาะผู้ดูแล ผู้ใช้ทั่วไปดูและฟังได้อย่างเดียว (API ตรวจซ้ำอีกชั้น)
  const canEdit = loaded && (!config?.auth || !!user?.admin);
  // หมวดที่ใช้อยู่ในคลัง (เรียงตามจำนวนเสียงมากไปน้อย) ใช้ทำปุ่มกรองและเป็นตัวเลือกตอนตั้งหมวด
  const known = useMemo(() => {
    const count = new Map<string, number>();
    voices?.forEach((v) => (v.categories ?? []).forEach((c) => count.set(c, (count.get(c) ?? 0) + 1)));
    return [...count.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c);
  }, [voices]);
  const shown = voices?.filter((v) => !filter || (v.categories ?? []).includes(filter)) ?? null;
  useEffect(() => { if (filter && voices && !known.includes(filter)) setFilter(""); }, [filter, known, voices]);

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

      {canEdit && <UploadCard onUploaded={refresh} known={known} />}

      {error && <div className="alert error" role="alert">{error}</div>}
      <section aria-label="เสียงในคลัง" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 500 }}>
          เสียงในคลัง {shown?.length ? `(${shown.length}${filter ? ` จาก ${voices?.length}` : ""})` : ""}
        </h2>
        {known.length > 0 && (
          <div className="chips" role="group" aria-label="กรองตามหมวดหมู่">
            <button type="button" className="chip" aria-pressed={!filter} onClick={() => setFilter("")}>ทั้งหมด</button>
            {known.map((c) => (
              <button key={c} type="button" className="chip" aria-pressed={filter === c} onClick={() => setFilter(c)}>{c}</button>
            ))}
          </div>
        )}
        {shown === null ? <div className="empty">กำลังโหลด...</div>
          : voices?.length === 0 ? <div className="empty">ยังไม่มีเสียงในคลัง</div>
          : (
            <div className="grid-2">
              {shown.map((v) => <VoiceCard key={v.id} v={v} preview={preview} onChanged={refresh} known={known} canEdit={canEdit} />)}
            </div>
          )}
      </section>
    </main>
  );
}
