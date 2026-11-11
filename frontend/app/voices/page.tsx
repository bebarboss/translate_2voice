"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { api, fileUrl, uploadJob, uploadVoice, uploadVoiceImage, type Entitlements, type Gender, type LibraryVoice } from "@/lib/api";
import { GENDER_LABEL, TONES, VOICE_STAGE_LABEL } from "@/lib/format";
import CategoryPicker from "@/components/CategoryPicker";
import { PreviewButton, usePreview } from "@/components/VoicePreview";
import { ImagePickButton } from "@/components/VoiceDetail";
import WaveBars, { fmtClock } from "@/components/WaveBars";
import { UploadIcon } from "@/components/Icons";
import VoiceAvatar from "@/components/VoiceAvatar";
import { useAuth } from "@/lib/useAuth";
import { tx } from "@/lib/i18n";

const ACCEPT = ".wav,.mp3,.m4a,.aac,.flac,.ogg,.oga,.opus,.wma,.mp4,.mov,.mkv,.webm";
const GENDERS: Gender[] = ["", "male", "female"];

type AddMode = "single" | "multi";

function GenderPicker({ value, onChange, label }: { value: Gender; onChange: (g: Gender) => void; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label} style={{ alignSelf: "flex-start" }}>
      {GENDERS.map((g) => (
        <button key={g || "auto"} type="button" aria-pressed={value === g} onClick={() => onChange(g)}>
          {g ? tx(GENDER_LABEL[g]) : tx("ให้ระบบเดา")}
        </button>
      ))}
    </div>
  );
}

