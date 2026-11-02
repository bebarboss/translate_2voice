"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import Recorder from "@/components/Recorder";
import { PreviewButton, usePreview } from "@/components/VoicePreview";
import { api, fileUrl, type ActorMe, type Gender, type LibraryVoice, type Mood, type UsageRow } from "@/lib/api";
import { fmtBaht, GENDER_LABEL, MOOD_LABEL, MOODS, VOICE_STAGE_LABEL } from "@/lib/format";
import { useAuth } from "@/lib/useAuth";

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
/** บทของเสียงอารมณ์ พูดด้วยอารมณ์นั้นจริง ๆ */
const MOOD_SCRIPT: Record<Mood, string> = {
  angry: "พอได้แล้ว! ฉันบอกกี่ครั้งแล้วว่าอย่าแตะของของฉัน ออกไปเดี๋ยวนี้!",
  sad: "ฉันรอเธอมาทั้งคืน แต่เธอก็ไม่มา... บางทีเราอาจจะไม่ได้เจอกันอีกแล้ว",
  happy: "จริงเหรอ! เราสอบผ่านแล้ว! ดีใจที่สุดเลย ไปฉลองกันเถอะ!",
  whisper: "ชู่ว์... เบา ๆ หน่อย เดี๋ยวคนอื่นได้ยิน เรามีความลับต้องคุยกัน",
  scared: "อะไรน่ะ! มีใครอยู่ตรงนั้นหรือเปล่า... อย่าเข้ามานะ ฉันกลัว!",
};

