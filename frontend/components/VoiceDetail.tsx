"use client";

import { useEffect, useState } from "react";
import { api, fileUrl, uploadVoiceImage, uploadVoiceMood, type Gender, type LibraryVoice, type Mood, type VoiceAnalysis, type VoiceMood } from "@/lib/api";
import { GENDER_LABEL, MOODS, MOOD_LABEL, TONES, VOICE_STAGE_LABEL, fmtWhen } from "@/lib/format";
import CategoryPicker from "@/components/CategoryPicker";
import { PreviewButton, PlayRoundButton, usePreview } from "@/components/VoicePreview";
import WaveBars, { fmtClock } from "@/components/WaveBars";
import VoiceAvatar from "@/components/VoiceAvatar";
import { tx } from "@/lib/i18n";

const ACCEPT = ".wav,.mp3,.m4a,.aac,.flac,.ogg,.oga,.opus,.wma,.mp4,.mov,.mkv,.webm";
const IMAGE_ACCEPT = "image/jpeg,image/png,image/webp";
const OTHER_VOICES_WARN = 0.2;

const fmtMin = (sec: number) => (sec >= 90 ? tx("{0} นาที", { 0: (sec / 60).toFixed(1) }) : tx("{0} วินาที", { 0: Math.round(sec) }));

function AnalysisNote({ a }: { a: VoiceAnalysis }) {
  const other = a.other_voices ?? 0;
  return (
    <>
      <span className="dim">
        {tx("ประเมินทั้งไฟล์")}{a.source_sec ? ` ${fmtMin(a.source_sec)}` : ""}
        {a.speech_sec ? tx(" · เสียงพูด {0}", { 0: fmtMin(a.speech_sec) }) : ""}
        {a.windows ? tx(" · {0} ท่อน เลือกท่อนที่ชัดที่สุด", { 0: a.windows }) : ""}
      </span>
      {other >= OTHER_VOICES_WARN && (
        <div className="alert warn">
          {tx("พบเสียงคนอื่นปนราว")} {Math.round(other * 100)}{tx("% ของไฟล์ ระบบเลือกเฉพาะเสียงของคนที่พูดมากที่สุด ถ้าเสียงตัวอย่างไม่ใช่คนที่ต้องการ ใช้ไฟล์ที่มีแค่เสียงคนนั้น")}
        </div>
      )}
    </>
  );
}