/** เพิ่มเสียงเข้าคลังจากไฟล์หรือลิงก์ */
function UploadCard({ onUploaded, known }: { onUploaded: () => void; known: string[] }) {
  const router = useRouter();
  const [mode, setMode] = useState<AddMode>("single");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [count, setCount] = useState("");
  const [drag, setDrag] = useState(false);
  const [name, setName] = useState("");
  const [gender, setGender] = useState<Gender>("");
  const [tone, setTone] = useState("");
  const [description, setDescription] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const [image, setImage] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState("");
  const [rights, setRights] = useState(false);
  const [denoise, setDenoise] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const abortRef = useRef<(() => void) | null>(null);
  const multi = mode === "multi";
  const busy = progress !== null;

  const pickFile = (f: File | undefined | null) => {
    setError("");
    if (!f) return;
    const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPT.split(",").includes(ext)) {
      setError(tx("รองรับไฟล์เสียง WAV, MP3, M4A, FLAC, OGG, OGA หรือวิดีโอ MP4, MOV, MKV, WEBM"));
      return;
    }
    setFile(f);
    setUrl("");
    if (!name) setName(f.name.slice(0, f.name.lastIndexOf(".")).slice(0, 80));
  };

  const hasSource = !!file || !!url.trim();
  const ready = hasSource && rights && !busy && (multi || !!name.trim());

  useEffect(() => {
    if (!image) { setImagePreview(""); return; }
    const objectUrl = URL.createObjectURL(image);
    setImagePreview(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [image]);

  const submitMulti = async () => {
    const n = parseInt(count, 10);
    const opts = { sourceLang: "", targetLang: "th" as const, numSpeakers: n >= 2 && n <= 20 ? n : null,
      review: true, burnSubs: false, genre: "", glossary: "", library: true };
    let id: string;
    if (file) {
      const up = uploadJob(file, opts, setProgress);
      abortRef.current = up.abort;
      id = (await up.promise).id;
    } else {
      id = (await api.createFromUrl(url.trim(), opts)).id;
    }
    router.push(`/jobs/${id}`);
  };

  const submitSingle = async () => {
    const meta = { name: name.trim(), gender, tone: tone.trim(), description: description.trim(), categories, denoise };
    let v: LibraryVoice;
    if (file) {
      const up = uploadVoice(file, meta, setProgress);
      abortRef.current = up.abort;
      v = await up.promise;
    } else {
      v = await api.createVoiceFromUrl(url.trim(), meta);
    }
    let imageError = "";
    if (image) {
      await uploadVoiceImage(v.id, image).catch((e) => { imageError = tx("เพิ่มเสียงแล้ว แต่ตั้งรูปไม่สำเร็จ: {0}", { 0: (e as Error).message }); });
    }
    setFile(null);
    setUrl("");
    setName("");
    setTone("");
    setGender("");
    setDescription("");
    setCategories([]);
    setImage(null);
    setError(imageError);
    onUploaded();
  };

  const submit = async () => {
    if (!ready) return;
    setError("");
    setProgress(0);
    try {
      await (multi ? submitMulti() : submitSingle());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setProgress(null);
      abortRef.current = null;
    }
  };

  return (
    <section className="card" aria-labelledby="add-voice">
      <div className="row" style={{ justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h2 id="add-voice" style={{ margin: 0 }}>{tx("เพิ่มเสียงเข้าคลัง")}</h2>
        <div className="seg" role="group" aria-label={tx("ชนิดคลิป")}>
          <button type="button" aria-pressed={!multi} onClick={() => setMode("single")} disabled={busy}>{tx("เสียงคนเดียว")}</button>
          <button type="button" aria-pressed={multi} onClick={() => setMode("multi")} disabled={busy}>{tx("คลิปหลายคนพูด")}</button>
        </div>
      </div>
      <div className="grid-2">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <label className={`dropzone${drag ? " drag" : ""}`} style={{ minHeight: 0, padding: 24, flex: 1 }}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); pickFile(e.dataTransfer.files[0]); }}>
            <span className="icon"><UploadIcon size={26} /></span>
            {file ? (
              <>
                <span style={{ fontSize: 16, fontWeight: 500, wordBreak: "break-all" }}>{file.name}</span>
                <span className="muted">{(file.size / 1024 / 1024).toFixed(1)}  {tx("MB · คลิกเพื่อเปลี่ยนไฟล์")}</span>
              </>
            ) : (
              <>
                <span style={{ fontSize: 17, fontWeight: 500 }}>{tx("ลากคลิปเสียงภาษาไทยมาวาง")}</span>
                <span className="muted">{tx("หรือ")} <span className="u">{tx("เลือกไฟล์")}</span></span>
                <span className="dim">
                  {multi
                    ? tx("คลิปที่มีหลายคนพูด เช่น ละคร รายการ · ระบบแยกเสียงของแต่ละคนให้")
                    : tx("เสียงคนเดียวพูด 10 วินาทีขึ้นไป · ระบบประเมินทั้งไฟล์ (ไม่เกิน 60 นาที) ยิ่งยาวยิ่งได้ท่อนที่ดี")}
                </span>
              </>
            )}
            <input type="file" accept={ACCEPT} aria-label={tx("เลือกไฟล์เสียง")} disabled={busy}
              onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
          <input className="input" type="url" placeholder={tx("หรือวางลิงก์ YouTube, TikTok, Facebook ฯลฯ")} aria-label={tx("ลิงก์คลิป")}
            value={url} disabled={busy} onChange={(e) => { setUrl(e.target.value); if (e.target.value) setFile(null); }} />
        </div>

        {multi ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <p className="muted" style={{ margin: 0 }}>
              {tx("ระบบแยกเพลงออก แยกเสียงของแต่ละคน และถอดเสียงให้ (ไม่แปล ไม่พากย์) แล้วพาไปหน้าที่ให้ฟังเสียงแต่ละคน ตั้งชื่อว่าเป็นเสียงของใคร และเลือกบันทึกลงคลังทีละคน")}
            </p>
            <div className="field">
              <label htmlFor="v-count">{tx("จำนวนคนในคลิป (ถ้ารู้ ช่วยให้แยกแม่นขึ้น)")}</label>
              <input id="v-count" className="input" type="number" min={2} max={20} placeholder={tx("ไม่ระบุ = ให้ระบบนับเอง")}
                value={count} onChange={(e) => setCount(e.target.value)} disabled={busy} />
            </div>
            <span className="dim">{tx("ใช้เครดิตตามความยาวคลิปเหมือนงานพากย์")}</span>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div className="field">
              <label htmlFor="v-name">{tx("ชื่อเสียง")}</label>
              <input id="v-name" className="input" maxLength={80} placeholder={tx("เช่น พี่ต้น ผู้ชายวัยทำงาน")}
                value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="field">
              <span className="label">{tx("เพศ")}</span>
              <GenderPicker value={gender} onChange={setGender} label={tx("เพศของเสียง")} />
            </div>
            <div className="field">
              <label htmlFor="v-tone">{tx("โทนเสียง")}</label>
              <input id="v-tone" className="input" list="tones" maxLength={80} placeholder={tx("เช่น ทุ้มลึก นุ่มนวล สดใส")}
                value={tone} onChange={(e) => setTone(e.target.value)} />
              <datalist id="tones">{TONES.map((t) => <option key={t} value={tx(t)} />)}</datalist>
            </div>
            <div className="field">
              <span className="label">{tx("รูป (ไม่ใส่ก็ได้)")}</span>
              <div className="row" style={{ gap: 10 }}>
                <VoiceAvatar name={name} url={imagePreview} />
                <ImagePickButton label={image ? tx("เปลี่ยนรูป") : tx("เลือกรูป")} onPick={setImage} disabled={busy} />
                {image && <button type="button" className="btn small" onClick={() => setImage(null)} disabled={busy}>{tx("เอารูปออก")}</button>}
              </div>
            </div>
          </div>
        )}
      </div>

      {!multi && (
        <>
          <div className="field">
            <span className="label" id="v-cat">{tx("หมวดหมู่ (เลือกได้หลายหมวด)")}</span>
            <CategoryPicker id="v-cat" value={categories} onChange={setCategories} known={known} />
          </div>
          <div className="field">
            <label htmlFor="v-desc">{tx("รายละเอียด (ไม่ใส่ก็ได้)")}</label>
            <textarea id="v-desc" className="textarea" rows={3} maxLength={1000}
              placeholder={tx("เช่น คนพากย์ บทที่เหมาะ อายุตัวละคร สไตล์การพูด")}
              value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <label className="check" style={{ justifyContent: "flex-start" }}>
            <input type="checkbox" checked={denoise} onChange={(e) => setDenoise(e.target.checked)} />
            <span>{tx("ลดเสียงรบกวนเพิ่ม (ช่วยกับเสียงซ่าหรือลมจากการอัดเอง ระบบแยกเพลงออกให้อยู่แล้ว)")}</span>
          </label>
        </>
      )}

      <label className="check" style={{ justifyContent: "flex-start" }}>
        <input type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)} />
        <span>
          {multi ? tx("ฉันเป็นเจ้าของเสียงในคลิปนี้ หรือได้รับอนุญาตจากเจ้าของเสียงให้นำไปใช้พากย์แล้ว")
            : tx("ฉันเป็นเจ้าของเสียงนี้ หรือได้รับอนุญาตจากเจ้าของเสียงให้นำไปใช้พากย์แล้ว")}
        </span>
      </label>
      {error && <div className="alert error" role="alert">{error}</div>}
      <div className="row" style={{ justifyContent: "space-between" }}>
        {busy && file ? (
          <div style={{ flex: "1 1 260px", display: "flex", alignItems: "center", gap: 12 }}>
            <div className="progress" style={{ flex: 1 }}><div style={{ width: `${(progress ?? 0) * 100}%` }} /></div>
            <span className="mono">{Math.round((progress ?? 0) * 100)}%</span>
            <button type="button" className="btn small" onClick={() => abortRef.current?.()}>{tx("ยกเลิก")}</button>
          </div>
        ) : (
          <span className="dim">
            {multi ? tx("แยกเสียงเสร็จแล้วจะพาไปหน้าเลือกบันทึกเสียงของแต่ละคน")
              : tx("ระบบจะแยกเสียงรบกวนออก ตัดท่อนที่ชัดที่สุด 3–10 วินาที และถอดข้อความให้อัตโนมัติ")}
          </span>
        )}
        <button type="button" className="btn primary" onClick={submit} disabled={!ready}>
          {busy ? (file ? tx("กำลังอัปโหลด...") : tx("กำลังส่ง...")) : multi ? tx("แยกเสียง") : tx("เพิ่มเสียง")}
        </button>
      </div>
    </section>
  );
}

