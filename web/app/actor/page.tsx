"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import Recorder from "@/components/Recorder";
import { PreviewButton, usePreview } from "@/components/VoicePreview";
import { api, fileUrl, type ActorConsentDoc, type ActorMe, type ActorPayment, type Gender, type LibraryVoice, type Mood,
  type UsageRow } from "@/lib/api";
import { fmtBaht, GENDER_LABEL, MOOD_LABEL, MOODS, VOICE_STAGE_LABEL } from "@/lib/format";
import { useAuth } from "@/lib/useAuth";

import { locale, tx } from "@/lib/i18n";
/** บทอ่านเสียงหลัก: ครบเสียงสระ วรรณยุกต์ และพยัญชนะควบ อ่านช้า ๆ เป็นธรรมชาติราว 30–40 วินาที */
const SCRIPT = [
  "สวัสดีครับ วันนี้อากาศดีมาก เราออกไปเดินเล่นที่สวนสาธารณะกันไหม",
  "เมื่อวานฉันไปตลาดน้ำ ซื้อขนมครก ข้าวเหนียวมะม่วง และกาแฟเย็นมาฝากทุกคน",
  "ถ้าเธอไม่รีบ ก็นั่งพักก่อนสักครู่ เดี๋ยวฉันจะเล่าเรื่องสนุก ๆ ให้ฟัง",
  "รถไฟขบวนสุดท้ายออกจากสถานีกรุงเทพตอนสี่ทุ่มตรง อย่ามาสายล่ะ",
  "ความพยายามอยู่ที่ไหน ความสำเร็จอยู่ที่นั่น ขอให้เชื่อมั่นในตัวเอง",
  "เสียงฟ้าร้องครืนครางดังมาจากทิศเหนือ ฝนคงจะตกหนักในอีกไม่ช้า",
  "คุณครูบอกว่าการบ้านต้องส่งภายในวันศุกร์ ห้ามลืมเด็ดขาด",
  "ขอบคุณที่อยู่ข้างกันเสมอ ไม่ว่าจะสุขหรือทุกข์ เราจะผ่านไปด้วยกัน",
];
/** ชุดบทของแต่ละอารมณ์ อ่านด้วยอารมณ์นั้นจริง ๆ ราว 25–40 วินาทีต่อหมวด */
const MOOD_SCRIPT: Record<Mood, string[]> = {
  angry: [
    "พอได้แล้ว! ฉันบอกกี่ครั้งแล้วว่าอย่าแตะของของฉัน ออกไปเดี๋ยวนี้!",
    "คุณคิดว่าฉันจะทนอีกได้เหรอ นี่มันเกินพอแล้ว!",
    "อย่ามาพูดกับฉันแบบนั้นอีก ฉันไม่ได้เป็นคนให้ใครเหยียบหัว!",
    "ทำไมไม่ยอมฟังสักที! ฉันพูดชัด ๆ แล้วว่าห้ามทำแบบนี้!",
    "ฉันโกรธมาก อย่าเข้ามายุ่งเดี๋ยวนี้ ปล่อยฉันไว้คนเดียวก่อน!",
    "ถ้ายังไม่เลิก ฉันจะไม่คุยด้วยอีกเลย จำไว้ให้ดี!",
  ],
  sad: [
    "ฉันรอเธอมาทั้งคืน แต่เธอก็ไม่มา... บางทีเราอาจจะไม่ได้เจอกันอีกแล้ว",
    "ทำไมทุกอย่างต้องเป็นแบบนี้ ฉันเหนื่อยจริง ๆ แล้ว",
    "ตอนนี้ฉันรู้สึกว่างเปล่า เหมือนไม่มีอะไรเหลืออยู่เลย",
    "ขอโทษนะ... ฉันคงทำอะไรผิดไปมากมายโดยไม่รู้ตัว",
    "น้ำตาไหลเองไม่ทันตั้งตัว ฉันไม่อยากเสียเธอไปเลย",
    "ถ้าเวลาย้อนกลับได้ ฉันอยากขอเริ่มต้นใหม่อีกครั้ง",
  ],
  happy: [
    "จริงเหรอ! เราสอบผ่านแล้ว! ดีใจที่สุดเลย ไปฉลองกันเถอะ!",
    "วันนี้เป็นวันที่ดีที่สุดในชีวิตฉันเลย น่าตื่นเต้นมาก!",
    "เย้! สำเร็จแล้ว! ฉันแทบกระโดดโลดเต้นอยู่เลย!",
    "ขอบคุณนะ ที่อยู่ด้วยกันจนถึงตอนนี้ ฉันมีความสุขมากเลย",
    "มาเร็วเข้า! ข่าวดีมีมาอีกแล้ว ห้ามพลาดเด็ดขาด!",
    "ฮ่า ๆ ๆ สนุกจัง วันแบบนี้แล้วยังไม่ยิ้มได้อีกเหรอ!",
  ],
  whisper: [
    "ชู่ว์... เบา ๆ หน่อย เดี๋ยวคนอื่นได้ยิน เรามีความลับต้องคุยกัน",
    "ใกล้ ๆ หน่อย... ฉันจะกระซิบให้ฟัง อย่าเพิ่งบอกใครนะ",
    "เงียบไว้ก่อน เดี๋ยวเขาหันมามอง เราค่อยคุยต่อทีหลัง",
    "ฟังนะ... ประตูห้องข้าง ๆ ยังไม่ได้ปิดสนิท",
    "เบาที่สุดเลย แผนนี้ห้ามมีใครรู้ นอกจากเราสองคน",
    "ค่อย ๆ พูดทีละคำ... อย่าให้เสียงดังเกินลมหายใจ",
  ],
  scared: [
    "อะไรน่ะ! มีใครอยู่ตรงนั้นหรือเปล่า... อย่าเข้ามานะ ฉันกลัว!",
    "เสียงอะไรน่ะ จากห้องมืด ๆ นั่น... ฉันได้ยินชัด ๆ เลย",
    "อย่าทิ้งฉันไว้คนเดียว ฉันไม่กล้าเดินต่อแล้ว",
    "หัวใจเต้นแรงมาก... มีอะไรกำลังตามเราอยู่ใช่ไหม",
    "ไฟดับอีกแล้ว! ช่วยเปิดไฟที ฉันมองอะไรไม่เห็นเลย!",
    "หยุด... ได้ยินไหม ฝีเท้าใกล้เข้ามาทุกทีแล้ว",
  ],
};

