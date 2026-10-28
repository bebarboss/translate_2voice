"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, fileUrl, type Job, type LibraryVoice, type SpeakerVoice } from "@/lib/api";
import { GENDER_LABEL, speakerColor, speakerLabel } from "@/lib/format";
import { PreviewButton, usePreview } from "./VoicePreview";

/** เลือกเสียงจากคลังให้ตัวละครแต่ละตัว (null = เลียนเสียงนักแสดงต้นฉบับ) */
export default function VoiceCast({ job, value, onChange }: {
  job: Job;
  value: Record<string, string | null>;
  onChange: (speaker: string, voiceId: string | null) => void;
}) {
  const [cast, setCast] = useState<SpeakerVoice[] | null>(null);
  const [voices, setVoices] = useState<Record<string, LibraryVoice>>({});
  const [error, setError] = useState("");
  const preview = usePreview();

  useEffect(() => {
    api.listVoices()
      .then((v) => setVoices(Object.fromEntries(v.filter((x) => x.status === "ready").map((x) => [x.id, x]))))
      .catch(() => {});
    api.jobVoices(job.id).then(setCast).catch((e) => setError(e.message));
  }, [job.id]);

  const describe = (v: LibraryVoice) => [v.name, v.gender && GENDER_LABEL[v.gender], v.tone].filter(Boolean).join(" · ");
  const hasLibrary = Object.keys(voices).length > 0;

  const useSuggested = () => {
    for (const c of cast ?? []) {
      const top = c.suggestions.find((s) => voices[s.voice_id]);
      if (top) onChange(c.speaker, top.voice_id);
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
            const ranked = c.suggestions.filter((s) => voices[s.voice_id]);
            const topId = ranked[0]?.voice_id;
            const missing = selected && !voices[selected]; // เสียงที่เลือกไว้ถูกลบจากคลังไปแล้ว
            return (
              <div key={c.speaker} className="row" style={{ gap: 10, alignItems: "center" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 2, width: 150, flex: "none" }}>
                  <span className="row" style={{ gap: 8 }}>
                    <span className="swatch" style={{ background: speakerColor(c.speaker, job.speakers) }} />
                    {speakerLabel(c.speaker)}
                  </span>
                  <span className="dim">
                    {c.gender ? `น่าจะ${GENDER_LABEL[c.gender]}` : "วัดเสียงไม่ได้"}{c.pitch_hz ? ` · ${Math.round(c.pitch_hz)} Hz` : ""}
                  </span>
                </div>
                <PreviewButton url={fileUrl.stem(job.id, c.speaker)} playing={preview.playing} onToggle={preview.toggle}
                  label="เสียงเดิม" />
                <label className="sr-only" htmlFor={`voice-${c.speaker}`}>เสียงพากย์ของ{speakerLabel(c.speaker)}</label>
                <select id={`voice-${c.speaker}`} className="select" style={{ flex: "1 1 220px", minWidth: 0 }}
                  value={missing ? "" : selected ?? ""}
                  onChange={(e) => onChange(c.speaker, e.target.value || null)}>
                  <option value="">เสียงต้นฉบับ (เลียนเสียงนักแสดง)</option>
                  {ranked.map((s) => (
                    <option key={s.voice_id} value={s.voice_id}>
                      {s.voice_id === topId ? "★ แนะนำ · " : ""}{describe(voices[s.voice_id])} · ใกล้เคียง {Math.round(s.score * 100)}%
                    </option>
                  ))}
                </select>
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
