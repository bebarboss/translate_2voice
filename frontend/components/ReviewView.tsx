"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, fileUrl, unsureFlags, type Job, type Utterance } from "@/lib/api";
import { TARGET_LABEL, estimateSeconds, fmtDuration, fmtTime, langName, speakerColor, stripPauseMarks } from "@/lib/format";
import { isChanged, useTranscript } from "@/lib/useTranscript";
import LineCard from "./LineCard";
import ProjectPanel from "./ProjectPanel";
import RetranslatePanel from "./RetranslatePanel";
import SpeakerLanes from "./SpeakerLanes";
import StatusBadge from "./StatusBadge";
import { suggestedVoiceMap, UseSuggested, VoiceCastPicker, VoiceChoice, useVoiceCast } from "./VoiceCast";
import { ArrowLeft, MicIcon, NextLineIcon, PauseIcon, PlayIcon, PrevLineIcon, SkipStartIcon } from "./Icons";

import { tx } from "@/lib/i18n";

type LineFilter = "all" | "check" | "listen" | "long" | "overlap" | "edited";
const FILTERS: { key: LineFilter; label: string }[] = [
  { key: "all", label: "ทั้งหมด" }, { key: "check", label: "ควรตรวจ" }, { key: "listen", label: "ควรฟัง" },
  { key: "long", label: "ยาวเกินเวลา" }, { key: "overlap", label: "พูดซ้อน" }, { key: "edited", label: "แก้แล้ว" },
];

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
  const [filter, setFilter] = useState<LineFilter | null>(null); // null = ค่าเริ่มต้น: ควรตรวจ ถ้ามี ไม่งั้นทั้งหมด
  const [playing, setPlaying] = useState(false);
  const [picked, setPicked] = useState<number | null>(null); // บล็อกที่คลิกเลือก (ลากขอบได้) ล้างเมื่อเล่นวิดีโอ
  const [maxSpeedup, setMaxSpeedup] = useState(1.10);
  const [redubQuote, setRedubQuote] = useState<{ credits: number; free: boolean; enough: boolean } | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const autoVoiceKey = useRef("");

  useEffect(() => {
    api.getSettings().then((s) => setMaxSpeedup(s.max_speedup)).catch(() => {});
  }, [job.id]);

  // ประมาณเครดิตพากย์ซ้ำเมื่อแก้บทหลังงานเสร็จ
  useEffect(() => {
    if (job.status !== "done" || !dirty.length) {
      setRedubQuote(null);
      return;
    }
    const editSec = dirty.reduce((s, u) => {
      const d = tr.draftOf(u);
      return s + Math.max(0, d.end - d.start);
    }, 0);
    const freeSec = dirty.reduce((s, u) => {
      if (!(u.unclear || (u.check_note || "").trim())) return s;
      const d = tr.draftOf(u);
      return s + Math.max(0, d.end - d.start);
    }, 0);
    let cancelled = false;
    api.quoteRedub(editSec, job.duration || 0, freeSec)
      .then((q) => { if (!cancelled) setRedubQuote({ credits: q.credits, free: q.free, enough: q.enough }); })
      .catch(() => { if (!cancelled) setRedubQuote(null); });
    return () => { cancelled = true; };
  }, [job.status, job.duration, dirty, tr.drafts]);

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

  /** บันทึกบท + เสียงพากย์ที่แก้ค้างไว้ (ยังไม่รีเฟรชงาน — ให้เรียก onChanged เองหลังจบขั้น) */
  const saveAll = async () => {
    if (voiceDirty.length) {
      await api.setJobVoices(job.id, Object.fromEntries(voiceDirty.map((s) => [s, voiceDraft[s] ?? null])));
    }
    await tr.saveLines();
  };

  const onSave = async () => {
    setBusy("save");
    setMessage(null);
    try {
      const n = dirty.length;
      const nv = voiceDirty.length;
      await saveAll();
      onChanged();
      const parts = [n && tx("บท {0} ประโยค", { 0: n }), nv && tx("เสียงพากย์ {0} ตัวละคร", { 0: nv })].filter(Boolean);
      setMessage({ kind: "info", text: parts.length ? tx("บันทึกแล้ว: {0}", { 0: parts.join(" และ ") }) : tx("ไม่มีอะไรเปลี่ยน") });
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally { setBusy(""); }
  };

  const onDub = async () => {
    if (unsureLines.length && !window.confirm(tx("ยังมี {0} ประโยคที่ระบบไม่แน่ใจและยังไม่ได้แก้ พากย์ตามบทเดิมเลยไหม?", { 0: unsureLines.length }))) {
      setFilter("check");
      return;
    }
    const empty = sorted.filter((u) => !tr.draftOf(u).target.trim()).length;
    setBusy("dub");
    setMessage(null);
    try {
      // กดพากย์ = บันทึกที่แก้ทั้งหมด แล้วค่อยเข้าคิวพากย์
      // บทว่าง: เซิร์ฟเวอร์ให้ AI วิเคราะห์แล้วเติมเองก่อนพากย์ (AI_FILL_EMPTY)
      const edited = [...dirty];
      await saveAll();
      if (empty) {
        setMessage({ kind: "info", text: tx("พบบทว่าง {0} ประโยค — AI จะเติมให้อัตโนมัติแล้วพากย์", { 0: empty }) });
      }
      let body: { edit_seconds?: number; free_flagged_seconds?: number } | undefined;
      if (job.status === "done" && edited.length) {
        const editSec = edited.reduce((s, u) => {
          const d = tr.draftOf(u);
          return s + Math.max(0, d.end - d.start);
        }, 0);
        const freeSec = edited.reduce((s, u) => {
          if (!(u.unclear || (u.check_note || "").trim())) return s;
          const d = tr.draftOf(u);
          return s + Math.max(0, d.end - d.start);
        }, 0);
        body = { edit_seconds: editSec, free_flagged_seconds: freeSec };
      }
      await api.synthesize(job.id, body);
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
  const checkOf = (u: Utterance) => !tr.draftOf(u).target.trim() || !!u.unclear || !!(u.check_note || "").trim() || !!(u.unclear_reason || "").trim()
    || unsureFlags(u).length > 0;
  // บรรทัดที่ระบบไม่แน่ใจและยังไม่ได้แก้บท: ต้องให้เจ้าของงานเห็นก่อนพากย์ ไม่ปล่อยผ่านเงียบ ๆ
  const unsureLines = sorted.filter((u) => unsureFlags(u).length > 0 && !isChanged(u, tr.draftOf(u)));
  const matches: Record<LineFilter, (u: Utterance) => boolean> = {
    all: () => true,
    check: checkOf,
    listen: (u) => !!(u.heard || "").trim(),
    long: tooLong,
    overlap: (u) => tr.overlaps.ids.has(u.id),
    edited: (u) => isChanged(u, tr.draftOf(u)),
  };
  const counts = Object.fromEntries(FILTERS.map((f) => [f.key, sorted.filter(matches[f.key]).length])) as Record<LineFilter, number>;
  const activeFilter: LineFilter = filter ?? (counts.check > 0 ? "check" : "all");
  const listLines = sorted.filter(matches[activeFilter]);
  const selected = sorted.find((u) => u.id === (picked ?? speaking?.id ?? active?.id ?? sorted[0]?.id)) ?? null;
  const togglePlay = () => { const m = mediaRef.current; if (m) void (m.paused ? m.play() : m.pause()); };
  const prevLine = () => { const u = [...sorted].reverse().find((x) => x.start < t - 0.4); seek(u ? u.start : 0); };
  const nextLine = () => { const u = sorted.find((x) => x.start > t + 0.05); if (u) seek(u.start); };

  return (
    <main className="page wide">
      <div className="toolbar">
        <div className="row" style={{ gap: 12, minWidth: 0 }}>
          {onCancelEdit ? (
            <button type="button" className="icon-only" onClick={onCancelEdit} aria-label={tx("กลับหน้าผลลัพธ์")}><ArrowLeft /></button>
          ) : (
            <Link href="/jobs" className="icon-only" aria-label={tx("กลับหน้างานทั้งหมด")}><ArrowLeft /></Link>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
            <span style={{ fontSize: 16, fontWeight: 600, wordBreak: "break-all" }}>{job.filename}</span>
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
          <button type="button" className="btn primary" onClick={onDub} disabled={!!busy || !lines?.length || (redubQuote != null && !redubQuote.enough)}
            title={tx("บันทึกบทและเสียงที่แก้ทั้งหมด แล้วเริ่มพากย์")}>
            <MicIcon size={17} />{busy === "dub" ? tx("กำลังบันทึกและพากย์...") : onCancelEdit ? tx("บันทึกและพากย์ใหม่") : tx("บันทึกและเริ่มพากย์")}
          </button>
        </div>
      </div>

      {onCancelEdit && (
        <div className="alert info">{tx("แก้บท เปลี่ยนตัวละคร หรือเปลี่ยนเสียงพากย์ แล้วกดบันทึกและพากย์ใหม่ ระบบบันทึกการแก้ทั้งหมดก่อน แล้วพากย์เฉพาะประโยคที่เปลี่ยน")}</div>
      )}
      {redubQuote && (
        <div className={`alert ${redubQuote.enough ? "info" : "error"}`} role="status">
          {redubQuote.free
            ? tx("พากย์ซ้ำครั้งนี้อยู่ในโควตาฟรี (ไม่เกิน 10% หรือบรรทัดที่ AI ติดธง)")
            : tx("พากย์ซ้ำครั้งนี้ใช้ประมาณ {0} เครดิต", { 0: redubQuote.credits.toFixed(2) })}
          {!redubQuote.enough && <> — <Link href="/promotions">{tx("เติมเครดิตหรืออัปเกรด")}</Link></>}
        </div>
      )}
      {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
      {unsureLines.length > 0 && (
        <div className="alert warn" role="status">
          {tx("ระบบไม่แน่ใจ {0} ประโยค (ตัวเลข ชื่อ คำเกิน หรือต้นฉบับถอดเสียงไม่ชัด) ฟังต้นฉบับแล้วแก้บทก่อนพากย์", { 0: unsureLines.length })}{" "}
          <button type="button" className="btn small" onClick={() => { setFilter("check"); const u = unsureLines[0]; setPicked(u.id); seek(u.start); }}>
            {tx("ไปที่ประโยคแรก")}
          </button>
        </div>
      )}

      <ProjectPanel job={job} label={tr.label} onChanged={onChanged} />
      <RetranslatePanel job={job} names={tr.names} onStarted={onChanged}
        onJump={(id) => { const u = tr.sorted.find((x) => x.id === id); if (u) { setPicked(id); seek(u.start); } }}
        speakerOf={(id) => tr.sorted.find((x) => x.id === id)?.speaker} label={tr.label}
        onSpeaker={(id, s) => { const u = tr.sorted.find((x) => x.id === id); if (u) { tr.changeSpeaker(u, s); setPicked(id); } }} />

      <div className="playbar" role="toolbar" aria-label={tx("ควบคุมการเล่น")}>
        <button type="button" className="icon-only" onClick={() => seek(0)} aria-label={tx("กลับไปต้นคลิป")}><SkipStartIcon /></button>
        <button type="button" className="icon-only" onClick={prevLine} aria-label={tx("ท่อนก่อนหน้า")}><PrevLineIcon /></button>
        <button type="button" className="icon-only play" onClick={togglePlay} aria-label={playing ? tx("หยุด") : tx("เล่น")}>
          {playing ? <PauseIcon size={18} /> : <PlayIcon size={18} />}
        </button>
        <button type="button" className="icon-only" onClick={nextLine} aria-label={tx("ท่อนถัดไป")}><NextLineIcon /></button>
        <span className="timecode mono">{fmtTime(t)}<small> / {fmtTime(total)}</small></span>
        <label className="chip follow">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
          {tx("เลื่อนตามคลิป")}
        </label>
      </div>

      <div className="editor-grid">
        <section className="editor-col video-col" aria-label={tx("วิดีโอ")}>
          <div className="video-box">
            {job.timeline ? (
              <audio ref={(el) => { mediaRef.current = el; }} src={fileUrl.source(job.id)} preload="metadata" hidden
                onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
                onSeeked={(e) => setT(e.currentTarget.currentTime)}
                onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
                onPlay={() => { setPicked(null); setPlaying(true); }} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />
            ) : (
              <video ref={(el) => { mediaRef.current = el; }} src={fileUrl.source(job.id)} preload="metadata" playsInline onClick={togglePlay}
                onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
                onSeeked={(e) => setT(e.currentTarget.currentTime)}
                onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
                onPlay={() => { setPicked(null); setPlaying(true); }} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />
            )}
            {speaking && tr.draftOf(speaking).target && (
              <div className="caption"><span>{stripPauseMarks(tr.draftOf(speaking).target)}</span></div>
            )}
          </div>
          <p className="dim video-note">{job.timeline
            ? tx("เสียงต้นฉบับจากไทม์ไลน์ · แก้บทด้านขวา แล้วกดเริ่มพากย์")
            : <>{tx("วิดีโอนี้เป็นเสียงต้นฉบับ ซับบนภาพคือบทพากย์")}{tx(TARGET_LABEL[job.target_lang])}{tx("ที่กำลังแก้")}</>}</p>
        </section>

        <aside className="editor-col lines-col" aria-label={tx("บทพากย์")}>
          <div className="col-head">
            <h2>{tx("บทพากย์")}</h2>
            <div className="chips" role="group" aria-label={tx("กรองบท")}>
              {FILTERS.map((f) => (
                <button key={f.key} type="button" className="chip filter" aria-pressed={activeFilter === f.key} onClick={() => setFilter(f.key)}>
                  {tx(f.label)} <span className="n mono">{counts[f.key]}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="lines" ref={listRef}>
            {lines === null ? <div className="empty">{tx("กำลังโหลดบท...")}</div>
              : sorted.length === 0 ? <div className="empty">{tx("ไม่พบบทพูดในคลิปนี้")}</div>
              : listLines.length === 0 ? <div className="empty">{tx("ไม่มีบทในหมวดนี้")}</div>
              : listLines.map((u) => {
                const d = tr.draftOf(u);
                return (
                  <button key={u.id} type="button" ref={(el) => { lineRefs.current[u.id] = el as unknown as HTMLDivElement | null; }}
                    className={`line-row${selected?.id === u.id ? " selected" : ""}${speaking?.id === u.id ? " speaking" : ""}${unsureFlags(u).length && !isChanged(u, d) ? " uncertain" : ""}`}
                    aria-pressed={selected?.id === u.id}
                    onClick={() => { setPicked(u.id); seek(u.start); }}>
                    <span className="lr-top">
                      <span className="mono lr-time">{fmtTime(u.start)}</span>
                      <i className="swatch" style={{ background: speakerColor(d.speaker, tr.speakers) }} />
                      <span className="lr-name">{tr.label(d.speaker)}</span>
                      <span className="lr-badges">
                        {isChanged(u, d) && <span className="badge ok">{tx("แก้แล้ว")}</span>}
                        {tr.overlaps.ids.has(u.id) && <span className="badge info">{tx("พูดซ้อน")}</span>}
                        {tooLong(u) && <span className="badge warn">{tx("ยาวเกินเวลา")}</span>}
                        {unsureFlags(u).length > 0 && !isChanged(u, d)
                          ? <span className="badge warn" title={unsureFlags(u).map((f) => f.reason).join("\n")}>{tx("ระบบไม่แน่ใจ")}</span>
                          : checkOf(u) && <span className="badge warn">{tx("ควรตรวจ")}</span>}
                        {!!(u.heard || "").trim() && <span className="badge warn">{tx("ควรฟัง")}</span>}
                      </span>
                    </span>
                    <span className="lr-target">{stripPauseMarks(d.target) || tx("(ยังไม่มีบทพากย์)")}</span>
                    <span className="lr-src">{u.source}</span>
                  </button>
                );
              })}
          </div>
        </aside>

        <aside className="editor-col inspector" aria-label={tx("ท่อนที่เลือก")}>
          {!selected ? <div className="empty">{tx("เลือกท่อนจากรายการบทเพื่อแก้")}</div> : (() => {
            const d = tr.draftOf(selected);
            const dur = Math.max(0.3, d.end - d.start);
            const ratio = d.target.trim() ? estimateSeconds(d.target, job.target_lang) / dur : 0;
            const fitTone = ratio <= 1 ? "ok" : ratio <= 1.25 ? "warn" : "bad";
            const moods = tr.moodsOf(d.speaker);
            return (
              <>
                <div className="col-head insp-head">
                  <i className="swatch lg" style={{ background: speakerColor(d.speaker, tr.speakers) }} />
                  <h2>{tr.label(d.speaker)}</h2>
                  <span className="mono dim">{fmtTime(d.start)}–{fmtTime(d.end)}</span>
                </div>
                <div className="insp-body">
                  <div className="insp-voice">
                    <span className="label">{tx("เสียงพากย์ของ{0}", { 0: tr.label(d.speaker) })}</span>
                    <VoiceChoice vc={vc} speaker={d.speaker} label={tr.label(d.speaker)} selected={voiceDraft[d.speaker] ?? null} />
                  </div>
                  <div className="insp-fit" title={tx("ความยาวบทพากย์เทียบกับช่องเวลาของท่อนนี้")}>
                    <span className="row" style={{ justifyContent: "space-between" }}>
                      <span className="label">{tx("ความพอดีกับช่องเวลา")}</span>
                      <b className={`mono fit-${fitTone}`}>{ratio ? `${Math.round(ratio * 100)}%` : "—"}</b>
                    </span>
                    <span className="fit-bar" role="img" aria-label={`${Math.round(ratio * 100)}%`}>
                      <span className={`fit-fill fit-${fitTone}`} style={{ width: `${Math.min(ratio, 1.5) / 1.5 * 100}%` }} />
                      <span className="fit-mark" />
                    </span>
                  </div>
                  {moods.length === 0 && (
                    <p className="dim insp-note">{tx("เสียงนี้มีอารมณ์เดียว จึงไม่มีตัวเลือกอารมณ์ เลือกเสียงที่มีหลายอารมณ์ในคลังเพื่อกำหนดอารมณ์รายท่อน")}</p>
                  )}
                  <LineCard key={selected.id} u={selected} tr={tr} isLast={sorted[sorted.length - 1]?.id === selected.id} retake={!!onCancelEdit}
                    active speaking={speaking?.id === selected.id} tooLong={tooLong(selected)}
                    onSeek={seek} onFocusText={() => { if (mediaRef.current?.paused) seek(selected.start); }} />
                </div>
              </>
            );
          })()}
        </aside>
      </div>

      <SpeakerLanes job={job} tr={tr} total={total} t={t} highlight={picked ?? speaking?.id ?? null}
        onPick={(u) => { setPicked(u.id); seek(u.start); }} onRetimed={(sec) => seek(Math.max(0, sec - 1))} onSeek={seek}
        voiceSlot={(s) => <VoiceChoice vc={vc} speaker={s} label={tr.label(s)} selected={voiceDraft[s] ?? null} compact />}
        voiceHead={<UseSuggested vc={vc} value={voiceDraft} onApply={(c) => setVoiceDraft((d) => ({ ...d, ...c }))} />} />

      <VoiceCastPicker vc={vc} job={{ ...job, speakers, speaker_names: tr.names }} value={voiceDraft} onChange={pickVoice} />
    </main>
  );
}