export function ImagePickButton({ label, onPick, disabled }: { label: string; onPick: (f: File) => void; disabled?: boolean }) {
  return (
    <label className={`btn small${disabled ? " disabled" : ""}`} style={{ cursor: disabled ? "default" : "pointer" }}>
      {label}
      <input type="file" accept={IMAGE_ACCEPT} className="sr-only" disabled={disabled}
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onPick(f); }} />
    </label>
  );
}

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
        <span className="badge awaiting_review">{tx(MOOD_LABEL[m.mood])}</span>
        {m.review === "pending" && <span className="badge warn">{tx("รอผู้ดูแลตรวจ")}</span>}
        {m.review === "rejected" && <span className="badge failed">{tx("ไม่ผ่านการตรวจ")}</span>}
        {m.status === "processing" && <span className="badge running">{VOICE_STAGE_LABEL[m.stage] ?? m.stage}...</span>}
        {m.status === "failed" && <span className="badge failed">{tx("เตรียมเสียงไม่สำเร็จ")}</span>}
        {m.status === "ready" && m.quality != null && m.quality < 2.3 && <span className="badge warn">{tx("มีเสียงรบกวน")}</span>}
        <span className="row" style={{ marginLeft: "auto", gap: 6 }}>
          {canEdit && m.status === "ready" && !editing && <button type="button" className="icon-btn" onClick={() => setEditing(true)}>{tx("แก้ข้อความ")}</button>}
          {canEdit && m.status === "failed" && <button type="button" className="icon-btn" onClick={() => run(() => api.retryVoiceMood(v.id, m.mood))}>{tx("ลองใหม่")}</button>}
          {canEdit && !(m.status === "processing" && m.stage !== "queued") && (
            <button type="button" className="icon-btn" aria-label={tx("ลบอารมณ์{0}", { 0: tx(MOOD_LABEL[m.mood]) })}
              onClick={() => window.confirm(tx("ลบเสียงอารมณ์{0}? ประโยคที่เลือกอารมณ์นี้จะกลับไปใช้เสียงปกติ", { 0: tx(MOOD_LABEL[m.mood]) }))
                && run(() => api.deleteVoiceMood(v.id, m.mood))}>{tx("ลบ")}</button>
          )}
          {m.status === "ready" && (
            <PreviewButton url={fileUrl.voiceMood(v.id, m.mood, v.updated_at)} playing={preview.playing} onToggle={preview.toggle} />
          )}
        </span>
      </div>
      {m.status === "failed" && m.error && <div className="alert error">{m.error}</div>}
      {editing ? (
        <div className="field">
          <label className="sr-only" htmlFor={`mx-${v.id}-${m.mood}`}>{tx("ข้อความที่พูดในเสียงอารมณ์นี้")}</label>
          <textarea id={`mx-${v.id}-${m.mood}`} className="textarea" rows={2} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row" style={{ gap: 6 }}>
            <button type="button" className="btn small primary" onClick={save}>{tx("บันทึก")}</button>
            <button type="button" className="btn small" onClick={() => setEditing(false)}>{tx("ยกเลิก")}</button>
          </div>
        </div>
      ) : m.status === "ready" && (
        <span className="dim">“{m.text}” · {m.duration?.toFixed(1)}  {tx("วินาที")}</span>
      )}
    </div>
  );
}

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
      <span className="label">{tx("เสียงอารมณ์อื่น")}</span>
      {v.moods.map((m) => <MoodRow key={m.mood} v={v} m={m} preview={preview} run={run} canEdit={canEdit} />)}
      {canEdit && missing.length > 0 && (
        <div className="row" style={{ gap: 8 }}>
          <label className="sr-only" htmlFor={`am-${v.id}`}>{tx("อารมณ์ที่จะเพิ่ม")}</label>
          <select id={`am-${v.id}`} className="spk-select" value={pick} onChange={(e) => setMood(e.target.value as Mood)}
            disabled={progress !== null}>
            {missing.map((m) => <option key={m} value={m}>{tx(MOOD_LABEL[m])}</option>)}
          </select>
          {progress !== null ? (
            <span className="mono">{tx("กำลังอัปโหลด")} {Math.round(progress * 100)}%</span>
          ) : (
            <label className="btn small" style={{ cursor: "pointer" }}>
              {tx("เพิ่มคลิปอารมณ์นี้")}
              <input type="file" accept={ACCEPT} className="sr-only"
                onChange={(e) => { add(e.target.files?.[0]); e.target.value = ""; }} />
            </label>
          )}
        </div>
      )}
      <span className="dim">{canEdit ? tx("ใช้คนพากย์คนเดิม พูดด้วยอารมณ์นั้น 10 วินาทีขึ้นไป แล้ว") : ""}{tx("เลือกอารมณ์ให้แต่ละประโยคในหน้าแก้บท")}</span>
    </div>
  );
}

