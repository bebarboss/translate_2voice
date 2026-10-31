"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api, checkFile, fileUrl, type Fonts, type Job, type RuntimeSettings, type SubtitleStyle, type Utterance,
} from "@/lib/api";
import { TARGET_LABEL, estimateSeconds, fmtDuration, fmtTime, langName, speakerColor, speakerLabel } from "@/lib/format";
import { useTranscript } from "@/lib/useTranscript";
import LineCard from "./LineCard";
import SpeakerLanes from "./SpeakerLanes";
import SubtitleStylePanel from "./SubtitleStylePanel";
import { ArrowLeft, ArrowRight, CheckIcon, DownloadIcon, MicIcon, PlayIcon } from "./Icons";

function defaultStyle(s: RuntimeSettings | null, lang: Job["target_lang"]): SubtitleStyle {
  return {
    font: (lang === "en" ? s?.sub_font_en : s?.sub_font_th) ?? (lang === "en" ? "Noto Sans" : "Noto Sans Thai"),
    color: s?.sub_color ?? "#FFFFFF",
    outline_color: s?.sub_outline_color ?? "#000000",
    size: s?.sub_size ?? 48,
    position: s?.sub_position ?? "bottom",
  };
}

const STEM_LABEL: Record<string, string> = {
  vocals: "เสียงพูดต้นฉบับรวม",
  bgm: "เพลงและเสียงประกอบ",
  dub_voice: "เสียงพากย์อย่างเดียว",
  final_audio: "เสียงผสมสุดท้าย",
};

