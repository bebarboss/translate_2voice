"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, fileUrl, type Job, type Utterance } from "@/lib/api";
import { TARGET_LABEL, estimateSeconds, fmtDuration, fmtTime, langName, stripPauseMarks } from "@/lib/format";
import { useTranscript } from "@/lib/useTranscript";
import LineCard from "./LineCard";
import ProjectPanel from "./ProjectPanel";
import RetranslatePanel from "./RetranslatePanel";
import SpeakerLanes from "./SpeakerLanes";
import StatusBadge from "./StatusBadge";
import { suggestedVoiceMap, UseSuggested, VoiceCastPicker, VoiceChoice, useVoiceCast } from "./VoiceCast";
import { ArrowLeft, MicIcon } from "./Icons";

import { tx } from "@/lib/i18n";
export default function ReviewView({ job, onChanged, onCancelEdit }: {
  job: Job;
  onChanged: () => void;
  onCancelEdit?: () => void;
}) {
  const mediaRef = useRef<HTMLMediaElement>(null);
  const tr = useTranscript(job, onChanged, () => mediaRef.current?.currentTime ?? 0);
  const { lines, sorted, speakers, dirty, busy, setBusy, message, setMessage } = tr;
  const [voiceDraft, setVoiceDraft] = useState<Record<string, string | null>>(job.voice_map ?? {});
  const vc = useVoiceCast(job.id);
  const pickVoice = (s: string, id: string | null) => setVoiceDraft((d) => ({ ...d, [s]: id }));
  const [t, setT] = useState(0);
  const [duration, setDuration] = useState(job.duration ?? 0);
  const [follow, setFollow] = useState(true);
  const [picked, setPicked] = useState<number | null>(null); // บล็อกที่คลิกเลือก (ลากขอบได้) ล้างเมื่อเล่นวิดีโอ
  const [maxSpeedup, setMaxSpeedup] = useState(1.35);
  const listRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const autoVoiceKey = useRef("");

  useEffect(() => {
    api.getSettings().then((s) => setMaxSpeedup(s.max_speedup)).catch(() => {});
  }, [job.id]);

  // เข้าหน้าแก้บทแล้วเลือกเสียงแนะนำอัตโนมัติ ตามคลังที่แพ็กเกจใช้ได้ (ทดลอง = Standard เท่านั้น)
  useEffect(() => {
    if (!vc.cast || !Object.keys(vc.voices).length) return;
    const key = `${job.id}|${speakers.join(",")}|${Object.keys(vc.voices).sort().join(",")}|${vc.cast.map((c) => c.suggestions[0]?.voice_id ?? "").join(",")}`;
    if (autoVoiceKey.current === key) return;
    autoVoiceKey.current = key;
    const suggested = suggestedVoiceMap(vc.cast, vc.voices, speakers);
    setVoiceDraft((prev) => {
      const next: Record<string, string | null> = { ...prev };
      let changed = false;
      for (const s of speakers) {
        const top = suggested[s];
        const cur = next[s] ?? null;
        // บังคับใช้เสียงแนะนำ หรือถ้าของเดิมใช้ไม่ได้ (ไม่อยู่ในคลังตามแพ็ก) ให้เปลี่ยนเป็นแนะนำ
        if (top && cur !== top) {
          next[s] = top;
          changed = true;
        } else if (cur && !vc.voices[cur]) {
          next[s] = top ?? null;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [vc.cast, vc.voices, job.id, speakers]);

  const total = duration || (sorted.length ? sorted[sorted.length - 1].end + 1 : 1);

  const active = useMemo(() => {
    let cur: Utterance | null = null;
    for (const u of sorted) if (t >= u.start) cur = u;
    return cur;
  }, [sorted, t]);
  const speaking = active && t <= active.end ? active : null;

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
    const v = mediaRef.current;
    if (v) v.currentTime = sec + 0.01;
    setT(sec + 0.01);
  }, []);

  const save = async () => {
    if (voiceDirty.length) {
      await api.setJobVoices(job.id, Object.fromEntries(voiceDirty.map((s) => [s, voiceDraft[s] ?? null])));
      onChanged();
    }
    await tr.saveLines();
  };

  const onSave = async () => {
    setBusy("save");
    setMessage(null);
    try {
      const n = dirty.length;
      const nv = voiceDirty.length;
      await save();
      const parts = [n && tx("บท {0} ประโยค", { 0: n }), nv && tx("เสียงพากย์ {0} ตัวละคร", { 0: nv })].filter(Boolean);
      setMessage({ kind: "info", text: parts.length ? tx("บันทึกแล้ว: {0}", { 0: parts.join(" และ ") }) : tx("ไม่มีอะไรเปลี่ยน") });
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally { setBusy(""); }
  };

  const onDub = async () => {
    const empty = sorted.filter((u) => !tr.draftOf(u).target.trim()).length;
    if (empty && !window.confirm(tx("มี {0} ประโยคที่บทว่าง ประโยคเหล่านั้นจะไม่ถูกพากย์ พากย์ต่อเลยไหม?", { 0: empty }))) return;
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
    const { target: text, start, end } = tr.draftOf(u);
    const dur = Math.max(0.3, end - start);
    return !!text.trim() && estimateSeconds(text, job.target_lang) > dur * maxSpeedup;
  };
  const longCount = sorted.filter(tooLong).length;

  return (
    <main className="page wide">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row" style={{ gap: 14 }}>
          {onCancelEdit ? (
            <button type="button" className="btn small" onClick={onCancelEdit} aria-label={tx("กลับหน้าผลลัพธ์")}><ArrowLeft /></button>
          ) : (
            <Link href="/jobs" className="btn small" aria-label={tx("กลับหน้างานทั้งหมด")}><ArrowLeft /></Link>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
            <span style={{ fontSize: 17, fontWeight: 600, wordBreak: "break-all" }}>{job.filename}</span>
            <span className="dim">
              {langName(job.detected_lang ?? job.source_lang)} → {tx(TARGET_LABEL[job.target_lang])} · {speakers.length}  {tx("ตัวละคร ·")} {sorted.length}  {tx("ประโยค ·")} {fmtDuration(job.duration)}
            </span>
          </div>
          {onCancelEdit ? <span className="badge awaiting_review">{tx("แก้บทเพื่อพากย์ใหม่")}</span> : <StatusBadge job={job} />}
        </div>
        <div className="row">
          <button type="button" className="btn" onClick={onSave} disabled={!!busy || !pending}>
            {busy === "save" ? tx("กำลังบันทึก...") : tx("บันทึก{0}", { 0: pending ? ` (${pending})` : "" })}
          </button>
          <button type="button" className="btn primary" onClick={onDub} disabled={!!busy || !lines?.length}>
            <MicIcon size={17} />{busy === "dub" ? tx("กำลังส่ง...") : onCancelEdit ? tx("พากย์ใหม่") : tx("เริ่มพากย์")}
          </button>
        </div>
      </div>

      {onCancelEdit && (
        <div className="alert info">{tx("แก้บท เปลี่ยนตัวละคร หรือเปลี่ยนเสียงพากย์ แล้วกดพากย์ใหม่ ระบบจะพากย์เฉพาะประโยคที่เปลี่ยน ประโยคอื่นใช้เสียงเดิม")}</div>
      )}
      {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}

      <ProjectPanel job={job} label={tr.label} onChanged={onChanged} />
      <RetranslatePanel job={job} names={tr.names} onStarted={onChanged}
        onJump={(id) => { const u = tr.sorted.find((x) => x.id === id); if (u) { setPicked(id); seek(u.start); } }}
        speakerOf={(id) => tr.sorted.find((x) => x.id === id)?.speaker} label={tr.label}
        onSpeaker={(id, s) => { const u = tr.sorted.find((x) => x.id === id); if (u) { tr.changeSpeaker(u, s); setPicked(id); } }} />

      <div className="split">
        <section className="main" aria-label={tx("วิดีโอ")}>
          <div className="video-box">
            {job.timeline ? (
              <audio ref={(el) => { mediaRef.current = el; }} src={fileUrl.source(job.id)} controls preload="metadata"
                style={{ width: "100%", margin: "24px 16px" }}
                onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
                onSeeked={(e) => setT(e.currentTarget.currentTime)}
                onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
                onPlay={() => setPicked(null)} />
            ) : (
              <video ref={(el) => { mediaRef.current = el; }} src={fileUrl.source(job.id)} controls preload="metadata" playsInline
                onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
                onSeeked={(e) => setT(e.currentTarget.currentTime)}
                onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
                onPlay={() => setPicked(null)} />
            )}
            {speaking && tr.draftOf(speaking).target && (
              <div className="caption"><span>{stripPauseMarks(tr.draftOf(speaking).target)}</span></div>
            )}
          </div>
          <div className="row dim" style={{ justifyContent: "space-between" }}>
            <span>{job.timeline
              ? tx("เสียงต้นฉบับจากไทม์ไลน์ · แก้บทด้านขวา แล้วกดเริ่มพากย์")
              : <>{tx("วิดีโอนี้เป็นเสียงต้นฉบับ ซับบนภาพคือบทพากย์")}{tx(TARGET_LABEL[job.target_lang])}{tx("ที่กำลังแก้")}</>}</span>
            <span className="mono">{fmtTime(t)} / {fmtTime(total)}</span>
          </div>

          <SpeakerLanes job={job} tr={tr} total={total} t={t} highlight={picked ?? speaking?.id ?? null}
            onPick={(u) => { setPicked(u.id); seek(u.start); }} onRetimed={(sec) => seek(Math.max(0, sec - 1))} onSeek={seek}
            voiceSlot={(s) => <VoiceChoice vc={vc} speaker={s} label={tr.label(s)} selected={voiceDraft[s] ?? null} compact />}
            voiceHead={<UseSuggested vc={vc} value={voiceDraft} onApply={(c) => setVoiceDraft((d) => ({ ...d, ...c }))} />} />

          <VoiceCastPicker vc={vc} job={{ ...job, speakers, speaker_names: tr.names }} value={voiceDraft} onChange={pickVoice} />
        </section>

        <aside className="side card" aria-label={tx("บทพากย์")} style={{ padding: 0, gap: 0, overflow: "hidden" }}>
          <div className="row" style={{ justifyContent: "space-between", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
            <h2 style={{ fontSize: 16 }}>{tx("บทพากย์")} {longCount > 0 && <span className="badge warn" style={{ marginLeft: 6 }}>{tx("ยาวเกินเวลา")} {longCount}</span>}</h2>
            <label className="row" style={{ gap: 8, fontSize: 13, color: "var(--text-2)", cursor: "pointer" }}>
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)}
                style={{ width: 18, height: 18, accentColor: "var(--accent)" }} />
              
              {tx("เลื่อนตามคลิป")}
            </label>
          </div>
          <div className="lines" ref={listRef}>
            {lines === null ? <div className="empty">{tx("กำลังโหลดบท...")}</div>
              : sorted.length === 0 ? <div className="empty">{tx("ไม่พบบทพูดในคลิปนี้")}</div>
              : sorted.map((u, idx) => (
                <LineCard key={u.id} u={u} tr={tr} isLast={idx === sorted.length - 1} retake={!!onCancelEdit}
                  active={active?.id === u.id} speaking={speaking?.id === u.id} tooLong={tooLong(u)}
                  onSeek={seek} onFocusText={() => { if (mediaRef.current?.paused) seek(u.start); }}
                  boxRef={(el) => { lineRefs.current[u.id] = el; }} />
              ))}
          </div>
        </aside>
      </div>
    </main>
  );
}
