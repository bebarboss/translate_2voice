"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, fileUrl, type Gender, type Job, type Utterance } from "@/lib/api";
import { GENDER_LABEL, fmtDuration, langName, speakerColor, speakerLabel } from "@/lib/format";
import { PreviewButton, usePreview } from "./VoicePreview";
import { ArrowLeft } from "./Icons";

const GENDERS: Gender[] = ["", "male", "female"];
const MIN_SOLO_SEC = 3; // ตรงกับเกณฑ์ของ API (main.speaker_to_library)

/** งานเก็บเสียงเข้าคลัง: คลิปที่มีหลายคนพูด ระบบแยกผู้พูดให้แล้ว
 *  ผู้ใช้ฟัง ตั้งชื่อ รวมคนที่ถูกแยกเป็นสองคน แล้วเลือกบันทึกเสียงของแต่ละคนลงคลัง */
export default function LibraryJobView({ job, onChanged }: { job: Job; onChanged: () => void }) {
  const [lines, setLines] = useState<Utterance[] | null>(null);
  const [message, setMessage] = useState<{ kind: "info" | "error"; text: string } | null>(null);
  const preview = usePreview();

  const load = useCallback(() => {
    api.getTranscript(job.id).then(setLines).catch((e) => setMessage({ kind: "error", text: (e as Error).message }));
  }, [job.id]);
  useEffect(load, [load]);

  const lang = job.detected_lang || job.source_lang;
  const notThai = !!lang && lang !== "th";

  // เวลาพูดของแต่ละคน และเวลาที่พูดคนเดียว (ไม่มีคนอื่นพูดทับ) ซึ่งเป็นส่วนที่บันทึกลงคลังได้
  const stats = useMemo(() => {
    const out: Record<string, { count: number; sec: number; solo: number; samples: string[] }> = {};
    for (const s of job.speakers) {
      const own = (lines ?? []).filter((u) => u.speaker === s);
      const others = (lines ?? []).filter((u) => u.speaker !== s);
      const solo = own.filter((u) => !others.some((o) => Math.min(u.end, o.end) - Math.max(u.start, o.start) > 0.2));
      out[s] = {
        count: own.length,
        sec: own.reduce((a, u) => a + u.end - u.start, 0),
        solo: solo.reduce((a, u) => a + u.end - u.start, 0),
        samples: [...own].sort((a, b) => (b.end - b.start) - (a.end - a.start)).slice(0, 3).map((u) => u.source),
      };
    }
    return out;
  }, [job.speakers, lines]);

  const merge = async (speaker: string, into: string) => {
    const label = (s: string) => speakerLabel(s, job.speaker_names);
    if (!window.confirm(`รวม "${label(speaker)}" เข้ากับ "${label(into)}"? ประโยคทั้งหมดจะเป็นของ ${label(into)}`)) return;
    try {
      await api.removeSpeaker(job.id, speaker, into);
      setMessage({ kind: "info", text: `รวมเป็น ${label(into)} แล้ว` });
      onChanged();
      load();
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    }
  };

  return (
    <main className="page">
      <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
        <Link href="/voices" className="btn small"><ArrowLeft /> คลังเสียง</Link>
        <div style={{ minWidth: 0 }}>
          <h1 style={{ margin: 0 }}>แยกเสียงเข้าคลัง</h1>
          <span className="dim" style={{ wordBreak: "break-all" }}>{job.filename}{job.duration ? ` · ${fmtDuration(job.duration)}` : ""}</span>
        </div>
      </div>

      <p className="muted" style={{ marginTop: 12 }}>
        ระบบแยกเสียงได้ {job.speakers.length} คน ฟังแล้วตั้งชื่อเสียงที่ต้องการ กด &ldquo;บันทึกลงคลัง&rdquo; ทีละคน
        ระบบจะใช้เฉพาะช่วงที่คนนั้นพูดคนเดียว แล้วเลือกท่อนที่ชัดที่สุดเป็นเสียงตัวอย่างให้เอง
        ถ้าคนเดียวถูกแยกเป็นสองคน ใช้ &ldquo;รวมกับ&rdquo;
      </p>
      {notThai && (
        <div className="alert error" role="alert">
          คลิปนี้เป็นภาษา{langName(lang!)} เสียงในคลังต้องเป็นภาษาไทย (ระบบพากย์ต้องรู้ว่าเสียงตัวอย่างพูดอะไร) ใช้คลิปภาษาไทยแทน
        </div>
      )}
      {message && <div className={`alert ${message.kind === "error" ? "error" : "info"}`} role="status">{message.text}</div>}

      {!lines ? <div className="empty">กำลังโหลด...</div> : (
        <div style={{ display: "grid", gap: 14, marginTop: 14 }}>
          {job.speakers.map((s) => (
            <SpeakerCard key={s} job={job} speaker={s} stat={stats[s]} blocked={notThai} preview={preview}
              onMerge={(into) => merge(s, into)} onSaved={onChanged} onError={(text) => setMessage({ kind: "error", text })} />
          ))}
        </div>
      )}
    </main>
  );
}