export default function ResultView({ job, onChanged, onEdit }: { job: Job; onChanged: () => void; onEdit: () => void }) {
  const [audio, setAudio] = useState<"dub" | "orig">("dub");
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [fonts, setFonts] = useState<Fonts | null>(null);
  const [stems, setStems] = useState<string[]>([]);
  const [burn, setBurn] = useState(job.burn_subs);
  const [style, setStyle] = useState<SubtitleStyle | null>(job.sub_style);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const resume = useRef<{ time: number; playing: boolean } | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tr = useTranscript(job, onChanged, () => videoRef.current?.currentTime ?? 0);
  const { sorted, dirty } = tr;
  const [t, setT] = useState(0);
  const [duration, setDuration] = useState(job.duration ?? 0);
  const [picked, setPicked] = useState<number | null>(null); // ประโยคที่คลิกเลือก (null = ตามวิดีโอ)
  const stopAt = useRef<number | null>(null); // เล่นเฉพาะช่วงของประโยค หยุดเมื่อถึงเวลานี้

  const total = duration || (sorted.length ? sorted[sorted.length - 1].end + 1 : 1);
  const active = useMemo(() => {
    let cur: Utterance | null = null;
    for (const u of sorted) if (t >= u.start) cur = u;
    return cur;
  }, [sorted, t]);
  const current = sorted.find((u) => u.id === picked) ?? active ?? sorted[0] ?? null;
  const idx = current ? sorted.indexOf(current) : -1;
  // แก้บทหลังพากย์แล้ว ต้องพากย์ใหม่เสียงถึงจะเปลี่ยน
  const needsDub = dirty.length > 0 || tr.saved > 0;

  useEffect(() => {
    if (!dirty.length) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty.length]);

  const seek = (sec: number) => {
    const v = videoRef.current;
    if (v) v.currentTime = sec + 0.01;
    setT(sec + 0.01);
  };
  const pick = (u: Utterance) => {
    setPicked(u.id);
    seek(u.start);
  };
  const playLine = (u: Utterance) => {
    const v = videoRef.current;
    if (!v) return;
    const d = tr.draftOf(u);
    setPicked(u.id);
    v.currentTime = d.start;
    stopAt.current = d.end + 0.15;
    v.play().catch(() => {});
  };
  const onTime = (v: HTMLVideoElement) => {
    setT(v.currentTime);
    if (stopAt.current !== null && v.currentTime >= stopAt.current) {
      stopAt.current = null;
      v.pause();
    }
  };

  const saveEdits = async () => {
    tr.setBusy("save");
    tr.setMessage(null);
    try {
      await tr.saveLines();
      tr.setMessage({ kind: "info", text: "บันทึกบทแล้ว กดพากย์ใหม่เพื่อฟังเสียงที่แก้" });
    } catch (e) {
      tr.setMessage({ kind: "error", text: (e as Error).message });
    } finally { tr.setBusy(""); }
  };
  const redub = async () => {
    tr.setBusy("dub");
    tr.setMessage(null);
    try {
      await tr.saveLines();
      await api.synthesize(job.id);
      onChanged();
    } catch (e) {
      tr.setMessage({ kind: "error", text: (e as Error).message });
      tr.setBusy("");
    }
  };
  const tooLong = (u: Utterance) => {
    const { target: text, start, end } = tr.draftOf(u);
    const limit = Math.max(0.3, end - start) * (settings?.max_speedup ?? 1.35);
    return !!text.trim() && estimateSeconds(text, job.target_lang) > limit;
  };

  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => {});
    api.fonts().then(setFonts).catch(() => setFonts({ thai: [], english: [] }));
    api.listStems(job.id).then(setStems).catch(() => {});
  }, [job.id]);

  const effective = style ?? defaultStyle(settings, job.target_lang);

  // สลับเสียงพากย์กับต้นฉบับ แล้วเล่นต่อจากเวลาเดิม
  const switchAudio = (to: "dub" | "orig") => {
    if (to === audio) return;
    const v = videoRef.current;
    if (v) resume.current = { time: v.currentTime, playing: !v.paused };
    setAudio(to);
  };
  const onLoaded = () => {
    const v = videoRef.current;
    const r = resume.current;
    if (!v || !r) return;
    v.currentTime = r.time;
    if (r.playing) v.play().catch(() => {});
    resume.current = null;
  };

  const persist = (patch: { burn_subs?: boolean; sub_style?: SubtitleStyle | null }, delay = 0) => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    setSaving(true);
    saveTimer.current = setTimeout(async () => {
      try { await api.setOptions(job.id, patch); } catch (e) { setMessage({ kind: "error", text: (e as Error).message }); }
      finally { setSaving(false); }
    }, delay);
  };

  const changeStyle = (patch: Partial<SubtitleStyle>) => {
    const next = { ...effective, ...patch };
    setStyle(next);
    persist({ sub_style: next }, 600);
  };

  const download = async (kind: "mp4" | "zip") => {
    setMessage(null);
    const url = kind === "zip" ? fileUrl.export(job.id, burn) : fileUrl.result(job.id, burn);
    setBusy(kind);
    try {
      const res = await checkFile(url);
      if (res.ok) {
        window.location.href = url;
        return;
      }
      if (res.status === 409 && burn) {
        if (window.confirm("ยังไม่มีวิดีโอฝังซับตามรูปแบบนี้ สร้างตอนนี้เลยไหม? (ไม่ต้องพากย์ใหม่ ใช้เวลาไม่กี่นาที)")) {
          await api.render(job.id);
          onChanged();
        }
        return;
      }
      setMessage({ kind: "error", text: res.message });
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy("");
    }
  };

  const layerStems = stems.filter((s) => !s.startsWith("speaker_"));
  const speakerStems = stems.filter((s) => s.startsWith("speaker_"));

  return (
    <main className="page wide">
      <div className="page-head">
        <div className="row" style={{ gap: 14, minWidth: 0 }}>
          <h1 style={{ fontSize: 24, wordBreak: "break-all" }}>{job.filename}</h1>
          <span className="badge done"><CheckIcon size={14} />พากย์{TARGET_LABEL[job.target_lang]}เสร็จแล้ว</span>
        </div>
        <div className="row">
          {needsDub && (
            <button type="button" className="btn primary" onClick={redub} disabled={!!tr.busy}>
              <MicIcon size={17} />{tr.busy === "dub" ? "กำลังส่ง..." : "พากย์ใหม่ช่วงที่แก้"}
            </button>
          )}
          <button type="button" className="btn" onClick={onEdit}>แก้บททั้งหมด</button>
          <Link href="/" className="btn">ส่งคลิปถัดไป</Link>
        </div>
      </div>

      {job.synth_stats && (
        <span className="dim" style={{ marginTop: -12 }}>
          รอบล่าสุดพากย์ใหม่ {job.synth_stats.redubbed} ประโยค · ใช้เสียงเดิม {job.synth_stats.reused} ประโยค
        </span>
      )}
      {message && <div className={`alert ${message.kind}`} role="alert">{message.text}</div>}
      {tr.message && <div className={`alert ${tr.message.kind}`} role={tr.message.kind === "error" ? "alert" : "status"}>{tr.message.text}</div>}

      <div className="split">
        <section className="main" aria-label="วิดีโอที่พากย์แล้ว">
          <div className="video-box">
            <video ref={videoRef} key={audio} src={audio === "dub" ? fileUrl.result(job.id) : fileUrl.source(job.id)}
              controls preload="metadata" playsInline
              onLoadedMetadata={(e) => { setDuration(e.currentTarget.duration); onLoaded(); }}
              onTimeUpdate={(e) => onTime(e.currentTarget)} onSeeked={(e) => setT(e.currentTarget.currentTime)}
              onPlay={() => { if (stopAt.current === null) setPicked(null); }} />
          </div>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="seg" role="group" aria-label="เสียงที่เล่น">
              <button type="button" aria-pressed={audio === "dub"} onClick={() => switchAudio("dub")}>เสียงพากย์{TARGET_LABEL[job.target_lang]}</button>
              <button type="button" aria-pressed={audio === "orig"} onClick={() => switchAudio("orig")}>เสียงต้นฉบับ</button>
            </div>
            <span className="dim">ตัวอย่างนี้ยังไม่ฝังซับ ซับจะฝังตอนดาวน์โหลด · <span className="mono">{fmtTime(t)} / {fmtTime(total)}</span></span>
          </div>

          {sorted.length > 0 && (
            <SpeakerLanes job={job} tr={tr} total={total} t={t} highlight={current?.id ?? null} onPick={pick}
              onRetimed={(sec) => seek(Math.max(0, sec - 1))}
              stemLabel="เสียงต้นฉบับ" />
          )}
          {current && (
            <section className="card tight" aria-label="แก้ช่วงที่เลือก">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h2 style={{ fontSize: 15 }}>ประโยคที่ {idx + 1} / {sorted.length}</h2>
                <div className="row" style={{ gap: 6 }}>
                  {needsDub && <span className="dim">{dirty.length ? `ยังไม่บันทึก ${dirty.length} ประโยค` : "บันทึกแล้ว รอพากย์ใหม่"}</span>}
                  <button type="button" className="btn small" onClick={saveEdits} disabled={!!tr.busy || !dirty.length}>
                    {tr.busy === "save" ? "กำลังบันทึก..." : "บันทึก"}
                  </button>
                </div>
              </div>
              <LineCard u={current} tr={tr} isLast={idx === sorted.length - 1} tooLong={tooLong(current)} retake
                onSeek={seek} onFocusText={() => { videoRef.current?.pause(); setPicked(current.id); }}
                tools={<>
                  <button type="button" className="icon-btn" disabled={idx <= 0} onClick={() => pick(sorted[idx - 1])}
                    aria-label="ประโยคก่อนหน้า"><ArrowLeft size={14} /></button>
                  <button type="button" className="icon-btn" onClick={() => playLine(current)}>
                    <PlayIcon size={12} />เล่นช่วงนี้
                  </button>
                  <button type="button" className="icon-btn" disabled={idx >= sorted.length - 1}
                    onClick={() => pick(sorted[idx + 1])} aria-label="ประโยคถัดไป"><ArrowRight size={14} /></button>
                  <span style={{ flex: 1 }} />
                </>} />
              <span className="dim">เสียงในวิดีโอยังเป็นเสียงพากย์รอบก่อน แก้บท ตัวละคร หรือแยก/รวมประโยค แล้วกด &ldquo;พากย์ใหม่ช่วงที่แก้&rdquo; ระบบพากย์เฉพาะประโยคที่เปลี่ยน</span>
            </section>
          )}

          <div className="card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2>ดาวน์โหลด</h2>
              <label className="row" style={{ gap: 8, cursor: "pointer" }}>
                <input type="checkbox" checked={burn} style={{ width: 20, height: 20, accentColor: "var(--accent)" }}
                  onChange={(e) => { setBurn(e.target.checked); persist({ burn_subs: e.target.checked }); }} />
                ฝังซับในวิดีโอ
              </label>
            </div>
            {burn && (
              <div className="card tight" style={{ background: "var(--surface-3)" }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <h2 style={{ fontSize: 15 }}>รูปแบบซับ</h2>
                  <div className="row">
                    <span className="dim" aria-live="polite">{saving ? "กำลังบันทึก..." : "บันทึกอัตโนมัติ"}</span>
                    {style && (
                      <button type="button" className="btn small" onClick={() => { setStyle(null); persist({ sub_style: null }); }}>
                        ใช้ค่าเริ่มต้น
                      </button>
                    )}
                  </div>
                </div>
                <SubtitleStylePanel style={effective} lang={job.target_lang} fonts={fonts} onChange={changeStyle} idPrefix="job" />
              </div>
            )}
            <div className="row">
              <button type="button" className="btn primary" disabled={saving || !!busy} onClick={() => download("zip")}>
                <DownloadIcon />{busy === "zip" ? "กำลังเตรียม..." : "ส่งออก (MP4 + SRT)"}
              </button>
              <button type="button" className="btn" disabled={saving || !!busy} onClick={() => download("mp4")}>
                {busy === "mp4" ? "กำลังเตรียม..." : "เฉพาะ MP4"}
              </button>
              <a className="btn" href={fileUrl.subtitles(job.id)} download>เฉพาะ SRT</a>
            </div>
            <span className="dim">
              {burn ? "วิดีโอจะมีซับฝังอยู่ในภาพ ถ้าเปลี่ยนรูปแบบซับ ระบบจะสร้างวิดีโอใหม่ก่อนดาวน์โหลด" : "วิดีโอไม่มีซับในภาพ ไฟล์ SRT แยกมาให้ใช้กับโปรแกรมตัดต่อหรืออัปโหลดขึ้นแพลตฟอร์ม"}
            </span>
          </div>
        </section>

        <aside className="side">
          <section className="card" aria-labelledby="sum" style={{ gap: 4 }}>
            <h2 id="sum" style={{ marginBottom: 8 }}>สรุปงาน</h2>
            <div className="kv"><span>ภาษาต้นฉบับ</span><span>{langName(job.detected_lang ?? job.source_lang)}</span></div>
            <div className="kv"><span>ภาษาพากย์</span><span>{TARGET_LABEL[job.target_lang]}</span></div>
            <div className="kv"><span>ความยาวคลิป</span><span className="mono">{fmtDuration(job.duration)}</span></div>
            <div className="kv"><span>ตัวละคร</span><span>{tr.speakers.length}</span></div>
            {job.source_url && <div className="kv"><span>ที่มา</span><a href={job.source_url} target="_blank" rel="noreferrer">เปิดลิงก์</a></div>}
          </section>

          <section className="card" aria-labelledby="layers" style={{ gap: 10 }}>
            <h2 id="layers">เลเยอร์เสียง (WAV)</h2>
            {speakerStems.map((s) => (
              <div key={s} className="row" style={{ fontSize: 14 }}>
                <span className="swatch" style={{ background: speakerColor(s, job.speakers) }} />
                <span style={{ flex: 1 }}>{speakerLabel(s)} · เสียงต้นฉบับ</span>
                <a href={fileUrl.stem(job.id, s)} download>ดาวน์โหลด</a>
              </div>
            ))}
            {layerStems.map((s) => (
              <div key={s} className="row" style={{ fontSize: 14 }}>
                <span className="swatch" style={{ background: "#8A919D" }} />
                <span style={{ flex: 1 }}>{STEM_LABEL[s] ?? s}</span>
                <a href={fileUrl.stem(job.id, s)} download>ดาวน์โหลด</a>
              </div>
            ))}
            {!stems.length && <span className="dim">ไม่มีไฟล์เลเยอร์</span>}
          </section>

          <p className="dim" style={{ margin: 0 }}>ก่อนเผยแพร่ โปรดตรวจว่าได้รับอนุญาตจากเจ้าของคลิปและเจ้าของเสียงแล้ว</p>
        </aside>
      </div>
    </main>
  );
}