const STATUS_TEXT = { pending: "รอผู้ดูแลอนุมัติใบสมัคร", rejected: "ใบสมัครไม่ผ่าน", withdrawn: "ถอนความยินยอมแล้ว" } as const;
const fmtDate = (unix: number) =>
  new Date(unix * 1000).toLocaleString("th-TH", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const fmtMin = (sec: number) => `${(sec / 60).toLocaleString("th-TH", { maximumFractionDigits: 1 })} นาที`;
const fmtMonth = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString("th-TH", { month: "long", year: "numeric" });

function ConsentBox({ onAccept, busy, label }: { onAccept: (version: string) => void; busy: boolean; label: string }) {
  const [doc, setDoc] = useState<{ version: string; text: string } | null>(null);
  const [pdpa, setPdpa] = useState(false);
  const [license, setLicense] = useState(false);
  useEffect(() => { api.actorConsent().then(setDoc).catch(() => setDoc(null)); }, []);
  if (!doc) return <div className="empty">กำลังโหลดหนังสือยินยอม...</div>;
  return (
    <div className="field">
      <span className="label">หนังสือยินยอม (อ่านให้ครบก่อนกดยอมรับ)</span>
      <div className="consent-box" tabIndex={0}>{doc.text}</div>
      <label className="agree">
        <input type="checkbox" checked={pdpa} onChange={(e) => setPdpa(e.target.checked)} />
        ข้าพเจ้ายินยอมโดยชัดแจ้งให้เก็บ ใช้ และส่งข้อมูลเสียงและลายเสียงของข้าพเจ้าไปประมวลผลต่างประเทศ ตามหนังสือข้างต้น
      </label>
      <label className="agree">
        <input type="checkbox" checked={license} onChange={(e) => setLicense(e.target.checked)} />
        ข้าพเจ้าอนุญาตให้ผู้ใช้ในระบบใช้เสียงของข้าพเจ้าสร้างงานพากย์ และรับรองว่าเสียงที่ส่งเป็นเสียงของข้าพเจ้าเอง
      </label>
      <button type="button" className="btn primary" style={{ alignSelf: "flex-start" }}
        disabled={busy || !pdpa || !license} onClick={() => onAccept(doc.version)}>{label}</button>
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
  const submit = async (version: string) => {
    setBusy(true);
    setError("");
    try {
      await api.actorApply({ stage_name: name.trim(), gender, bio, contact, consent_version: version });
      onDone();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <section className="card" aria-labelledby="apply-title">
      <h2 id="apply-title">สมัครเป็นนักพากย์</h2>
      <p className="muted" style={{ margin: 0 }}>
        อัดเสียงของคุณเข้าคลังเสียง ให้ผู้ใช้ทุกคนเลือกใช้พากย์ได้ และรับค่าตอบแทนตามเวลาที่เสียงของคุณถูกใช้
        ผู้ดูแลจะตรวจใบสมัครก่อน
      </p>
      <div className="field">
        <label htmlFor="stage">ชื่อในวงการ (แสดงคู่กับเสียง)</label>
        <input id="stage" className="input" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <span className="label">เพศของเสียง</span>
        <div className="seg" role="group" aria-label="เพศของเสียง" style={{ alignSelf: "flex-start" }}>
          {(["male", "female", ""] as Gender[]).map((g) => (
            <button key={g || "none"} type="button" aria-pressed={gender === g} onClick={() => setGender(g)}>{GENDER_LABEL[g]}</button>
          ))}
        </div>
      </div>
      <div className="field">
        <label htmlFor="bio">ประสบการณ์ / สไตล์เสียง</label>
        <textarea id="bio" className="input" rows={3} maxLength={1000} value={bio} onChange={(e) => setBio(e.target.value)}
          placeholder="เช่น พากย์การ์ตูนมา 5 ปี เสียงทุ้ม เหมาะกับบทพระเอก" />
      </div>
      <div className="field">
        <label htmlFor="contact">ช่องทางติดต่อ / รับเงิน</label>
        <input id="contact" className="input" maxLength={200} value={contact} onChange={(e) => setContact(e.target.value)}
          placeholder="เช่น LINE ID หรือเบอร์โทร" />
      </div>
      {name.trim() ? <ConsentBox busy={busy} label={busy ? "กำลังส่ง..." : "ยอมรับและส่งใบสมัคร"} onAccept={submit} />
        : <span className="dim">กรอกชื่อในวงการก่อน แล้วจะเห็นหนังสือยินยอม</span>}
      {error && <div className="alert error" role="alert">{error}</div>}
    </section>
  );
}

const REVIEW_BADGE = {
  pending: <span className="badge awaiting_review">รอผู้ดูแลตรวจ</span>,
  approved: <span className="badge done">อยู่ในคลังแล้ว</span>,
  rejected: <span className="badge failed">ให้อัดใหม่</span>,
};

function Studio({ me, reload }: { me: ActorMe; reload: () => void }) {
  const preview = usePreview();
  const [target, setTarget] = useState<{ voice?: LibraryVoice; mood?: Mood }>({});
  const [blob, setBlob] = useState<{ data: Blob; name: string } | null>(null);
  const [denoise, setDenoise] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [key, setKey] = useState(0); // เปลี่ยนแล้วล้างเครื่องอัด

  // เสียงที่กำลังเตรียมอยู่ โหลดสถานะใหม่ทุก 4 วินาที
  const preparing = me.voices.some((v) => [v, ...v.moods].some((x) => x.status === "processing"));
  useEffect(() => {
    if (!preparing) return;
    const t = setInterval(reload, 4000);
    return () => clearInterval(t);
  }, [preparing, reload]);

  const send = async () => {
    if (!blob) return;
    setBusy(true);
    setMessage(null);
    try {
      await api.actorRecord(blob.data, blob.name, { voiceId: target.voice?.id, mood: target.mood, denoise });
      setBlob(null);
      setKey((k) => k + 1);
      setTarget({});
      setMessage({ kind: "info", text: "ส่งเสียงแล้ว ระบบกำลังเตรียมเสียง แล้วผู้ดูแลจะตรวจฟังก่อนขึ้นคลัง" });
      reload();
    } catch (e) { setMessage({ kind: "error", text: (e as Error).message }); } finally { setBusy(false); }
  };
  const remove = async (v: LibraryVoice) => {
    if (!window.confirm(`ลบเสียง "${v.name}" ออกจากคลัง?`)) return;
    try { await api.actorDeleteVoice(v.id); reload(); } catch (e) { setMessage({ kind: "error", text: (e as Error).message }); }
  };

  const lines = target.mood ? [MOOD_SCRIPT[target.mood]] : SCRIPT;
  const title = target.mood ? `เสียงอารมณ์${MOOD_LABEL[target.mood]} ของ ${target.voice?.name}`
    : target.voice ? `อัดเสียงหลักของ ${target.voice.name} ใหม่` : "เสียงหลักใหม่";
  return (
    <>
      <section className="card" aria-labelledby="studio-title">
        <div className="row" style={{ justifyContent: "space-between", gap: 10 }}>
          <h2 id="studio-title" style={{ margin: 0 }}>ห้องอัด · {title}</h2>
          {target.voice && <button type="button" className="btn small" onClick={() => setTarget({})}>อัดเสียงใหม่แทน</button>}
        </div>
        <p className="muted" style={{ margin: 0 }}>
          อัดในห้องเงียบ ไม่มีเสียงแอร์หรือพัดลม ห่างไมค์ประมาณหนึ่งฝ่ามือ อ่านด้วยน้ำเสียงปกติของคุณ{target.mood ? "ในอารมณ์นั้น" : ""}
          {" "}ไม่ต้องรีบ เว้นจังหวะหายใจตามธรรมชาติ
        </p>
        <ol className="script">{lines.map((l) => <li key={l}>{l}</li>)}</ol>
        <Recorder key={key} disabled={busy} onDone={(b, name) => setBlob(b ? { data: b, name } : null)} />
        <label className="agree">
          <input type="checkbox" checked={denoise} onChange={(e) => setDenoise(e.target.checked)} />
          ลดเสียงรบกวน (แนะนำเมื่ออัดด้วยไมค์มือถือหรือโน้ตบุ๊ก)
        </label>
        <button type="button" className="btn primary" style={{ alignSelf: "flex-start" }} disabled={!blob || busy} onClick={send}>
          {busy ? "กำลังส่ง..." : "ส่งเสียงให้ผู้ดูแลตรวจ"}
        </button>
        {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
      </section>

      <section className="card" aria-labelledby="my-voices">
        <h2 id="my-voices">เสียงของฉัน</h2>
        {me.voices.length === 0 ? <span className="dim">ยังไม่ได้ส่งเสียง</span> : me.voices.map((v) => (
          <div key={v.id} className="actor-voice">
            <div className="row" style={{ justifyContent: "space-between", gap: 10 }}>
              <div className="row" style={{ gap: 8 }}>
                <strong>{v.name}</strong>
                {v.status === "processing" ? <span className="badge running">{VOICE_STAGE_LABEL[v.stage] ?? v.stage}...</span>
                  : v.status === "failed" ? <span className="badge failed">เตรียมเสียงไม่สำเร็จ</span>
                  : v.review && REVIEW_BADGE[v.review]}
              </div>
              <div className="row" style={{ gap: 6 }}>
                {v.status === "ready" && <PreviewButton url={fileUrl.voice(v.id, v.updated_at)} playing={preview.playing} onToggle={preview.toggle} />}
                <button type="button" className="btn small" onClick={() => setTarget({ voice: v })}>อัดใหม่</button>
                <button type="button" className="btn small" onClick={() => remove(v)}>ลบ</button>
              </div>
            </div>
            {v.error && <div className="alert error">{v.error}</div>}
            {v.review === "rejected" && v.review_note && <div className="alert error">ผู้ดูแล: {v.review_note}</div>}
            <div className="row" style={{ gap: 6 }}>
              <span className="dim">เสียงอารมณ์:</span>
              {MOODS.map((m) => {
                const got = v.moods.find((x) => x.mood === m);
                return (
                  <button key={m} type="button" className="chip" aria-pressed={target.voice?.id === v.id && target.mood === m}
                    title={got ? `${got.status === "ready" ? "มีแล้ว" : got.status === "failed" ? "ไม่สำเร็จ" : "กำลังเตรียม"} กดเพื่ออัดใหม่` : "กดเพื่ออัด"}
                    onClick={() => setTarget({ voice: v, mood: m })}>
                    {got?.status === "ready" ? "✓ " : got?.status === "processing" ? "… " : got ? "! " : "+ "}{MOOD_LABEL[m]}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </section>
    </>
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
      <h2 id="earn-title">ค่าตอบแทน</h2>
      <span className="muted">อัตรา {fmtBaht(me.rate)} ต่อนาทีของเสียงพากย์ที่ผู้ใช้คนอื่นสร้างจากเสียงของคุณ (งานที่พากย์ใหม่นับเฉพาะรอบล่าสุด)</span>
      {me.usage.length === 0 ? <span className="dim">ยังไม่มีการใช้เสียง</span> : (
        <table className="ledger">
          <thead><tr><th>เดือน</th><th>เวลาที่ใช้</th><th>งาน</th><th>ค่าตอบแทน</th><th>จ่ายแล้ว</th><th>ค้างจ่าย</th><th /></tr></thead>
          <tbody>
            {me.usage.map((u) => (
              <Fragment key={u.month}>
                <tr>
                  <td>{fmtMonth(u.month)}</td>
                  <td>{fmtMin(u.seconds)}{u.self_seconds > 0 && <div className="dim">ใช้เอง {fmtMin(u.self_seconds)}</div>}</td>
                  <td>{u.jobs}</td>
                  <td>{fmtBaht(u.amount)}</td>
                  <td>{fmtBaht(u.paid)}</td>
                  <td>{fmtBaht(Math.max(0, u.due))}</td>
                  <td><button type="button" className="btn small" onClick={() => toggle(u.month)}>{open === u.month ? "ซ่อน" : "รายการ"}</button></td>
                </tr>
                {open === u.month && (
                  <tr><td colSpan={7}>
                    {rows.length === 0 ? <span className="dim">กำลังโหลด...</span> : (
                      <table className="ledger">
                        <tbody>{rows.map((r) => (
                          <tr key={`${r.job_id}-${r.voice_id}`}>
                            <td>{fmtDate(r.updated_at)}</td>
                            <td>{r.lines} ประโยค</td>
                            <td>{fmtMin(r.seconds)}</td>
                            <td>{r.payable ? fmtBaht(r.amount) : <span className="dim">งานของคุณเอง</span>}</td>
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

  const accept = async (version: string) => {
    setBusy(true);
    try { await api.actorAccept(version); reload(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const withdraw = async () => {
    if (!window.confirm("ถอนความยินยอม? เสียงทั้งหมดของคุณจะถูกลบออกจากคลังทันที และกู้คืนไม่ได้")) return;
    try { await api.actorWithdraw(); reload(); } catch (e) { setError((e as Error).message); }
  };

  if (!loaded) return <main className="page"><div className="empty">กำลังโหลด...</div></main>;
  if (!config?.auth || !user) {
    return <main className="page narrow"><div className="card"><span className="muted">เข้าสู่ระบบก่อนสมัครเป็นนักพากย์</span></div></main>;
  }
  const a = me?.actor;
  return (
    <main className="page" style={{ maxWidth: 860 }}>
      <div className="page-head">
        <div>
          <h1>นักพากย์</h1>
          {a && <span className="muted">{a.stage_name} · {a.status === "approved" ? "อนุมัติแล้ว" : STATUS_TEXT[a.status]}</span>}
        </div>
        {a && a.status !== "withdrawn" && <button type="button" className="btn small" onClick={withdraw}>ถอนความยินยอม</button>}
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {!me ? <div className="empty">กำลังโหลด...</div>
        : !a || a.status === "withdrawn" || a.status === "rejected" ? (
          <>
            {a?.status === "rejected" && <div className="alert error">ใบสมัครไม่ผ่าน{a.note ? `: ${a.note}` : ""} แก้ไขแล้วสมัครใหม่ได้</div>}
            <ApplyForm onDone={reload} />
          </>
        ) : a.status === "pending" ? (
          <div className="card">
            <h2>ส่งใบสมัครแล้ว</h2>
            <span className="muted">รอผู้ดูแลอนุมัติ เมื่ออนุมัติแล้วหน้านี้จะเปิดห้องอัดเสียงให้</span>
            {me.consent && <span className="dim">ยอมรับหนังสือยินยอมเวอร์ชัน {me.consent.version} เมื่อ {fmtDate(me.consent.accepted_at)}</span>}
          </div>
        ) : !me.consent_current ? (
          <section className="card">
            <h2>หนังสือยินยอมมีเวอร์ชันใหม่</h2>
            <span className="muted">อ่านและกดยอมรับก่อนส่งเสียงใหม่ เสียงที่อยู่ในคลังแล้วยังใช้ได้ตามปกติ</span>
            <ConsentBox busy={busy} label="ยอมรับเวอร์ชันใหม่" onAccept={accept} />
          </section>
        ) : (
          <>
            <Studio me={me} reload={reload} />
            <Earnings me={me} />
            {me.consent && <span className="dim">ยอมรับหนังสือยินยอมเวอร์ชัน {me.consent.version} เมื่อ {fmtDate(me.consent.accepted_at)}</span>}
          </>
        )}
    </main>
  );
}
