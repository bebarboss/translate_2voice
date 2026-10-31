"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Job, type Utterance, type UtteranceEdit } from "./api";
import { speakerLabel } from "./format";

export type Draft = { target: string; speaker: string; start: number; end: number; take: number };
export type Message = { kind: "error" | "info"; text: string } | null;

export const NEW_SPEAKER = "__new__";

export const isChanged = (u: Utterance, d: Draft) =>
  d.target !== u.target || d.speaker !== u.speaker || d.start !== u.start || d.end !== u.end || d.take !== (u.take ?? 0);

/** บทพากย์ที่กำลังแก้: ร่างที่ยังไม่บันทึก แยก/รวมประโยค และเพิ่มลบตัวละคร ใช้ทั้งหน้าตรวจบทและหน้าผลลัพธ์
 *  now: เวลาที่วิดีโออยู่ตอนนี้ ใช้เป็นจุดแยกเมื่อไม่ได้วางเคอร์เซอร์ในบท */
export function useTranscript(job: Job, onChanged: () => void, now: () => number) {
  const [lines, setLines] = useState<Utterance[] | null>(null);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  // ตัวละครทั้งหมด (เพิ่มตัวละครแล้วใช้ได้ทันที ไม่ต้องรอโหลดงานใหม่)
  const [speakers, setSpeakers] = useState<string[]>(job.speakers);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState<Message>(null);
  const [saved, setSaved] = useState(0); // จำนวนครั้งที่บันทึกบทในหน้านี้ (หน้าผลลัพธ์ใช้บอกว่าต้องพากย์ใหม่)
  const cursors = useRef<Record<number, number>>({}); // ตำแหน่งเคอร์เซอร์ล่าสุดในบทของแต่ละประโยค ใช้เป็นจุดแยก

  useEffect(() => { setSpeakers(job.speakers); }, [job.speakers]);

  const applyLines = (u: Utterance[]) => {
    setLines(u);
    setDrafts(Object.fromEntries(u.map((x) => [x.id, { target: x.target, speaker: x.speaker, start: x.start, end: x.end, take: x.take ?? 0 }])));
  };

  useEffect(() => {
    api.getTranscript(job.id).then(applyLines).catch((e) => setMessage({ kind: "error", text: e.message }));
  }, [job.id]);

  const sorted = useMemo(() => (lines ?? []).slice().sort((a, b) => a.start - b.start), [lines]);

  const dirty = useMemo(() => (lines ?? []).filter((u) => {
    const d = drafts[u.id];
    return d && isChanged(u, d);
  }), [lines, drafts]);

  const draftOf = (u: Utterance): Draft =>
    drafts[u.id] ?? { target: u.target, speaker: u.speaker, start: u.start, end: u.end, take: u.take ?? 0 };

  const setDraft = (id: number, patch: Partial<Draft>) =>
    setDrafts((d) => ({ ...d, [id]: { ...d[id], ...patch } }));

  const saveLines = async () => {
    if (!dirty.length) return;
    const edits: UtteranceEdit[] = dirty.map((u) => {
      const d = drafts[u.id];
      const e: UtteranceEdit = { id: u.id };
      if (d.target !== u.target) e.target = d.target;
      if (d.speaker !== u.speaker) e.speaker = d.speaker;
      if (d.start !== u.start) e.start = d.start;
      if (d.end !== u.end) e.end = d.end;
      if (d.take !== (u.take ?? 0)) e.take = d.take;
      return e;
    });
    applyLines(await api.saveTranscript(job.id, edits));
    setSaved((n) => n + 1);
  };

  // แยก/รวมประโยค และลบตัวละคร ทำบนเซิร์ฟเวอร์ บันทึกที่แก้ค้างไว้ก่อน แล้วโหลดบทใหม่
  const restructure = async (op: () => Promise<unknown>, done: string) => {
    setBusy("edit");
    setMessage(null);
    try {
      await saveLines();
      await op();
      applyLines(await api.getTranscript(job.id));
      setSaved((n) => n + 1);
      onChanged();
      setMessage({ kind: "info", text: done });
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally { setBusy(""); }
  };

  const split = (u: Utterance) => {
    const draft = draftOf(u).target;
    // เซิร์ฟเวอร์ตัดช่องว่างหัวท้ายบท เลื่อนตำแหน่งเคอร์เซอร์ตาม
    const pos = (cursors.current[u.id] ?? 0) - (draft.length - draft.trimStart().length);
    const t = now();
    const at: { at?: number; pos?: number } = {};
    if (pos > 0 && pos < draft.trim().length) at.pos = pos;
    else if (t > u.start + 0.2 && t < u.end - 0.2) at.at = t;
    else {
      setMessage({ kind: "error", text: "วางเคอร์เซอร์ในบทตรงที่จะแยก หรือเล่นวิดีโอไปหยุดตรงที่คนที่สองเริ่มพูด แล้วกดแยกอีกครั้ง" });
      return;
    }
    delete cursors.current[u.id];
    restructure(() => api.splitLine(job.id, u.id, at), "แยกประโยคแล้ว เปลี่ยนตัวละครของท่อนหลังได้เลย");
  };

  const merge = (u: Utterance) => restructure(() => api.mergeLine(job.id, u.id), "รวมกับประโยคถัดไปแล้ว");

  const changeSpeaker = async (u: Utterance, value: string) => {
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

  const removeSpeaker = (speaker: string, into: string) =>
    restructure(async () => setSpeakers((await api.removeSpeaker(job.id, speaker, into || undefined)).speakers),
      into ? `ลบ${speakerLabel(speaker)} ย้ายประโยคไปให้${speakerLabel(into)}แล้ว` : `ลบ${speakerLabel(speaker)}แล้ว`);

  return {
    lines, sorted, drafts, draftOf, setDraft, speakers, dirty, busy, setBusy, message, setMessage, saved, cursors,
    saveLines, split, merge, changeSpeaker, removeSpeaker,
  };
}

export type Transcript = ReturnType<typeof useTranscript>;