function SpeakerCard({ job, speaker, stat, blocked, preview, onMerge, onSaved, onError }: {
  job: Job;
  speaker: string;
  stat: { count: number; sec: number; solo: number; samples: string[] };
  blocked: boolean;
  preview: ReturnType<typeof usePreview>;
  onMerge: (into: string) => void;
  onSaved: () => void;
  onError: (text: string) => void;
}) {
  const label = speakerLabel(speaker, job.speaker_names);
  const [name, setName] = useState(job.speaker_names?.[speaker] ?? "");
  const [gender, setGender] = useState<Gender>("");
  const [busy, setBusy] = useState(false);
  const saved = job.saved_voices?.[speaker];
  const tooShort = stat.solo < MIN_SOLO_SEC;

  // ชื่อที่พิมพ์ใช้เป็นทั้งชื่อตัวละครในงานนี้และชื่อเสียงในคลัง
  const rename = () => {
    const n = name.trim();
    if (n !== (job.speaker_names?.[speaker] ?? "")) api.renameSpeaker(job.id, speaker, n).then(onSaved).catch(() => {});
  };

  const save = async () => {
    setBusy(true);
    try {
      rename();
      await api.speakerToLibrary(job.id, speaker, { name: name.trim(), gender, tone: "", description: "", categories: [] });
      onSaved();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card" aria-label={label}>
      <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
        <span className="swatch" style={{ background: speakerColor(speaker, job.speakers) }} />
        <strong>{label}</strong>
        <span className="dim">
          {stat.count} ประโยค · พูด {Math.round(stat.sec)} วินาที
          {stat.solo < stat.sec - 0.5 ? ` · พูดคนเดียว ${Math.round(stat.solo)} วินาที` : ""}
        </span>
        <span style={{ marginLeft: "auto" }} />
        <PreviewButton url={fileUrl.stem(job.id, speaker)} playing={preview.playing} onToggle={preview.toggle} label="ฟังเสียง" />
      </div>

      {stat.samples.length > 0 && (
        <ul className="dim" style={{ margin: "10px 0 0", paddingLeft: 18 }}>
          {stat.samples.map((t, i) => <li key={i}>{t}</li>)}
        </ul>
      )}

      <div className="row" style={{ gap: 10, flexWrap: "wrap", marginTop: 12 }}>
        {saved ? (
          <>
            <span className="badge done">บันทึกลงคลังแล้ว</span>
            <Link href="/voices" className="btn small">ดูในคลังเสียง</Link>
          </>
        ) : (
          <>
            <input className="input" style={{ flex: "1 1 200px", minWidth: 0 }} maxLength={80} placeholder="ชื่อเสียง เช่น โดราเอมอน"
              aria-label={`ชื่อเสียงของ${label}`} value={name} onChange={(e) => setName(e.target.value)} onBlur={rename} />
            <div className="seg" role="group" aria-label={`เพศของ${label}`}>
              {GENDERS.map((g) => (
                <button key={g || "auto"} type="button" aria-pressed={gender === g} onClick={() => setGender(g)}>
                  {g ? GENDER_LABEL[g] : "ให้ระบบเดา"}
                </button>
              ))}
            </div>
            <button type="button" className="btn primary small" onClick={save}
              disabled={busy || blocked || tooShort || !name.trim()}
              title={tooShort ? `พูดคนเดียวไม่ถึง ${MIN_SOLO_SEC} วินาที เสียงตัวอย่างจะไม่ชัด` : undefined}>
              {busy ? "กำลังบันทึก..." : "บันทึกลงคลัง"}
            </button>
          </>
        )}
        {job.speakers.length > 1 && (
          <select className="input" style={{ width: "auto" }} value="" aria-label={`รวม${label}กับตัวละครอื่น`}
            onChange={(e) => e.target.value && onMerge(e.target.value)}>
            <option value="">รวมกับ…</option>
            {job.speakers.filter((x) => x !== speaker).map((x) => (
              <option key={x} value={x}>{speakerLabel(x, job.speaker_names)}</option>
            ))}
          </select>
        )}
      </div>
      {tooShort && !saved && (
        <span className="dim" style={{ display: "block", marginTop: 8 }}>
          พูดคนเดียวไม่ถึง {MIN_SOLO_SEC} วินาที บันทึกลงคลังไม่ได้
        </span>
      )}
    </section>
  );
}