/** แถวแนวนอนแนว Pixabay — รูป · ชื่อ · waveform · ความยาว · หมวด */
function VoiceRow({ v, preview }: { v: LibraryVoice; preview: ReturnType<typeof usePreview> }) {
  const audioUrl = fileUrl.voice(v.id, v.updated_at);
  const on = preview.playing === audioUrl;
  const stop = (e: MouseEvent) => { e.preventDefault(); e.stopPropagation(); };
  const by = v.actor || (v.mine ? tx("ของฉัน") : "");

  return (
    <Link href={`/voices/${v.id}`} className="voice-row">
      <VoiceAvatar name={v.name} url={v.image ? fileUrl.voiceImage(v.id, v.updated_at) : ""} size={48} />
      <div className="voice-row-id">
        <span className="voice-row-name">{v.name}</span>
        {by && <span className="voice-row-by">{by}</span>}
        {v.status === "processing" && <span className="badge running">{VOICE_STAGE_LABEL[v.stage] ?? v.stage}...</span>}
        {v.status === "failed" && <span className="badge failed">{tx("เตรียมเสียงไม่สำเร็จ")}</span>}
        {v.review === "pending" && <span className="badge awaiting_review">{tx("รอผู้ดูแลตรวจ")}</span>}
      </div>
      <div className="voice-row-wave" onClick={stop}>
        {v.status === "ready" ? (
          <WaveBars
            seed={v.id}
            bars={56}
            active={on}
            progress={on ? preview.progress : 0}
            onClick={() => preview.toggle(audioUrl)}
          />
        ) : (
          <span className="dim" style={{ fontSize: 13 }}>—</span>
        )}
      </div>
      <span className="voice-row-dur mono">{v.status === "ready" ? fmtClock(v.duration) : "–:––"}</span>
      <div className="voice-row-tags">
        {(v.categories ?? []).slice(0, 2).map((c) => <span key={c}>{c}</span>)}
        {v.gender && <span>{tx(GENDER_LABEL[v.gender])}</span>}
        {v.tone && <span>{v.tone}</span>}
      </div>
      <div className="voice-row-actions" onClick={stop}>
        {v.status === "ready" && (
          <PreviewButton url={audioUrl} playing={preview.playing} onToggle={preview.toggle} label="" className="icon-btn wave-play" />
        )}
      </div>
    </Link>
  );
}

