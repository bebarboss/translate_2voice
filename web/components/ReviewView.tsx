"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, fileUrl, type Job, type Utterance, type UtteranceEdit } from "@/lib/api";
import {
  TARGET_LABEL, estimateSeconds, fmtDuration, fmtTime, langName, speakerColor, speakerLabel,
} from "@/lib/format";
import StatusBadge from "./StatusBadge";
import VoiceCast from "./VoiceCast";
import { ArrowLeft, MergeIcon, MicIcon, ScissorsIcon, XIcon } from "./Icons";

type Draft = { target: string; speaker: string };

const NEW_SPEAKER = "__new__";

export default function ReviewView({ job, onChanged, onCancelEdit }: {
  job: Job;
  onChanged: () => void;
  onCancelEdit?: () => void;
}) {
  const [lines, setLines] = useState<Utterance[] | null>(null);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [voiceDraft, setVoiceDraft] = useState<Record<string, string | null>>(job.voice_map ?? {});
  const [t, setT] = useState(0);
  const [duration, setDuration] = useState(job.duration ?? 0);
  const [follow, setFollow] = useState(true);
  const [maxSpeedup, setMaxSpeedup] = useState(1.35);
  const [busy, setBusy] = useState<"" | "save" | "dub" | "edit">("");
  // ตัวละครทั้งหมด (เพิ่มตัวละครแล้วใช้ได้ทันที ไม่ต้องรอโหลดงานใหม่)
  const [speakers, setSpeakers] = useState<string[]>(job.speakers);
  const [removing, setRemoving] = useState<{ speaker: string; into: string } | null>(null);
  const [message, setMessage] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const cursors = useRef<Record<number, number>>({}); // ตำแหน่งเคอร์เซอร์ล่าสุดในบทของแต่ละประโยค ใช้เป็นจุดแยก

  useEffect(() => { setSpeakers(job.speakers); }, [job.speakers]);

  const applyLines = (u: Utterance[]) => {
    setLines(u);
    setDrafts(Object.fromEntries(u.map((x) => [x.id, { target: x.target, speaker: x.speaker }])));
  };

  useEffect(() => {
    api.getTranscript(job.id).then(applyLines).catch((e) => setMessage({ kind: "error", text: e.message }));
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
  // ตัวละครที่เปลี่ยนเสียงพากย์แต่ยังไม่บันทึก
  const voiceDirty = useMemo(() => speakers.filter(
    (s) => (voiceDraft[s] ?? null) !== (job.voice_map?.[s] ?? null)), [speakers, job.voice_map, voiceDraft]);
  const pending = dirty.length + voiceDirty.length;

  useEffect(() => {
    if (!pending) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [pending]);

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
    if (voiceDirty.length) {
      await api.setJobVoices(job.id, Object.fromEntries(voiceDirty.map((s) => [s, voiceDraft[s] ?? null])));
      onChanged();
    }
    if (!dirty.length) return true;
    const edits: UtteranceEdit[] = dirty.map((u) => {
      const d = drafts[u.id];
      const e: UtteranceEdit = { id: u.id };
      if (d.target !== u.target) e.target = d.target;
      if (d.speaker !== u.speaker) e.speaker = d.speaker;
      return e;
    });
    applyLines(await api.saveTranscript(job.id, edits));
    return true;
  };

  // แยก/รวมประโยค และเพิ่มลบตัวละคร ทำบนเซิร์ฟเวอร์ บันทึกที่แก้ค้างไว้ก่อน แล้วโหลดบทใหม่
  const restructure = async (op: () => Promise<unknown>, done: string) => {
    setBusy("edit");
    setMessage(null);
    try {
      await save();
      await op();
      applyLines(await api.getTranscript(job.id));
      onChanged();
      setMessage({ kind: "info", text: done });
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally { setBusy(""); }
  };

  const onSplit = (u: Utterance) => {
    const draft = drafts[u.id]?.target ?? u.target;
    // เซิร์ฟเวอร์ตัดช่องว่างหัวท้ายบท เลื่อนตำแหน่งเคอร์เซอร์ตาม
    const pos = (cursors.current[u.id] ?? 0) - (draft.length - draft.trimStart().length);
    const at: { at?: number; pos?: number } = {};
    if (pos > 0 && pos < draft.trim().length) at.pos = pos;
    else if (t > u.start + 0.2 && t < u.end - 0.2) at.at = t;
    else {
      setMessage({ kind: "error", text: "วางเคอร์เซอร์ในบทตรงที่จะแยก หรือเล่นวิดีโอไปหยุดตรงที่คนที่สองเริ่มพูด แล้วกดแยกอีกครั้ง" });
      return;
    }
    restructure(() => api.splitLine(job.id, u.id, at), "แยกประโยคแล้ว เปลี่ยนตัวละครของท่อนหลังได้เลย");
  };

  const onMerge = (u: Utterance) => restructure(() => api.mergeLine(job.id, u.id), "รวมกับประโยคถัดไปแล้ว");

  const onSpeakerChange = async (u: Utterance, value: string) => {
    if (value !== NEW_SPEAKER) { setDraft(u.id, { speaker: value }); return; }
    setBusy("edit");
    try {
      const j = await api.addSpeaker(job.id);
      setSpeakers(j.speakers);
      setDraft(u.id, { speaker: j.speakers[j.speakers.length - 1] });
      onChanged();
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally { setBusy(""); }
  };

  const onRemoveSpeaker = (speaker: string, into: string) => {
    setRemoving(null);
    restructure(async () => setSpeakers((await api.removeSpeaker(job.id, speaker, into || undefined)).speakers),
      into ? `ลบ${speakerLabel(speaker)} ย้ายประโยคไปให้${speakerLabel(into)}แล้ว` : `ลบ${speakerLabel(speaker)}แล้ว`);
  };

  const onSave = async () => {
    setBusy("save");
    setMessage(null);
    try {
      const n = dirty.length;
      const nv = voiceDirty.length;
      await save();
      const parts = [n && `บท ${n} ประโยค`, nv && `เสียงพากย์ ${nv} ตัวละคร`].filter(Boolean);
      setMessage({ kind: "info", text: parts.length ? `บันทึกแล้ว: ${parts.join(" และ ")}` : "ไม่มีอะไรเปลี่ยน" });
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
              {langName(job.detected_lang ?? job.source_lang)} → {TARGET_LABEL[job.target_lang]} · {speakers.length} ตัวละคร · {sorted.length} ประโยค · {fmtDuration(job.duration)}
            </span>
          </div>
          {onCancelEdit ? <span className="badge awaiting_review">แก้บทเพื่อพากย์ใหม่</span> : <StatusBadge job={job} />}
        </div>
        <div className="row">
          <button type="button" className="btn" onClick={onSave} disabled={!!busy || !pending}>
            {busy === "save" ? "กำลังบันทึก..." : `บันทึก${pending ? ` (${pending})` : ""}`}
          </button>
          <button type="button" className="btn primary" onClick={onDub} disabled={!!busy || !lines?.length}>
            <MicIcon size={17} />{busy === "dub" ? "กำลังส่ง..." : onCancelEdit ? "พากย์ใหม่" : "เริ่มพากย์"}
          </button>
        </div>
      </div>

      {onCancelEdit && (
        <div className="alert info">แก้บท เปลี่ยนตัวละคร หรือเปลี่ยนเสียงพากย์ แล้วกดพากย์ใหม่ ระบบจะพากย์เฉพาะประโยคที่เปลี่ยน ประโยคอื่นใช้เสียงเดิม</div>
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
              {speakers.map((s) => {
                const color = speakerColor(s, speakers);
                const count = sorted.filter((u) => (drafts[u.id]?.speaker ?? u.speaker) === s).length;
                return (
                  <div key={s} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <div className="lane">
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
                    <button type="button" className="icon-btn" aria-label={`ลบ${speakerLabel(s)}`} title="ลบตัวละครนี้"
                      disabled={!!busy || speakers.length < 2}
                      onClick={() => count ? setRemoving({ speaker: s, into: speakers.find((x) => x !== s) ?? "" })
                        : onRemoveSpeaker(s, "")}>
                      <XIcon />
                    </button>
                  </div>
                  {removing?.speaker === s && (
                    <div className="lane-remove">
                      <span>ลบ{speakerLabel(s)} ย้าย {count} ประโยคไปให้</span>
                      <label className="sr-only" htmlFor={`into-${s}`}>ตัวละครที่รับประโยคไป</label>
                      <select id={`into-${s}`} className="spk-select" value={removing.into}
                        onChange={(e) => setRemoving({ speaker: s, into: e.target.value })}>
                        {speakers.filter((x) => x !== s).map((x) => <option key={x} value={x}>{speakerLabel(x)}</option>)}
                      </select>
                      <button type="button" className="btn small danger" onClick={() => onRemoveSpeaker(s, removing.into)}>ลบ</button>
                      <button type="button" className="btn small" onClick={() => setRemoving(null)}>ยกเลิก</button>
                    </div>
                  )}
                  </div>
                );
              })}
            </div>
            <span className="dim">แยกเสียงผิด? คนเดียวถูกแยกเป็นสองตัวละคร กด ✕ เพื่อรวมเข้าตัวอื่น · สองคนถูกรวมเป็นตัวเดียว เลือก “+ ตัวละครใหม่” ในช่องตัวละครของประโยค · สองคนพูดในประโยคเดียว กด “แยกประโยค”</span>
          </div>

          <VoiceCast job={{ ...job, speakers }} value={voiceDraft}
            onChange={(s, id) => setVoiceDraft((d) => ({ ...d, [s]: id }))} />
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
              : sorted.map((u, idx) => {
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
                      <span className="swatch" style={{ background: speakerColor(d.speaker, speakers) }} />
                      <label className="sr-only" htmlFor={`spk-${u.id}`}>ตัวละครของประโยคที่ {u.id}</label>
                      <select id={`spk-${u.id}`} className="spk-select" value={d.speaker} disabled={busy === "edit"}
                        onChange={(e) => onSpeakerChange(u, e.target.value)}>
                        {speakers.map((s) => <option key={s} value={s}>{speakerLabel(s)}</option>)}
                        <option value={NEW_SPEAKER}>+ ตัวละครใหม่</option>
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
                      onSelect={(e) => { cursors.current[u.id] = e.currentTarget.selectionStart; }}
                      onFocus={() => { if (videoRef.current?.paused) seek(u.start); }} />
                    <div className="line-tools">
                      <button type="button" className="icon-btn" onClick={() => onSplit(u)} disabled={!!busy}
                        title="แยกตรงเคอร์เซอร์ในบท หรือตรงเวลาที่หยุดวิดีโอไว้">
                        <ScissorsIcon />แยกประโยค
                      </button>
                      <button type="button" className="icon-btn" onClick={() => onMerge(u)}
                        disabled={!!busy || idx === sorted.length - 1} title="รวมกับประโยคถัดไป">
                        <MergeIcon />รวมกับถัดไป
                      </button>
                    </div>
                  </div>
                );
              })}
          </div>
        </aside>
      </div>
    </main>
  );
}
