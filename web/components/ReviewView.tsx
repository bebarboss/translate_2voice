"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, fileUrl, type Job, type Utterance, type UtteranceEdit } from "@/lib/api";
import {
  TARGET_LABEL, estimateSeconds, fmtDuration, fmtTime, langName, speakerColor, speakerLabel,
} from "@/lib/format";
import StatusBadge from "./StatusBadge";
import { ArrowLeft, MicIcon } from "./Icons";

type Draft = { target: string; speaker: string };

export default function ReviewView({ job, onChanged, onCancelEdit }: {
  job: Job;
  onChanged: () => void;
  onCancelEdit?: () => void;
}) {
  const [lines, setLines] = useState<Utterance[] | null>(null);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [t, setT] = useState(0);
  const [duration, setDuration] = useState(job.duration ?? 0);
  const [follow, setFollow] = useState(true);
  const [maxSpeedup, setMaxSpeedup] = useState(1.35);
  const [busy, setBusy] = useState<"" | "save" | "dub">("");
  const [message, setMessage] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    api.getTranscript(job.id).then((u) => {
      setLines(u);
      setDrafts(Object.fromEntries(u.map((x) => [x.id, { target: x.target, speaker: x.speaker }])));
    }).catch((e) => setMessage({ kind: "error", text: e.message }));
    api.getSettings().then((s) => setMaxSpeedup(s.max_speedup)).catch(() => {});
  }, [job.id]);

  const sorted = useMemo(() => (lines ?? []).slice().sort((a, b) => a.start - b.start), [lines]);
  const total = duration || (sorted.length ? sorted[sorted.length - 1].end + 1 : 1);

  const active = useMemo(() => {
    let cur: Utterance | null = null;
    for (const u of sorted) if (t >= u.start) cur = u;
    return cur;
  }, [sorted, t]);
  const speaking = active && t <= active.end ? active : null;

  const dirty = useMemo(() => (lines ?? []).filter((u) => {
    const d = drafts[u.id];
    return d && (d.target !== u.target || d.speaker !== u.speaker);
  }), [lines, drafts]);

  useEffect(() => {
    if (!dirty.length) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty.length]);

  // เลื่อนรายการบทให้ประโยคที่กำลังพูดอยู่ในกรอบ (เลื่อนเฉพาะกล่องบท ไม่เลื่อนทั้งหน้า)
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

  const setDraft = (id: number, patch: Partial<Draft>) =>
    setDrafts((d) => ({ ...d, [id]: { ...d[id], ...patch } }));

  const save = async (): Promise<boolean> => {
    if (!lines) return false;
    if (!dirty.length) return true;
    const edits: UtteranceEdit[] = dirty.map((u) => {
      const d = drafts[u.id];
      const e: UtteranceEdit = { id: u.id };
      if (d.target !== u.target) e.target = d.target;
      if (d.speaker !== u.speaker) e.speaker = d.speaker;
      return e;
    });
    const updated = await api.saveTranscript(job.id, edits);
    setLines(updated);
    setDrafts(Object.fromEntries(updated.map((x) => [x.id, { target: x.target, speaker: x.speaker }])));
    return true;
  };

  const onSave = async () => {
    setBusy("save");
    setMessage(null);
    try {
      const n = dirty.length;
      await save();
      setMessage({ kind: "info", text: n ? `บันทึกบทแล้ว ${n} ประโยค` : "ไม่มีบทที่เปลี่ยน" });
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally { setBusy(""); }
  };

  const onDub = async () => {
    const empty = sorted.filter((u) => !drafts[u.id]?.target.trim()).length;
    if (empty && !window.confirm(`มี ${empty} ประโยคที่บทว่าง ประโยคเหล่านั้นจะไม่ถูกพากย์ พากย์ต่อเลยไหม?`)) return;
    setBusy("dub");
    setMessage(null);
    try {
      await save();
      await api.synthesize(job.id);
      onChanged();
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
      setBusy("");
    }
  };

  const tooLong = (u: Utterance) => {
    const text = drafts[u.id]?.target ?? u.target;
    const dur = Math.max(0.3, u.end - u.start);
    return !!text.trim() && estimateSeconds(text, job.target_lang) > dur * maxSpeedup;
  };
  const longCount = sorted.filter(tooLong).length;
  const playheadPct = `${Math.min(100, (t / total) * 100)}%`;

  return (
    <main className="page wide">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row" style={{ gap: 14 }}>
          {onCancelEdit ? (
            <button type="button" className="btn small" onClick={onCancelEdit} aria-label="กลับหน้าผลลัพธ์"><ArrowLeft /></button>
          ) : (
            <Link href="/jobs" className="btn small" aria-label="กลับหน้างานทั้งหมด"><ArrowLeft /></Link>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
            <span style={{ fontSize: 17, fontWeight: 600, wordBreak: "break-all" }}>{job.filename}</span>
            <span className="dim">
              {langName(job.detected_lang ?? job.source_lang)} → {TARGET_LABEL[job.target_lang]} · {job.speakers.length} ตัวละคร · {sorted.length} ประโยค · {fmtDuration(job.duration)}
            </span>
          </div>
          {onCancelEdit ? <span className="badge awaiting_review">แก้บทเพื่อพากย์ใหม่</span> : <StatusBadge job={job} />}
        </div>
        <div className="row">
          <button type="button" className="btn" onClick={onSave} disabled={!!busy || !dirty.length}>
            {busy === "save" ? "กำลังบันทึก..." : `บันทึกบท${dirty.length ? ` (${dirty.length})` : ""}`}
          </button>
          <button type="button" className="btn primary" onClick={onDub} disabled={!!busy || !lines?.length}>
            <MicIcon size={17} />{busy === "dub" ? "กำลังส่ง..." : onCancelEdit ? "พากย์ใหม่" : "เริ่มพากย์"}
          </button>
        </div>
      </div>

      {onCancelEdit && (
        <div className="alert info">แก้บทหรือเปลี่ยนตัวละคร แล้วกดพากย์ใหม่ ระบบจะพากย์เฉพาะประโยคที่เปลี่ยน ประโยคอื่นใช้เสียงเดิม</div>
      )}
      {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}

      <div className="split">
        <section className="main" aria-label="วิดีโอ">
          <div className="video-box">
            <video ref={videoRef} src={fileUrl.source(job.id)} controls preload="metadata" playsInline
              onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
              onSeeked={(e) => setT(e.currentTarget.currentTime)}
              onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)} />
            {speaking && drafts[speaking.id]?.target && (
              <div className="caption"><span>{drafts[speaking.id].target}</span></div>
            )}
          </div>
          <div className="row dim" style={{ justifyContent: "space-between" }}>
            <span>วิดีโอนี้เป็นเสียงต้นฉบับ ซับบนภาพคือบทพากย์{TARGET_LABEL[job.target_lang]}ที่กำลังแก้</span>
            <span className="mono">{fmtTime(t)} / {fmtTime(total)}</span>
          </div>

          <div className="card tight">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2 style={{ fontSize: 15 }}>เลเยอร์เสียงตัวละคร</h2>
              <span className="dim">คลิกบล็อกเพื่อกระโดดไปประโยคนั้น</span>
            </div>
            <div className="lanes">
              {job.speakers.map((s) => {
                const color = speakerColor(s, job.speakers);
                return (
                  <div className="lane" key={s}>
                    <div className="who"><span className="swatch" style={{ background: color }} />{speakerLabel(s)}</div>
                    <div className="track">
                      {sorted.filter((u) => (drafts[u.id]?.speaker ?? u.speaker) === s).map((u) => (
                        <button key={u.id} type="button" className="block"
                          aria-label={`${speakerLabel(s)} ${fmtTime(u.start)}`}
                          onClick={() => seek(u.start)}
                          style={{
                            left: `${(u.start / total) * 100}%`,
                            width: `${((u.end - u.start) / total) * 100}%`,
                            background: color,
                            opacity: speaking?.id === u.id ? 1 : 0.45,
                          }} />
                      ))}
                      <div className="playhead" style={{ left: playheadPct }} />
                    </div>
                    <a href={fileUrl.stem(job.id, s)} target="_blank" rel="noreferrer" className="dim" style={{ flex: "none", color: "var(--accent)" }}>ฟังเสียงแยก</a>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        <aside className="side card" aria-label="บทพากย์" style={{ padding: 0, gap: 0, overflow: "hidden" }}>
          <div className="row" style={{ justifyContent: "space-between", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
            <h2 style={{ fontSize: 16 }}>บทพากย์ {longCount > 0 && <span className="badge warn" style={{ marginLeft: 6 }}>ยาวเกินเวลา {longCount}</span>}</h2>
            <label className="row" style={{ gap: 8, fontSize: 13, color: "var(--text-2)", cursor: "pointer" }}>
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)}
                style={{ width: 18, height: 18, accentColor: "var(--accent)" }} />
              เลื่อนตามคลิป
            </label>
          </div>
          <div className="lines" ref={listRef}>
            {lines === null ? <div className="empty">กำลังโหลดบท...</div>
              : sorted.length === 0 ? <div className="empty">ไม่พบบทพูดในคลิปนี้</div>
              : sorted.map((u) => {
                const d = drafts[u.id] ?? { target: u.target, speaker: u.speaker };
                const isActiveLine = active?.id === u.id;
                const changed = d.target !== u.target || d.speaker !== u.speaker;
                return (
                  <div key={u.id} ref={(el) => { lineRefs.current[u.id] = el; }}
                    className={`line${isActiveLine ? " active" : ""}${speaking?.id === u.id ? " speaking" : ""}`}>
                    <div className="row" style={{ gap: 8 }}>
                      <button type="button" className="time-btn" onClick={() => seek(u.start)} aria-label={`ไปที่ ${fmtTime(u.start)}`}>
                        {fmtTime(u.start)}
                      </button>
                      <span className="swatch" style={{ background: speakerColor(d.speaker, job.speakers) }} />
                      <label className="sr-only" htmlFor={`spk-${u.id}`}>ตัวละครของประโยคที่ {u.id}</label>
                      <select id={`spk-${u.id}`} className="spk-select" value={d.speaker}
                        onChange={(e) => setDraft(u.id, { speaker: e.target.value })}>
                        {job.speakers.map((s) => <option key={s} value={s}>{speakerLabel(s)}</option>)}
                      </select>
                      <span style={{ marginLeft: "auto" }} className="row">
                        {changed && <span className="badge awaiting_review">แก้แล้ว</span>}
                        {tooLong(u) && <span className="badge warn">ยาวเกินเวลา</span>}
                      </span>
                    </div>
                    <p className="src">{u.source}</p>
                    <label className="sr-only" htmlFor={`tg-${u.id}`}>บทพากย์ประโยคที่ {u.id}</label>
                    <textarea id={`tg-${u.id}`} className="textarea" rows={2} value={d.target}
                      onChange={(e) => setDraft(u.id, { target: e.target.value })}
                      onFocus={() => { if (videoRef.current?.paused) seek(u.start); }} />
                  </div>
                );
              })}
          </div>
        </aside>
      </div>
    </main>
  );
}