export default function VoicesPage() {
  const [voices, setVoices] = useState<LibraryVoice[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [ent, setEnt] = useState<Entitlements | null>(null);
  const preview = usePreview();
  const { config, user, loaded } = useAuth();
  const canUpload = loaded && (!config?.auth || !!user?.admin);
  const trialVoicesOnly = !!config?.billing && !user?.admin && ent?.voices === "standard";
  const known = useMemo(() => {
    const count = new Map<string, number>();
    voices?.forEach((v) => (v.categories ?? []).forEach((c) => count.set(c, (count.get(c) ?? 0) + 1)));
    return [...count.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c);
  }, [voices]);
  const shown = voices?.filter((v) => !filter || (v.categories ?? []).includes(filter)) ?? null;
  useEffect(() => { if (filter && voices && !known.includes(filter)) setFilter(""); }, [filter, known, voices]);

  const refresh = useCallback(() => {
    api.listVoices().then((v) => { setVoices(v); setError(""); }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (!config?.billing || !user || user.admin) { setEnt(null); return; }
    api.wallet().then((w) => setEnt(w.entitlements ?? null)).catch(() => setEnt(null));
  }, [config?.billing, user]);

  const processing = voices?.some((v) => v.status === "processing" || v.moods.some((m) => m.status === "processing")) ?? false;
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [processing, refresh]);

  return (
    <main className="page" style={{ maxWidth: 1080 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h1 style={{ margin: 0, fontSize: 30, fontWeight: 700 }}>{tx("คลังเสียง")}</h1>
        <p className="muted" style={{ margin: 0 }}>
          {tx("เก็บเสียงพากย์ภาษาไทยไว้ใช้ซ้ำ แล้วเลือกให้ตัวละครแต่ละตัวในหน้าตรวจบท แทนการเลียนเสียงนักแสดงต้นฉบับ")}
        </p>
      </div>

      {trialVoicesOnly && (
        <div className="alert info" role="status">
          {tx("บัญชีทดลองใช้ได้เฉพาะเสียง Standard (ที่แอดมินเพิ่ม) เสียงนักพากย์ต้องอัปเกรดแพ็กเกจ")}
          {" "}
          <Link href="/promotions">{tx("ดูโปรโมชัน")}</Link>
        </div>
      )}

      {canUpload && <UploadCard onUploaded={refresh} known={known} />}

      {error && <div className="alert error" role="alert">{error}</div>}
      <section aria-label={tx("เสียงในคลัง")} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 500 }}>
          {tx("เสียงในคลัง")} {shown?.length ? `(${shown.length}${filter ? tx(" จาก {0}", { 0: voices?.length }) : ""})` : ""}
        </h2>
        {known.length > 0 && (
          <div className="chips" role="group" aria-label={tx("กรองตามหมวดหมู่")}>
            <button type="button" className="chip filter" aria-pressed={!filter} onClick={() => setFilter("")}>{tx("ทั้งหมด")}</button>
            {known.map((c) => (
              <button key={c} type="button" className="chip filter" aria-pressed={filter === c} onClick={() => setFilter(c)}>{c}</button>
            ))}
          </div>
        )}
        {shown === null ? <div className="empty">{tx("กำลังโหลด...")}</div>
          : voices?.length === 0 ? <div className="empty">{tx("ยังไม่มีเสียงในคลัง")}</div>
          : (
            <div className="voice-list">
              {shown.map((v) => <VoiceRow key={v.id} v={v} preview={preview} />)}
            </div>
          )}
      </section>
    </main>
  );
}