/** รายละเอียดเต็มแนว Pixabay — เครื่องเล่นใหญ่ + คอลัมน์ข้อมูล/แก้ไข */
export default function VoiceDetail({ v, preview, onChanged, known, canEdit }: {
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
  const [reportOpen, setReportOpen] = useState(false);
  const [reportReason, setReportReason] = useState<"stolen" | "inappropriate" | "quality" | "other">("quality");
  const [reportDetail, setReportDetail] = useState("");
  const [reportDone, setReportDone] = useState("");

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
    const ready = v.status === "ready";
    if (!name.trim() || (ready && !text.trim())) return setError(tx("ชื่อและข้อความในเสียงต้องไม่ว่าง"));
    const ok = await run(() => api.updateVoice(v.id, {
      name: name.trim(), gender, tone: tone.trim(), description: description.trim(), categories,
      ...(ready ? { text: text.trim() } : {}),
    }));
    if (ok) setEditing(false);
  };

  const remove = () => {
    if (window.confirm(tx("ลบเสียง \"{0}\" ออกจากคลัง? ตัวละครที่ใช้เสียงนี้จะกลับไปใช้เสียงต้นฉบับ", { 0: v.name }))) {
      run(() => api.deleteVoice(v.id));
    }
  };

  const audioUrl = fileUrl.voice(v.id, v.updated_at);
  const on = preview.playing === audioUrl;
  const cover = v.image ? fileUrl.voiceImage(v.id, v.updated_at) : "";
  const clockTotal = on && preview.duration > 0 ? preview.duration : (v.duration ?? 0);

  return (
    <div className="voice-detail">
      <section className="voice-hero" aria-label={tx("ฟังตัวอย่าง")}>
        {cover && (
          // eslint-disable-next-line @next/next/no-img-element
          <img className="voice-hero-bg" src={cover} alt="" />
        )}
        <div className="voice-hero-inner">
          <div className="voice-hero-top">
            <VoiceAvatar name={v.name} url={cover} size={64} />
            <div className="voice-hero-titles">
              <h2 className="voice-hero-name">{v.name}</h2>
              <span className="voice-hero-by">
                {v.actor ? `${tx("พากย์โดย")} ${v.actor}` : v.mine ? tx("ของฉัน") : tx("คลังเสียง")}
              </span>
            </div>
            {v.status === "ready" && (
              <PlayRoundButton url={audioUrl} playing={preview.playing} onToggle={preview.toggle} />
            )}
          </div>
          {v.status === "ready" && (
            <div className="voice-hero-wave">
              <span className="voice-hero-time mono">{fmtClock(on ? preview.currentTime : 0)}</span>
              <WaveBars
                seed={v.id}
                bars={96}
                active={on}
                progress={on ? preview.progress : 0}
                className="voice-hero-bars"
                onClick={() => preview.toggle(audioUrl)}
              />
              <span className="voice-hero-time mono">{fmtClock(clockTotal)}</span>
            </div>
          )}
          {v.status === "processing" && (
            <span className="badge running">{VOICE_STAGE_LABEL[v.stage] ?? v.stage}...</span>
          )}
          {v.status === "failed" && v.error && <div className="alert error">{v.error}</div>}
        </div>
      </section>

      <div className="voice-detail-grid">
        <div className="voice-detail-main">
          <div className="row" style={{ gap: 6 }}>
            {v.review === "pending" && <span className="badge awaiting_review">{tx("รอผู้ดูแลตรวจ")}</span>}
            {v.review === "rejected" && <span className="badge failed">{tx("ไม่ผ่านการตรวจ")}</span>}
            {(v.categories ?? []).map((c) => <span key={c} className="badge category">{c}</span>)}
            {v.gender && <span className="badge queued">{tx(GENDER_LABEL[v.gender])}</span>}
            {v.tone && <span className="badge awaiting_review">{v.tone}</span>}
            {v.moods.some((m) => m.status === "ready") && (
              <span className="badge done">{tx("อารมณ์ {0}/{1}", {
                0: v.moods.filter((m) => m.status === "ready" && (m.review == null || m.review === "approved")).length,
                1: MOODS.length,
              })}</span>
            )}
            {v.status === "ready" && v.quality != null && v.quality < 2.3 && <span className="badge warn">{tx("มีเสียงรบกวน")}</span>}
          </div>

          {!editing && v.description && (
            <p className="muted" style={{ margin: 0, fontSize: 15, lineHeight: 1.65, whiteSpace: "pre-wrap" }}>{v.description}</p>
          )}
          {!editing && v.status === "ready" && v.text && (
            <p style={{ margin: 0, fontSize: 16, lineHeight: 1.65 }}>“{v.text}”</p>
          )}
          {v.status === "ready" && v.analysis && <AnalysisNote a={v.analysis} />}
          {v.status === "ready" && !editing && (canEdit || v.moods.length > 0) && (
            <MoodSection v={v} preview={preview} run={run} canEdit={canEdit} />
          )}

          {editing && (
            <div className="card tight" style={{ gap: 12 }}>
              <div className="field">
                <span className="label">{tx("รูป")}</span>
                <div className="row" style={{ gap: 10 }}>
                  <VoiceAvatar name={name || v.name} url={cover} />
                  <ImagePickButton label={v.image ? tx("เปลี่ยนรูป") : tx("เพิ่มรูป")} disabled={busy}
                    onPick={(f) => run(() => uploadVoiceImage(v.id, f))} />
                  {v.image && (
                    <button type="button" className="btn small" disabled={busy}
                      onClick={() => run(() => api.deleteVoiceImage(v.id))}>{tx("ลบรูป")}</button>
                  )}
                </div>
              </div>
              <div className="field">
                <label htmlFor={`n-${v.id}`}>{tx("ชื่อเสียง")}</label>
                <input id={`n-${v.id}`} className="input" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="field">
                <span className="label">{tx("เพศ")}</span>
                <div className="seg" role="group" aria-label={tx("เพศของเสียง")} style={{ alignSelf: "flex-start" }}>
                  {(["male", "female", ""] as Gender[]).map((g) => (
                    <button key={g || "none"} type="button" aria-pressed={gender === g} onClick={() => setGender(g)}>{tx(GENDER_LABEL[g])}</button>
                  ))}
                </div>
              </div>
              <div className="field">
                <label htmlFor={`t-${v.id}`}>{tx("โทนเสียง")}</label>
                <input id={`t-${v.id}`} className="input" list="tones-edit" maxLength={80} value={tone} onChange={(e) => setTone(e.target.value)} />
                <datalist id="tones-edit">{TONES.map((t) => <option key={t} value={tx(t)} />)}</datalist>
              </div>
              <div className="field">
                <span className="label" id={`c-${v.id}`}>{tx("หมวดหมู่")}</span>
                <CategoryPicker id={`c-${v.id}`} value={categories} onChange={setCategories} known={known} />
              </div>
              <div className="field">
                <label htmlFor={`d-${v.id}`}>{tx("รายละเอียด")}</label>
                <textarea id={`d-${v.id}`} className="textarea" rows={3} maxLength={1000} value={description}
                  onChange={(e) => setDescription(e.target.value)} />
              </div>
              {v.status === "ready" && (
                <div className="field">
                  <label htmlFor={`x-${v.id}`}>{tx("ข้อความที่พูดในเสียงตัวอย่าง")}</label>
                  <textarea id={`x-${v.id}`} className="textarea" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
                  <span className="dim">{tx("ฟังตัวอย่างแล้วแก้ให้ตรงทุกคำ ระบบพากย์จะเลียนเสียงได้แม่นขึ้น")}</span>
                </div>
              )}
              <div className="row" style={{ gap: 8 }}>
                <button type="button" className="btn small primary" onClick={save} disabled={busy}>{busy ? tx("กำลังบันทึก...") : tx("บันทึก")}</button>
                <button type="button" className="btn small" onClick={() => setEditing(false)} disabled={busy}>{tx("ยกเลิก")}</button>
              </div>
            </div>
          )}
          {error && <div className="alert error" role="alert">{error}</div>}
        </div>

        <aside className="voice-detail-side">
          <div className="card tight voice-side-card">
            {canEdit && !editing && (
              <button type="button" className="btn primary" style={{ width: "100%" }}
                onClick={() => setEditing(true)} disabled={v.status === "processing"}>
                {tx("แก้ไข")}
              </button>
            )}
            {canEdit && v.status === "failed" && (
              <button type="button" className="btn" style={{ width: "100%" }}
                onClick={() => run(() => api.retryVoice(v.id))} disabled={busy}>{tx("ลองใหม่")}</button>
            )}
            {v.status === "ready" && (
              <dl className="voice-stats">
                <div><dt>{tx("ความยาว")}</dt><dd className="mono">{fmtClock(v.duration)}</dd></div>
                {v.pitch_hz != null && <div><dt>{tx("ระดับเสียง")}</dt><dd className="mono">{Math.round(v.pitch_hz)} Hz</dd></div>}
                {v.quality != null && <div><dt>{tx("ความชัด")}</dt><dd className="mono">{v.quality.toFixed(1)}/4.5</dd></div>}
                <div><dt>{tx("เพิ่มเมื่อ")}</dt><dd>{fmtWhen(v.created_at)}</dd></div>
              </dl>
            )}
            {canEdit && !(v.status === "processing" && v.stage !== "queued") && (
              <button type="button" className="btn small danger" style={{ width: "100%" }} onClick={remove} disabled={busy}>{tx("ลบเสียงนี้")}</button>
            )}
            {!canEdit && !!v.actor && !reportDone && (
              <button type="button" className="btn small" style={{ width: "100%" }}
                onClick={() => setReportOpen((o) => !o)} disabled={busy}>{tx("รายงานเสียงนี้")}</button>
            )}
            {reportDone && <div className="alert info">{reportDone}</div>}
            {reportOpen && !reportDone && (
              <div className="field" style={{ gap: 8 }}>
                <label className="label" htmlFor={`vr-${v.id}`}>{tx("เหตุผล")}</label>
                <select id={`vr-${v.id}`} className="spk-select" value={reportReason}
                  onChange={(e) => setReportReason(e.target.value as typeof reportReason)}>
                  <option value="stolen">{tx("ขโมยเสียงคนอื่น")}</option>
                  <option value="inappropriate">{tx("เนื้อหาไม่เหมาะสม")}</option>
                  <option value="quality">{tx("คุณภาพเสียงแย่")}</option>
                  <option value="other">{tx("อื่นๆ")}</option>
                </select>
                <textarea className="textarea" rows={3} value={reportDetail}
                  placeholder={tx("รายละเอียดเพิ่มเติม (ถ้ามี)")}
                  onChange={(e) => setReportDetail(e.target.value)} />
                <button type="button" className="btn small primary" disabled={busy}
                  onClick={async () => {
                    const ok = await run(() => api.reportVoice(v.id, reportReason, reportDetail.trim()));
                    if (ok) {
                      setReportDone(tx("ส่งรายงานแล้ว แอดมินจะตรวจเร็วๆ นี้"));
                      setReportOpen(false);
                    }
                  }}>{tx("ส่งรายงาน")}</button>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
