"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fileUrl, type Job, type LibraryVoice, type SpeakerVoice } from "@/lib/api";
import { GENDER_LABEL, speakerColor, speakerLabel } from "@/lib/format";
import VoiceAvatar from "./VoiceAvatar";
import VoicePicker from "./VoicePicker";
import { PreviewButton, usePreview } from "./VoicePreview";

/** เสียงในคลังที่พร้อมใช้ และเสียงที่แนะนำของแต่ละตัวละคร (ใช้ร่วมกันระหว่างรายการเสียงพากย์และเลเยอร์บนเส้นเวลา)
 *  picking: ตัวละครที่กำลังเปิดแถบเลือกเสียงอยู่ */
export function useVoiceCast(jobId: string) {
  const [cast, setCast] = useState<SpeakerVoice[] | null>(null);
  const [voices, setVoices] = useState<Record<string, LibraryVoice>>({});
  const [error, setError] = useState("");
  const [picking, setPicking] = useState<string | null>(null);

  useEffect(() => {
    api.listVoices()
      .then((v) => setVoices(Object.fromEntries(v.filter((x) => x.status === "ready").map((x) => [x.id, x]))))
      .catch(() => {});
    api.jobVoices(jobId).then(setCast).catch((e) => setError(e.message));
  }, [jobId]);

  return { cast, voices, error, picking, open: setPicking, close: () => setPicking(null) };
}
export type VoiceCastState = ReturnType<typeof useVoiceCast>;

const describe = (v: LibraryVoice) => [v.name, v.gender && GENDER_LABEL[v.gender], v.tone].filter(Boolean).join(" · ");
const scoreOf = (c: SpeakerVoice | undefined, id: string) => c?.suggestions.find((s) => s.voice_id === id)?.score;
const topOf = (c: SpeakerVoice | undefined, voices: Record<string, LibraryVoice>) =>
  c?.suggestions.find((s) => voices[s.voice_id])?.voice_id;

/** ปุ่มแสดงเสียงที่ตัวละครใช้อยู่ กดแล้วเปิดแถบเลือกเสียง compact = แบบย่อสำหรับเลเยอร์บนเส้นเวลา */
export function VoiceChoice({ vc, speaker, label, selected, compact }: {
  vc: VoiceCastState;
  speaker: string;
  label: string;
  selected: string | null;
  compact?: boolean;
}) {
  const c = vc.cast?.find((x) => x.speaker === speaker);
  const v = selected ? vc.voices[selected] : undefined;
  const top = topOf(c, vc.voices);
  const score = selected ? scoreOf(c, selected) : undefined;
  return (
    <button type="button" className={`voice-choice${compact ? " compact" : ""}`} onClick={() => vc.open(speaker)}
      aria-label={`เลือกเสียงพากย์ของ${label}`} title={v ? `เสียงพากย์: ${describe(v)}` : "เลือกเสียงพากย์จากคลัง"}>
      {v ? (
        <>
          <VoiceAvatar name={v.name} size={compact ? 22 : 32} url={v.image ? fileUrl.voiceImage(v.id, v.updated_at) : ""} />
          <span className="voice-choice-name">
            {selected === top ? "★ " : ""}{compact ? v.name : describe(v)}
            {!compact && score != null && <span className="dim"> · ใกล้เคียง {Math.round(score * 100)}%</span>}
          </span>
        </>
      ) : compact ? (
        <span className="voice-choice-name">เสียงต้นฉบับ</span>
      ) : (
        <span className="voice-choice-name">
          {selected ? "เสียงที่เลือกไว้ถูกลบแล้ว ใช้เสียงต้นฉบับ" : "เสียงต้นฉบับ (เลียนเสียงนักแสดง)"}
          {top && <span className="dim"> · แนะนำ {vc.voices[top].name}</span>}
        </span>
      )}
      <span className="dim" style={{ marginLeft: "auto", flex: "none" }}>{compact ? "›" : "เปลี่ยน ›"}</span>
    </button>
  );
}