const STATUS_TEXT = { pending: "รอผู้ดูแลอนุมัติใบสมัคร", rejected: "ใบสมัครไม่ผ่าน", withdrawn: "ถอนความยินยอมแล้ว" } as const;
const fmtDate = (unix: number) =>
  new Date(unix * 1000).toLocaleString(locale(), { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const fmtMin = (sec: number) => tx("{0} นาที", { 0: (sec / 60).toLocaleString(locale(), { maximumFractionDigits: 1 }) });
const fmtMonth = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString(locale(), { month: "long", year: "numeric" });

/** หนังสือยินยอม PDPA และสิทธิ์ใช้เสียง: อ่านในกล่อง (หรือเปิดเต็มหน้า) แล้วติ๊กให้ครบทุกข้อ */
function ConsentBox({ onAccept, busy, label, disabled, hint }: {
  onAccept: (version: string, items: string[]) => void; busy: boolean; label: string; disabled?: boolean; hint?: string;
}) {
  const [doc, setDoc] = useState<ActorConsentDoc | null>(null);
  const [error, setError] = useState("");
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  useEffect(() => { api.actorConsent().then(setDoc).catch((e) => setError(e.message)); }, []);
  if (error) return <div className="alert error" role="alert">{error}</div>;
  if (!doc) return <div className="empty">{tx("กำลังโหลดหนังสือยินยอม...")}</div>;
  const all = doc.items.every((i) => checked[i.id]);
  return (
    <div className="field">
      <div className="row" style={{ justifyContent: "space-between", gap: 10 }}>
        <span className="label">{tx("หนังสือให้ความยินยอมและอนุญาตให้ใช้เสียง (ฉบับ")} {doc.version})</span>
        <a href="/actor-consent" target="_blank" rel="noopener" className="dim" style={{ fontSize: 13 }}>{tx("เปิดอ่านเต็มหน้า")}</a>
      </div>
      <div className="consent-box" tabIndex={0} aria-label={tx("ข้อความหนังสือยินยอม")}>{doc.text}</div>
      <div className="consent-checks">
        {doc.items.map((i) => (
          <label key={i.id} className="agree">
            <input type="checkbox" checked={!!checked[i.id]} onChange={(e) => setChecked({ ...checked, [i.id]: e.target.checked })} />
            <span>{i.text}</span>
          </label>
        ))}
      </div>
      <span className="dim" style={{ fontSize: 13 }}>
        
        {tx("ถอนความยินยอมได้ตลอดเวลาที่หน้านี้ ระบบจะลบเสียงทั้งหมดของคุณออกจากคลังทันที")}
      </span>
      <button type="button" className="btn primary" style={{ alignSelf: "flex-start" }}
        disabled={busy || disabled || !all} onClick={() => onAccept(doc.version, doc.items.map((i) => i.id))}>{label}</button>
      {hint && <span className="dim">{hint}</span>}
    </div>
  );
}

function ApplyForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [gender, setGender] = useState<Gender>("");
  const [bio, setBio] = useState("");
  const [contact, setContact] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (version: string, items: string[]) => {
    setBusy(true);
    setError("");
    try {
      await api.actorApply({ stage_name: name.trim(), gender, bio, contact, consent_version: version, consent_items: items });
      onDone();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <section className="card" aria-labelledby="apply-title">
      <h2 id="apply-title">{tx("สมัครเป็นนักพากย์")}</h2>
      <p className="muted" style={{ margin: 0 }}>
        
        {tx("อัดเสียงของคุณเข้าคลังเสียง ให้ผู้ใช้ทุกคนเลือกใช้พากย์ได้ และรับค่าตอบแทนตามเวลาที่เสียงของคุณถูกใช้ ผู้ดูแลจะตรวจใบสมัครก่อน")}
      </p>
      <div className="field">
        <label htmlFor="stage">{tx("ชื่อในวงการ (แสดงคู่กับเสียง)")}</label>
        <input id="stage" className="input" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <span className="label">{tx("เพศของเสียง")}</span>
        <div className="seg" role="group" aria-label={tx("เพศของเสียง")} style={{ alignSelf: "flex-start" }}>
          {(["male", "female", ""] as Gender[]).map((g) => (
            <button key={g || "none"} type="button" aria-pressed={gender === g} onClick={() => setGender(g)}>{tx(GENDER_LABEL[g])}</button>
          ))}
        </div>
      </div>
      <div className="field">
        <label htmlFor="bio">{tx("ประสบการณ์ / สไตล์เสียง")}</label>
        <textarea id="bio" className="input" rows={3} maxLength={1000} value={bio} onChange={(e) => setBio(e.target.value)}
          placeholder={tx("เช่น พากย์การ์ตูนมา 5 ปี เสียงทุ้ม เหมาะกับบทพระเอก")} />
      </div>
      <div className="field">
        <label htmlFor="contact">{tx("ช่องทางติดต่อ / รับเงิน")}</label>
        <input id="contact" className="input" maxLength={200} value={contact} onChange={(e) => setContact(e.target.value)}
          placeholder={tx("เช่น LINE ID หรือเบอร์โทร")} />
      </div>
      <ConsentBox busy={busy} label={busy ? tx("กำลังส่ง...") : tx("ยอมรับและส่งใบสมัคร")} onAccept={submit}
        disabled={!name.trim()} hint={name.trim() ? undefined : tx("กรอกชื่อในวงการก่อนส่งใบสมัคร")} />
      {error && <div className="alert error" role="alert">{error}</div>}
    </section>
  );
}

const REVIEW_BADGE = {
  draft: <span className="badge queued">{tx("บันทึกแล้ว ยังไม่ส่งตรวจ")}</span>,
  pending: <span className="badge awaiting_review">{tx("รอผู้ดูแลตรวจ")}</span>,
  approved: <span className="badge done">{tx("อยู่ในคลังแล้ว")}</span>,
  rejected: <span className="badge failed">{tx("ให้อัดใหม่")}</span>,
};

/** ครบเสียงหลัก + อารมณ์ทุกหมวด และเตรียมเสร็จแล้ว */
function packageComplete(v: LibraryVoice): boolean {
  if (v.status !== "ready") return false;
  return MOODS.every((m) => v.moods.some((x) => x.mood === m && x.status === "ready"));
}

function hasDraft(v: LibraryVoice): boolean {
  return v.review === "draft" || v.moods.some((x) => x.review === "draft");
}

function hasRejected(v: LibraryVoice): boolean {
  return v.review === "rejected" || v.moods.some((x) => x.review === "rejected");
}

/** แสดงปุ่มส่งตรวจเมื่อยังมีงานค้าง (ร่าง / ตีกลับ / ยังอัดไม่ครบ) */
function showSubmit(v: LibraryVoice): boolean {
  if (v.review === "pending") return false;
  if (hasDraft(v) || hasRejected(v)) return true;
  return !packageComplete(v) && (v.status === "ready" || v.moods.length > 0);
}

function canSubmit(v: LibraryVoice): boolean {
  return packageComplete(v) && hasDraft(v) && !hasRejected(v);
}

type MoodSlot = Mood | "normal";

function moodSlotState(v: LibraryVoice, slot: MoodSlot): {
  mark: string; hint: string; badge: "empty" | "processing" | "failed" | "draft" | "pending" | "rejected" | "ready"; suggest: boolean;
} {
  if (slot === "normal") {
    if (v.status === "processing") return { mark: "…", hint: tx("กำลังเตรียม"), badge: "processing", suggest: false };
    if (v.status === "failed") return { mark: "!", hint: tx("เตรียมไม่สำเร็จ กดเพื่ออัดใหม่"), badge: "failed", suggest: false };
    if (v.status === "ready" && v.review === "draft") return { mark: "○", hint: tx("บันทึกแล้ว ยังไม่ส่งตรวจ"), badge: "draft", suggest: false };
    if (v.review === "pending") return { mark: "⏳", hint: tx("รอผู้ดูแลตรวจ"), badge: "pending", suggest: false };
    if (v.review === "rejected") return { mark: "✕", hint: tx("ไม่ผ่านการตรวจ กดเพื่ออัดใหม่"), badge: "rejected", suggest: false };
    if (v.status === "ready" && v.review === "approved") return { mark: "✓", hint: tx("ผ่านแล้ว กดเพื่ออัดใหม่"), badge: "ready", suggest: false };
    return { mark: "+", hint: tx("กดเพื่ออัด"), badge: "empty", suggest: false };
  }
  const got = v.moods.find((x) => x.mood === slot);
  if (!got) return { mark: "+", hint: tx("ต้องอัด"), badge: "empty", suggest: true };
  if (got.status === "processing") return { mark: "…", hint: tx("กำลังเตรียม"), badge: "processing", suggest: false };
  if (got.status === "failed") return { mark: "!", hint: tx("เตรียมไม่สำเร็จ กดเพื่ออัดใหม่"), badge: "failed", suggest: false };
  if (got.review === "draft") return { mark: "○", hint: tx("บันทึกแล้ว ยังไม่ส่งตรวจ"), badge: "draft", suggest: false };
  if (got.review === "pending") return { mark: "⏳", hint: tx("รอผู้ดูแลตรวจ"), badge: "pending", suggest: false };
  if (got.review === "rejected") return { mark: "✕", hint: tx("ไม่ผ่านการตรวจ กดเพื่ออัดใหม่"), badge: "rejected", suggest: false };
  return { mark: "✓", hint: tx("ผ่านแล้ว กดเพื่ออัดใหม่"), badge: "ready", suggest: false };
}

/** หมวดอารมณ์ของเสียงหนึ่ง: อัดและบันทึกทีละหมวด กดการ์ดเพื่อเปิดห้องอัดของหมวดนั้น */
function MoodCategories({ v, usage, picked, pickedNormal, onPick, onPickNormal, preview }: {
  v: LibraryVoice; usage: Record<string, number>; picked?: Mood; pickedNormal: boolean;
  onPick: (m: Mood) => void; onPickNormal: () => void;
  preview: { playing: string | null; toggle: (url: string) => void };
}) {
  const recorded = v.moods.filter((x) => x.status === "ready").length;
  const missing = MOODS.filter((m) => !v.moods.some((x) => x.mood === m && x.status === "ready"));
  const slots: MoodSlot[] = ["normal", ...MOODS];
  return (
    <div className="mood-cats">
      <div className="row" style={{ justifyContent: "space-between", gap: 8 }}>
        <span className="label" style={{ margin: 0 }}>{tx("หมวดอารมณ์ — ต้องอัดครบทุกหมวดก่อนส่งตรวจ")}</span>
        <span className="dim">{tx("เสียงอารมณ์ {0}/{1}", { 0: recorded, 1: MOODS.length })}</span>
      </div>
      <div className="mood-grid" role="list">
        {slots.map((slot) => {
          const { mark, hint, badge, suggest } = moodSlotState(v, slot);
          const label = slot === "normal" ? tx("ปกติ") : tx(MOOD_LABEL[slot]);
          const active = slot === "normal" ? pickedNormal : picked === slot;
          const lines = usage[slot === "normal" ? "" : slot] ?? 0;
          const canPreview = (badge === "ready" || badge === "draft" || badge === "pending") && (slot === "normal"
            ? v.status === "ready"
            : !!v.moods.find((x) => x.mood === slot && x.status === "ready"));
          const url = slot === "normal"
            ? fileUrl.voice(v.id, v.updated_at)
            : fileUrl.voiceMood(v.id, slot, v.updated_at);
          return (
            <div key={slot} className={`mood-card badge-${badge}${suggest ? " suggest" : ""}${active ? " active" : ""}`} role="listitem">
              <button type="button" className="mood-card-main" aria-pressed={active}
                title={hint} aria-label={`${label} · ${hint}`}
                onClick={() => (slot === "normal" ? onPickNormal() : onPick(slot))}>
                <span className="mood-card-mark" aria-hidden>{mark}</span>
                <span className="mood-card-label">{label}</span>
                <span className="mood-card-hint">{hint}</span>
                {lines > 0 && <span className="mood-card-use">{lines} {tx("ประโยค")}</span>}
              </button>
              {canPreview && (
                <PreviewButton url={url} playing={preview.playing} onToggle={preview.toggle} />
              )}
            </div>
          );
        })}
      </div>
      {missing.length > 0 && (
        <span className="dim">{tx("ยังขาด {0} — ต้องอัดครบทุกหมวดถึงจะส่งให้แอดมินตรวจได้",
          { 0: missing.map((m) => tx(MOOD_LABEL[m])).join(" · ") })}</span>
      )}
      {v.moods.filter((x) => x.review === "rejected" && x.review_note).map((x) => (
        <div key={x.mood} className="alert error">{tx("ผู้ดูแล ({0}):", { 0: tx(MOOD_LABEL[x.mood]) })} {x.review_note}</div>
      ))}
    </div>
  );
}

function Studio({ me, reload }: { me: ActorMe; reload: () => void }) {
  const preview = usePreview();
  const [target, setTarget] = useState<{ voice?: LibraryVoice; mood?: Mood }>({});
  const [blob, setBlob] = useState<{ data: Blob; name: string } | null>(null);
  const [denoise, setDenoise] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [key, setKey] = useState(0); // เปลี่ยนแล้วล้างเครื่องอัด
  const [freshVoice, setFreshVoice] = useState(false); // true = ตั้งใจอัดเสียงคนละตัวใหม่ ไม่ผูกเสียงเดิม

  // มีเสียงแล้วผูกห้องอัดกับเสียงนั้นอัตโนมัติ เพื่อให้เลือกหมวดอารมณ์ได้ทันที
  const liveVoice = (() => {
    if (freshVoice && !target.voice) return undefined;
    if (target.voice) return me.voices.find((x) => x.id === target.voice!.id) ?? target.voice;
    return me.voices[0];
  })();

  // เสียงที่กำลังเตรียมอยู่ โหลดสถานะใหม่ทุก 4 วินาที
  const preparing = me.voices.some((v) => [v, ...v.moods].some((x) => x.status === "processing"));
  useEffect(() => {
    if (!preparing) return;
    const t = setInterval(reload, 4000);
    return () => clearInterval(t);
  }, [preparing, reload]);

  const pickSlot = (voice: LibraryVoice, mood?: Mood) => {
    setFreshVoice(false);
    setTarget({ voice, mood });
    setBlob(null);
    setKey((k) => k + 1);
    setMessage(null);
    requestAnimationFrame(() => document.getElementById("studio-title")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  const send = async () => {
    if (!blob) return;
    setBusy(true);
    setMessage(null);
    const mood = target.mood;
    const voiceId = liveVoice?.id;
    try {
      const out = await api.actorRecord(blob.data, blob.name, { voiceId, mood, denoise });
      setBlob(null);
      setKey((k) => k + 1);
      setFreshVoice(false);
      // ผูกห้องอัดกับเสียงที่เพิ่งบันทึก เปิดให้เลือกหมวดอารมณ์ต่อได้ทันที
      setTarget({ voice: out, mood });
      setMessage({ kind: "info", text: mood
        ? tx("บันทึกหมวดอารมณ์แล้ว เลือกหมวดถัดไปด้านบนแล้วอัดต่อ หรืออัดให้ครบแล้วกดส่งตรวจ")
        : tx("บันทึกเสียงหลักแล้ว เลือกหมวดอารมณ์ด้านบนแล้วอัดทีละหมวด") });
      reload();
    } catch (e) { setMessage({ kind: "error", text: (e as Error).message }); } finally { setBusy(false); }
  };
  const submitReview = async (v: LibraryVoice) => {
    if (!canSubmit(v)) {
      setMessage({ kind: "error", text: hasRejected(v)
        ? tx("มีหมวดที่ถูกตีกลับ ให้อัดใหม่ก่อนส่งตรวจ")
        : tx("ต้องอัดเสียงอารมณ์ให้ครบทุกหมวดก่อนส่งให้แอดมินตรวจ") });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await api.actorSubmitReview(v.id);
      setMessage({ kind: "info", text: tx("ส่งชุดเสียงให้แอดมินตรวจแล้ว") });
      reload();
    } catch (e) { setMessage({ kind: "error", text: (e as Error).message }); } finally { setBusy(false); }
  };
  const remove = async (v: LibraryVoice) => {
    if (!window.confirm(tx("ลบเสียง \"{0}\" ออกจากคลัง?", { 0: v.name }))) return;
    try {
      await api.actorDeleteVoice(v.id);
      if (target.voice?.id === v.id || liveVoice?.id === v.id) { setTarget({}); setFreshVoice(false); }
      reload();
    } catch (e) { setMessage({ kind: "error", text: (e as Error).message }); }
  };

  const lines = target.mood ? MOOD_SCRIPT[target.mood] : SCRIPT;
  const title = target.mood && liveVoice
    ? tx("เสียงอารมณ์{0} ของ {1}", { 0: tx(MOOD_LABEL[target.mood]), 1: liveVoice.name })
    : liveVoice ? tx("อัดเสียงหลักของ {0} ใหม่", { 0: liveVoice.name }) : tx("เสียงหลักใหม่");
  const pickedNormal = !!liveVoice && !target.mood && !freshVoice;
  return (
    <>
      <section className="card" aria-labelledby="studio-title">
        <div className="row" style={{ justifyContent: "space-between", gap: 10 }}>
          <h2 id="studio-title" style={{ margin: 0 }}>{tx("ห้องอัด ·")} {title}</h2>
          {liveVoice && (
            <button type="button" className="btn small" onClick={() => { setFreshVoice(true); setTarget({}); setBlob(null); setKey((k) => k + 1); }}>
              {tx("อัดเสียงใหม่แทน")}
            </button>
          )}
        </div>
        <p className="muted" style={{ margin: 0 }}>
          {target.mood
            ? tx("อัดในห้องเงียบ ไม่มีเสียงแอร์หรือพัดลม ห่างไมค์ประมาณหนึ่งฝ่ามือ อ่านด้วยน้ำเสียงปกติของคุณ") + tx("ในอารมณ์นั้น")
            : tx("อัดในห้องเงียบ ไม่มีเสียงแอร์หรือพัดลม ห่างไมค์ประมาณหนึ่งฝ่ามือ อ่านด้วยน้ำเสียงปกติของคุณ")}
          {" "}{tx("ไม่ต้องรีบ เว้นจังหวะหายใจตามธรรมชาติ")}
          {" "}{tx("เลือกหมวดอารมณ์ด้านล่างแล้วอัดทีละหมวด ต้องครบทุกหมวดก่อนส่งตรวจ")}
        </p>

        {liveVoice ? (
          <MoodCategories
            v={liveVoice}
            usage={me.mood_usage[liveVoice.id] ?? {}}
            picked={target.mood}
            pickedNormal={pickedNormal}
            onPick={(m) => pickSlot(liveVoice, m)}
            onPickNormal={() => pickSlot(liveVoice)}
            preview={preview}
          />
        ) : (
          <div className="mood-cats">
            <span className="label" style={{ margin: 0 }}>{tx("หมวดอารมณ์")}</span>
            <div className="mood-grid" role="list">
              {(["normal", ...MOODS] as MoodSlot[]).map((slot) => (
                <div key={slot} className="mood-card badge-empty" role="listitem">
                  <button type="button" className="mood-card-main" disabled
                    title={tx("อัดเสียงหลักก่อน แล้วค่อยเลือกหมวดอารมณ์")}>
                    <span className="mood-card-mark" aria-hidden>+</span>
                    <span className="mood-card-label">{slot === "normal" ? tx("ปกติ") : tx(MOOD_LABEL[slot])}</span>
                    <span className="mood-card-hint">{tx("อัดเสียงหลักก่อน")}</span>
                  </button>
                </div>
              ))}
            </div>
            <span className="dim">{tx("อัดและบันทึกเสียงหลักก่อน จากนั้นจะเลือกหมวดอารมณ์ด้านบนนี้ได้")}</span>
          </div>
        )}

        <ol className="script">{lines.map((l) => <li key={l}>{l}</li>)}</ol>
        <Recorder key={`${key}-${liveVoice?.id ?? "new"}-${target.mood ?? "normal"}`} disabled={busy}
          onDone={(b, name) => setBlob(b ? { data: b, name } : null)} />
        <label className="agree">
          <input type="checkbox" checked={denoise} onChange={(e) => setDenoise(e.target.checked)} />
          {tx("ลดเสียงรบกวน (แนะนำเมื่ออัดด้วยไมค์มือถือหรือโน้ตบุ๊ก)")}
        </label>
        <button type="button" className="btn primary" style={{ alignSelf: "flex-start" }} disabled={!blob || busy} onClick={send}>
          {busy ? tx("กำลังบันทึก...") : target.mood
            ? tx("บันทึกหมวด {0}", { 0: tx(MOOD_LABEL[target.mood]) })
            : tx("บันทึกเสียงหลัก")}
        </button>
        {liveVoice && showSubmit(liveVoice) && (
          <div className="row" style={{ gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            <button type="button" className="btn primary" disabled={busy || !canSubmit(liveVoice)}
              onClick={() => submitReview(liveVoice)}
              title={canSubmit(liveVoice) ? undefined : tx("ต้องอัดเสียงอารมณ์ให้ครบทุกหมวดก่อนส่งให้แอดมินตรวจ")}>
              {busy ? tx("กำลังส่ง...") : tx("ส่งให้แอดมินตรวจ")}
            </button>
            {hasRejected(liveVoice) ? (
              <span className="dim">{tx("มีหมวดที่ถูกตีกลับ ให้อัดใหม่ก่อนส่งตรวจ")}</span>
            ) : !packageComplete(liveVoice) ? (
              <span className="dim">{tx("อัดให้ครบทุกหมวดอารมณ์ก่อน ปุ่มนี้จะเปิดให้กด")}</span>
            ) : null}
          </div>
        )}
        {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
      </section>

      <section className="card" aria-labelledby="my-voices">
        <h2 id="my-voices">{tx("เสียงของฉัน")}</h2>
        {me.voices.length === 0 ? <span className="dim">{tx("ยังไม่ได้ส่งเสียง")}</span> : me.voices.map((v) => (
          <div key={v.id} className="actor-voice">
            <div className="row" style={{ justifyContent: "space-between", gap: 10 }}>
              <div className="row" style={{ gap: 8 }}>
                <strong>{v.name}</strong>
                {v.status === "processing" ? <span className="badge running">{VOICE_STAGE_LABEL[v.stage] ?? v.stage}...</span>
                  : v.status === "failed" ? <span className="badge failed">{tx("เตรียมเสียงไม่สำเร็จ")}</span>
                  : v.review && REVIEW_BADGE[v.review]}
                <span className="dim">{tx("เสียงอารมณ์ {0}/{1}", {
                  0: v.moods.filter((x) => x.status === "ready").length, 1: MOODS.length })}</span>
              </div>
              <div className="row" style={{ gap: 6 }}>
                <button type="button" className="btn small" onClick={() => pickSlot(v)}>{tx("เลือกเพื่ออัดอารมณ์")}</button>
                <button type="button" className="btn small" onClick={() => remove(v)}>{tx("ลบ")}</button>
              </div>
            </div>
            {v.error && <div className="alert error">{v.error}</div>}
            {v.review === "rejected" && v.review_note && <div className="alert error">{tx("ผู้ดูแล:")} {v.review_note}</div>}
          </div>
        ))}
      </section>
    </>
  );
}

const EMPTY_PAYMENT: ActorPayment = { payee_name: "", tax_id: "", address: "", bank: "", account_no: "", account_name: "" };

/** ข้อมูลรับค่าตอบแทน: ผู้ดูแลบันทึกการจ่ายไม่ได้จนกว่าจะกรอก แก้ต้องกรอกเลขใหม่ทั้งหมด (หน้านี้เห็นแค่ 4 ตัวท้าย) */
function PaymentSection({ me, reload }: { me: ActorMe; reload: () => void }) {
  const [edit, setEdit] = useState(!me.payment);
  const [form, setForm] = useState<ActorPayment>(me.payment ? { ...me.payment, tax_id: "", account_no: "" } : EMPTY_PAYMENT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (k: keyof ActorPayment) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try { await api.actorSavePayment(form); setEdit(false); reload(); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  };
  const p = me.payment;
  const wht = me.wht.percent > 0
    ? tx("หักภาษี ณ ที่จ่ายร้อยละ {0} เมื่อจ่ายครั้งละตั้งแต่ {1} และออกหนังสือรับรองการหักภาษีให้", { 0: me.wht.percent, 1: fmtBaht(me.wht.min) })
    : "";
  return (
    <section className="card" aria-labelledby="pay-title">
      <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
        <h2 id="pay-title" style={{ margin: 0 }}>{tx("ข้อมูลรับเงิน")}</h2>
        {p && !edit && <button type="button" className="btn small" onClick={() => setEdit(true)}>{tx("แก้ไข")}</button>}
      </div>
      <span className="muted" style={{ fontSize: 14 }}>
        
        {tx("ใช้โอนค่าตอบแทนและยื่นภาษี")} {wht}  {tx("ข้อมูลนี้เห็นเฉพาะคุณและผู้ดูแล")}
      </span>
      {!p && <div className="alert info">{tx("กรอกข้อมูลรับเงินก่อน ผู้ดูแลถึงจะจ่ายค่าตอบแทนให้ได้")}</div>}
      {p && !edit ? (
        <dl className="profile-list">
          <div><dt className="dim">{tx("ผู้รับเงิน")}</dt><dd>{p.payee_name}</dd></div>
          <div><dt className="dim">{tx("เลขผู้เสียภาษี")}</dt><dd>{p.tax_id}</dd></div>
          <div><dt className="dim">{tx("ที่อยู่")}</dt><dd>{p.address}</dd></div>
          <div><dt className="dim">{tx("บัญชี")}</dt><dd>{p.bank} {p.account_no} ({p.account_name})</dd></div>
        </dl>
      ) : (
        <form onSubmit={save} style={{ display: "grid", gap: 12 }}>
          <div className="field"><label htmlFor="pp-name">{tx("ชื่อ-นามสกุลผู้รับเงิน (ตามบัตรประชาชน)")}</label>
            <input id="pp-name" className="input" value={form.payee_name} onChange={set("payee_name")} required maxLength={100} /></div>
          <div className="field"><label htmlFor="pp-tax">{tx("เลขประจำตัวผู้เสียภาษี / เลขบัตรประชาชน 13 หลัก")}</label>
            <input id="pp-tax" className="input" value={form.tax_id} onChange={set("tax_id")} required inputMode="numeric"
              autoComplete="off" placeholder={p ? tx("เดิม {0} (กรอกใหม่ทั้งหมด)", { 0: p.tax_id }) : ""} /></div>
          <div className="field"><label htmlFor="pp-addr">{tx("ที่อยู่ตามบัตรประชาชน")}</label>
            <textarea id="pp-addr" className="textarea" rows={2} value={form.address} onChange={set("address")} required maxLength={300} /></div>
          <div className="field"><label htmlFor="pp-bank">{tx("ธนาคาร")}</label>
            <select id="pp-bank" className="select" value={form.bank} onChange={set("bank")} required>
              <option value="">{tx("เลือกธนาคาร")}</option>
              {me.banks.map((b) => <option key={b} value={b}>{b}</option>)}
            </select></div>
          <div className="field"><label htmlFor="pp-acc">{tx("เลขบัญชี")}{form.bank === "พร้อมเพย์" ? tx(" (เบอร์โทรหรือเลขบัตรประชาชน)") : ""}</label>
            <input id="pp-acc" className="input" value={form.account_no} onChange={set("account_no")} required inputMode="numeric"
              autoComplete="off" placeholder={p ? tx("เดิม {0} (กรอกใหม่ทั้งหมด)", { 0: p.account_no }) : ""} /></div>
          <div className="field"><label htmlFor="pp-accname">{tx("ชื่อบัญชี")}</label>
            <input id="pp-accname" className="input" value={form.account_name} onChange={set("account_name")} required maxLength={100} /></div>
          {error && <div className="alert error" role="alert">{error}</div>}
          <div className="row" style={{ gap: 10 }}>
            <button type="submit" className="btn primary small" disabled={busy}>{busy ? tx("กำลังบันทึก...") : tx("บันทึกข้อมูลรับเงิน")}</button>
            {p && <button type="button" className="btn small" onClick={() => { setEdit(false); setError(""); }}>{tx("ยกเลิก")}</button>}
          </div>
        </form>
      )}
    </section>
  );
}

function Earnings({ me }: { me: ActorMe }) {
  const [open, setOpen] = useState("");
  const [rows, setRows] = useState<UsageRow[]>([]);
  const toggle = (m: string) => {
    if (open === m) { setOpen(""); return; }
    setOpen(m);
    setRows([]);
    api.actorUsage(m).then(setRows).catch(() => setRows([]));
  };
  return (
    <section className="card" aria-labelledby="earn-title">
      <h2 id="earn-title">{tx("ค่าตอบแทน")}</h2>
      <span className="muted">{tx("อัตรา")} {fmtBaht(me.rate)}  {tx("ต่อนาทีของเสียงพากย์ที่ผู้ใช้คนอื่นสร้างจากเสียงของคุณ (งานที่พากย์ใหม่นับเฉพาะรอบล่าสุด)")}</span>
      {me.usage.length === 0 ? <span className="dim">{tx("ยังไม่มีการใช้เสียง")}</span> : (
        <table className="ledger">
          <thead><tr><th>{tx("เดือน")}</th><th>{tx("เวลาที่ใช้")}</th><th>{tx("งาน")}</th><th>{tx("ค่าตอบแทน")}</th><th>{tx("จ่ายแล้ว")}</th><th>{tx("ค้างจ่าย")}</th><th /></tr></thead>
          <tbody>
            {me.usage.map((u) => (
              <Fragment key={u.month}>
                <tr>
                  <td>{fmtMonth(u.month)}</td>
                  <td>{fmtMin(u.seconds)}{u.self_seconds > 0 && <div className="dim">{tx("ใช้เอง")} {fmtMin(u.self_seconds)}</div>}</td>
                  <td>{u.jobs}</td>
                  <td>{fmtBaht(u.amount)}</td>
                  <td>{fmtBaht(u.paid)}</td>
                  <td>{fmtBaht(Math.max(0, u.due))}</td>
                  <td><button type="button" className="btn small" onClick={() => toggle(u.month)}>{open === u.month ? tx("ซ่อน") : tx("รายการ")}</button></td>
                </tr>
                {open === u.month && (
                  <tr><td colSpan={7}>
                    {rows.length === 0 ? <span className="dim">{tx("กำลังโหลด...")}</span> : (
                      <table className="ledger">
                        <tbody>{rows.map((r) => (
                          <tr key={`${r.job_id}-${r.voice_id}`}>
                            <td>{fmtDate(r.updated_at)}</td>
                            <td>{r.lines}  {tx("ประโยค")}</td>
                            <td>{fmtMin(r.seconds)}</td>
                            <td>{r.payable ? fmtBaht(r.amount) : <span className="dim">{tx("งานของคุณเอง")}</span>}</td>
                          </tr>
                        ))}</tbody>
                      </table>
                    )}
                  </td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
      {me.payouts.length > 0 && (
        <details>
          <summary className="dim">{tx("ประวัติการรับเงิน")}</summary>
          <table className="ledger">
            <thead><tr><th>{tx("วันที่จ่าย")}</th><th>{tx("ค่าตอบแทนเดือน")}</th><th>{tx("ยอดก่อนหักภาษี")}</th><th>{tx("ภาษีหัก ณ ที่จ่าย")}</th><th>{tx("โอนจริง")}</th></tr></thead>
            <tbody>{me.payouts.map((p) => (
              <tr key={p.id}>
                <td>{fmtDate(p.paid_at)}</td><td>{fmtMonth(p.month)}</td><td>{fmtBaht(p.amount)}</td>
                <td>{fmtBaht(p.wht)}</td><td>{fmtBaht(p.amount - p.wht)}</td>
              </tr>
            ))}</tbody>
          </table>
        </details>
      )}
    </section>
  );
}

export default function ActorPage() {
  const { config, user, loaded } = useAuth();
  const [me, setMe] = useState<ActorMe | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const reload = useCallback(() => { api.actorMe().then(setMe).catch((e) => setError(e.message)); }, []);
  useEffect(() => { if (user) reload(); }, [user, reload]);

  const accept = async (version: string, items: string[]) => {
    setBusy(true);
    try { await api.actorAccept(version, items); reload(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const withdraw = async () => {
    if (!window.confirm(tx("ถอนความยินยอม? เสียงทั้งหมดของคุณจะถูกลบออกจากคลังทันที และกู้คืนไม่ได้"))) return;
    try { await api.actorWithdraw(); reload(); } catch (e) { setError((e as Error).message); }
  };

  if (!loaded) return <main className="page"><div className="empty">{tx("กำลังโหลด...")}</div></main>;
  if (!config?.auth || !user) {
    return (
      <main className="page narrow">
        <div className="card">
          <span className="muted">{tx("เข้าสู่ระบบก่อนสมัครเป็นนักพากย์")}</span>
          <a href="/actor-consent">{tx("อ่านหนังสือยินยอมและเงื่อนไขค่าตอบแทนก่อนสมัคร")}</a>
        </div>
      </main>
    );
  }
  const a = me?.actor;
  return (
    <main className="page" style={{ maxWidth: 860 }}>
      <div className="page-head">
        <div>
          <h1>{tx("นักพากย์")}</h1>
          {a && <span className="muted">{a.stage_name} · {a.status === "approved" ? tx("อนุมัติแล้ว") : tx(STATUS_TEXT[a.status])}</span>}
        </div>
        {a && a.status !== "withdrawn" && <button type="button" className="btn small" onClick={withdraw}>{tx("ถอนความยินยอม")}</button>}
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {!me ? <div className="empty">{tx("กำลังโหลด...")}</div>
        : !a || a.status === "withdrawn" || a.status === "rejected" ? (
          <>
            {a?.status === "rejected" && <div className="alert error">{tx("ใบสมัครไม่ผ่าน")}{a.note ? `: ${a.note}` : ""}  {tx("แก้ไขแล้วสมัครใหม่ได้")}</div>}
            <ApplyForm onDone={reload} />
          </>
        ) : a.status === "pending" ? (
          <div className="card">
            <h2>{tx("ส่งใบสมัครแล้ว")}</h2>
            <span className="muted">{tx("รอผู้ดูแลอนุมัติ เมื่ออนุมัติแล้วหน้านี้จะเปิดห้องอัดเสียงให้")}</span>
            {me.consent && <span className="dim">{tx("ยอมรับหนังสือยินยอมเวอร์ชัน")} {me.consent.version}  {tx("เมื่อ")} {fmtDate(me.consent.accepted_at)}</span>}
          </div>
        ) : !me.consent_current ? (
          <section className="card">
            <h2>{tx("หนังสือยินยอมมีเวอร์ชันใหม่")}</h2>
            <span className="muted">{tx("อ่านและกดยอมรับก่อนส่งเสียงใหม่ เสียงที่อยู่ในคลังแล้วยังใช้ได้ตามปกติ")}</span>
            <ConsentBox busy={busy} label={tx("ยอมรับเวอร์ชันใหม่")} onAccept={accept} />
          </section>
        ) : (
          <>
            <Studio me={me} reload={reload} />
            <Earnings me={me} />
            <PaymentSection key={me.payment?.updated_at ?? 0} me={me} reload={reload} />
            {me.consent && <span className="dim">{tx("ยอมรับหนังสือยินยอมเวอร์ชัน")} {me.consent.version}  {tx("เมื่อ")} {fmtDate(me.consent.accepted_at)}</span>}
          </>
        )}
    </main>
  );
}