/** แถบเลือกเสียงด้านขวาของตัวละครที่กำลังเลือก (วางไว้ที่เดียวต่อหน้า) */
export function VoiceCastPicker({ vc, job, value, onChange }: {
  vc: VoiceCastState;
  job: Job;
  value: Record<string, string | null>;
  onChange: (speaker: string, voiceId: string | null) => void;
}) {
  const c = vc.cast?.find((x) => x.speaker === vc.picking);
  if (!c) return null;
  const chosen = value[c.speaker];
  return (
    // เสียงที่เลือกไว้ถูกลบจากคลังแล้ว = ใช้เสียงต้นฉบับอยู่
    <VoicePicker cast={c} voices={vc.voices} selected={chosen && vc.voices[chosen] ? chosen : null}
      label={speakerLabel(c.speaker, job.speaker_names)} color={speakerColor(c.speaker, job.speakers)}
      stemUrl={fileUrl.stem(job.id, c.speaker)}
      onPick={(id) => onChange(c.speaker, id)} onClose={vc.close} />
  );
}

/** เลือกเสียงจากคลังให้ตัวละครแต่ละตัว (null = เลียนเสียงนักแสดงต้นฉบับ) */
export default function VoiceCast({ job, vc, value, onChange }: {
  job: Job;
  vc: VoiceCastState;
  value: Record<string, string | null>;
  onChange: (speaker: string, voiceId: string | null) => void;
}) {
  const { cast, voices, error } = vc;
  const preview = usePreview();
  const hasLibrary = Object.keys(voices).length > 0;

  const useSuggested = () => {
    for (const c of cast ?? []) {
      const top = topOf(c, voices);
      if (top) onChange(c.speaker, top);
    }
  };

  return (
    <div className="card tight">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ fontSize: 15 }}>เสียงพากย์ของตัวละคร</h2>
        {hasLibrary && cast && (
          <button type="button" className="btn small" onClick={useSuggested}>ใช้เสียงที่แนะนำทั้งหมด</button>
        )}
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {!error && cast === null && <span className="dim">กำลังวัดเสียงตัวละครเพื่อหาเสียงที่ใกล้ที่สุดในคลัง...</span>}
      {cast && !hasLibrary && (
        <span className="dim">
          ยังไม่มีเสียงในคลัง ตอนนี้ทุกตัวละครเลียนเสียงนักแสดงต้นฉบับ · <Link href="/voices">เพิ่มเสียงเข้าคลัง</Link>
        </span>
      )}
      {cast && hasLibrary && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {cast.map((c) => {
            const selected = value[c.speaker] ?? null;
            return (
              <div key={c.speaker} className="row" style={{ gap: 10, alignItems: "center" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 2, width: 150, flex: "none" }}>
                  <span className="row" style={{ gap: 8 }}>
                    <span className="swatch" style={{ background: speakerColor(c.speaker, job.speakers) }} />
                    {speakerLabel(c.speaker, job.speaker_names)}
                  </span>
                  <span className="dim">
                    {c.gender ? `น่าจะ${GENDER_LABEL[c.gender]}` : "วัดเสียงไม่ได้"}{c.pitch_hz ? ` · ${Math.round(c.pitch_hz)} Hz` : ""}
                  </span>
                </div>
                <PreviewButton url={fileUrl.stem(job.id, c.speaker)} playing={preview.playing} onToggle={preview.toggle}
                  label="เสียงเดิม" />
                <VoiceChoice vc={vc} speaker={c.speaker} label={speakerLabel(c.speaker, job.speaker_names)} selected={selected} />
                <PreviewButton url={selected && voices[selected] ? fileUrl.voice(selected, voices[selected].updated_at) : ""}
                  playing={preview.playing} onToggle={preview.toggle} disabled={!selected || !voices[selected]} />
              </div>
            );
          })}
          <span className="dim">
            ★ คือเสียงในคลังที่ระดับเสียงและเนื้อเสียงใกล้ตัวละครที่สุด เปลี่ยนเสียงแล้วกดพากย์ ระบบจะพากย์ใหม่เฉพาะตัวละครที่เปลี่ยน
          </span>
        </div>
      )}
    </div>
  );
}
