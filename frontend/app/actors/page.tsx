"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { PreviewButton, usePreview } from "@/components/VoicePreview";
import { api, fileUrl, type ActorConsentRecord, type ActorPayment, type AdminActor, type AdminActorPayout, type LibraryVoice, type Mood,
  type UsageRow, type UsageSummary, type WhtRule } from "@/lib/api";
import { fmtBaht, GENDER_LABEL, MOOD_LABEL, VOICE_STAGE_LABEL } from "@/lib/format";
import { useAuth } from "@/lib/useAuth";

import { locale, tx } from "@/lib/i18n";
type Message = { kind: "error" | "info"; text: string } | null;
const fmtDate = (unix: number) =>
  new Date(unix * 1000).toLocaleString(locale(), { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const fmtMin = (sec: number) => tx("{0} นาที", { 0: (sec / 60).toLocaleString(locale(), { maximumFractionDigits: 1 }) });
const thisMonth = () => {
  const d = new Date(Date.now() + 7 * 3600_000); // เดือนตามเวลาไทย เหมือน API
  return d.toISOString().slice(0, 7);
};
const STATUS_LABEL: Record<string, string> = { pending: "รออนุมัติ", approved: "อนุมัติแล้ว", rejected: "ไม่ผ่าน", withdrawn: "ถอนตัว" };
const STATUS_BADGE: Record<string, string> = { pending: "awaiting_review", approved: "done", rejected: "failed", withdrawn: "cancelled" };

function useRun(load: () => void) {
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState<Message>(null);
  const run = async (key: string, fn: () => Promise<unknown>, done: string) => {
    setBusy(key);
    setMessage(null);
    try { await fn(); load(); setMessage({ kind: "info", text: done }); }
    catch (e) { setMessage({ kind: "error", text: (e as Error).message }); }
    finally { setBusy(""); }
  };
  return { busy, message, run };
}

const Alert = ({ m }: { m: Message }) =>
  m && <div className={`alert ${m.kind}`} role={m.kind === "error" ? "alert" : "status"}>{m.text}</div>;

function Applicants() {
  const [list, setList] = useState<AdminActor[] | null>(null);
  const [open, setOpen] = useState("");
  const [history, setHistory] = useState<ActorConsentRecord[]>([]);
  const load = useCallback(() => { api.adminActors().then(setList).catch(() => setList([])); }, []);
  const toggle = (id: string) => {
    if (open === id) { setOpen(""); return; }
    setOpen(id);
    setHistory([]);
    api.adminActorConsents(id).then(setHistory).catch(() => setHistory([]));
  };
  const { busy, message, run } = useRun(load);
  useEffect(load, [load]);
  const review = (a: AdminActor, approve: boolean) => {
    const note = approve ? "" : window.prompt(tx("เหตุผลที่ไม่อนุมัติ {0} (นักพากย์จะเห็น)", { 0: a.stage_name }), "");
    if (note === null) return;
    run(`a-${a.user_id}`, () => api.adminReviewActor(a.user_id, approve, note), approve ? tx("อนุมัติ {0} แล้ว", { 0: a.stage_name }) : tx("ไม่อนุมัติ {0}", { 0: a.stage_name }));
  };
  return (
    <section className="card" aria-labelledby="apps">
      <h2 id="apps">{tx("ผู้สมัครและนักพากย์")}</h2>
      <Alert m={message} />
      {!list ? <div className="empty">{tx("กำลังโหลด...")}</div> : list.length === 0 ? <span className="dim">{tx("ยังไม่มีผู้สมัคร")}</span> : (
        <table className="ledger">
          <thead><tr><th>{tx("นักพากย์")}</th><th>{tx("รายละเอียด")}</th><th>{tx("ความยินยอม")}</th><th>{tx("สถานะ")}</th><th /></tr></thead>
          <tbody>
            {list.map((a) => (
              <Fragment key={a.user_id}>
              <tr>
                <td><strong>{a.stage_name}</strong> · {tx(GENDER_LABEL[a.gender])}<div className="dim">{a.email}</div></td>
                <td style={{ maxWidth: 280, whiteSpace: "pre-wrap" }}>{a.bio}<div className="dim">{tx("ติดต่อ:")} {a.contact || "-"}</div></td>
                <td>{a.consent_version ? <>{a.consent_version}<div className="dim">{a.consent_at && fmtDate(a.consent_at)}</div></> : <span className="dim">{tx("ไม่มี")}</span>}
                  <button type="button" className="btn small" style={{ marginTop: 4 }} onClick={() => toggle(a.user_id)}>
                    {open === a.user_id ? tx("ซ่อนประวัติ") : tx("ประวัติ")}</button></td>
                <td><span className={`badge ${STATUS_BADGE[a.status]}`}>{tx(STATUS_LABEL[a.status])}</span>
                  <div className="dim">{tx("เสียง")} {a.voices}{a.pending ? tx(" · รอตรวจ {0}", { 0: a.pending }) : ""}</div></td>
                <td>
                  {a.status !== "withdrawn" && (
                    <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                      {a.status !== "approved" && <button type="button" className="btn primary small" disabled={!!busy} onClick={() => review(a, true)}>{tx("อนุมัติ")}</button>}
                      {a.status !== "rejected" && <button type="button" className="btn small" disabled={!!busy} onClick={() => review(a, false)}>{a.status === "approved" ? tx("ระงับ") : tx("ไม่อนุมัติ")}</button>}
                    </div>
                  )}
                </td>
              </tr>
              {open === a.user_id && (
                <tr><td colSpan={5}>
                  {history.length === 0 ? <span className="dim">{tx("กำลังโหลด...")}</span> : (
                    <table className="ledger">
                      <thead><tr><th>{tx("ยอมรับเมื่อ")}</th><th>{tx("ฉบับ")}</th><th>{tx("ข้อที่ยอมรับ")}</th><th>{tx("IP / เบราว์เซอร์")}</th><th>{tx("ถอนเมื่อ")}</th></tr></thead>
                      <tbody>{history.map((h) => (
                        <tr key={`${h.accepted_at}`}>
                          <td>{fmtDate(h.accepted_at)}</td>
                          <td>{h.version}<div className="dim mono" title={h.text_hash}>{h.text_hash.slice(0, 12)}</div></td>
                          <td>{h.items || <span className="dim">{tx("(ฉบับแรก ไม่ได้แยกข้อ)")}</span>}</td>
                          <td>{h.ip}<div className="dim" style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                            title={h.user_agent}>{h.user_agent}</div></td>
                          <td>{h.withdrawn_at ? fmtDate(h.withdrawn_at) : <span className="dim">-</span>}</td>
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

function VoiceReview() {
  const preview = usePreview();
  const [list, setList] = useState<LibraryVoice[] | null>(null);
  const [all, setAll] = useState(false);
  const load = useCallback(() => { api.adminActorVoices().then(setList).catch(() => setList([])); }, []);
  const { busy, message, run } = useRun(load);
  useEffect(load, [load]);
  const preparing = (list ?? []).some((v) => [v, ...v.moods].some((x) => x.status === "processing"));
  useEffect(() => {
    if (!preparing) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [preparing, load]);
  const review = (v: LibraryVoice, approve: boolean) => {
    const note = approve ? "" : window.prompt(tx("บอก {0} ว่าต้องแก้อะไร (เช่น เสียงแอร์ดัง อ่านเร็วเกิน)", { 0: v.actor }), "");
    if (note === null) return;
    run(`v-${v.id}`, () => api.adminReviewVoice(v.id, approve, note), approve ? tx("เสียง {0} ขึ้นคลังแล้ว", { 0: v.name }) : tx("ส่งกลับให้ {0} อัดใหม่", { 0: v.actor }));
  };
  const reviewMood = (v: LibraryVoice, m: Mood, approve: boolean) => {
    const note = approve ? "" : window.prompt(tx("บอก {0} ว่าต้องแก้อะไร (เช่น เสียงแอร์ดัง อ่านเร็วเกิน)", { 0: v.actor }), "");
    if (note === null) return;
    const label = tx(MOOD_LABEL[m]);
    run(`m-${v.id}-${m}`, () => api.adminReviewMood(v.id, m, approve, note),
      approve ? tx("อารมณ์{0}ของ {1} ใช้ได้แล้ว", { 0: label, 1: v.name }) : tx("ส่งอารมณ์{0}กลับให้ {1} อัดใหม่", { 0: label, 1: v.actor }));
  };
  const pendingMoods = (v: LibraryVoice) => v.moods.some((m) => m.review === "pending");
  const shown = (list ?? []).filter((v) => all || v.review === "pending" || pendingMoods(v));
  return (
    <section className="card" aria-labelledby="vr">
      <div className="row" style={{ justifyContent: "space-between", gap: 10 }}>
        <h2 id="vr" style={{ margin: 0 }}>{tx("ตรวจฟังเสียง")}</h2>
        <label className="agree"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />{tx("แสดงที่ตรวจแล้วด้วย")}</label>
      </div>
      <Alert m={message} />
      {!list ? <div className="empty">{tx("กำลังโหลด...")}</div> : shown.length === 0 ? <span className="dim">{tx("ไม่มีเสียงรอตรวจ")}</span> : shown.map((v) => (
        <div key={v.id} className="actor-voice">
          <div className="row" style={{ justifyContent: "space-between", gap: 10 }}>
            <div className="row" style={{ gap: 8 }}>
              <strong>{v.name}</strong><span className="dim">{tx("โดย")} {v.actor}</span>
              {v.status === "processing" ? <span className="badge running">{VOICE_STAGE_LABEL[v.stage] ?? v.stage}...</span>
                : v.status === "failed" ? <span className="badge failed">{tx("เตรียมไม่สำเร็จ")}</span>
                : <span className={`badge ${STATUS_BADGE[v.review === "draft" ? "pending" : (v.review ?? "pending")]}`}>
                    {v.review === "approved" ? tx("อยู่ในคลัง") : v.review === "rejected" ? tx("ให้อัดใหม่")
                      : v.review === "draft" ? tx("บันทึกแล้ว ยังไม่ส่งตรวจ") : tx("รอตรวจ")}</span>}
              {v.quality != null && <span className={`badge ${v.quality < 2.3 ? "warn" : "queued"}`}>{tx("ความสะอาด")} {v.quality.toFixed(1)}</span>}
            </div>
            <div className="row" style={{ gap: 6 }}>
              {v.status === "ready" && <PreviewButton url={fileUrl.voice(v.id, v.updated_at)} playing={preview.playing} onToggle={preview.toggle} />}
              <button type="button" className="btn primary small" disabled={!!busy || v.status !== "ready" || v.review === "approved"}
                title={tx("อนุมัติครั้งแรกให้นักพากย์โบนัส 5 เครดิต")}
                onClick={() => review(v, true)}>{tx("อนุมัติขึ้นคลัง")}</button>
              <button type="button" className="btn small" disabled={!!busy || v.review === "rejected"} onClick={() => review(v, false)}>{tx("ให้อัดใหม่")}</button>
            </div>
          </div>
          {v.text && <span className="muted" style={{ fontSize: 14 }}>{tx("ข้อความที่ถอดได้:")} {v.text}</span>}
          {v.error && <div className="alert error">{v.error}</div>}
          {v.moods.length > 0 && (
            <div style={{ display: "grid", gap: 6 }}>
              <span className="dim">{tx("เสียงอารมณ์ (ตรวจแยกทีละอารมณ์ เสียงหลักไม่ต้องตรวจใหม่)")}</span>
              {v.moods.map((m) => (
                <div key={m.mood} className="mood-review">
                  {m.status === "ready"
                    ? <PreviewButton url={fileUrl.voiceMood(v.id, m.mood, v.updated_at)} playing={preview.playing} onToggle={preview.toggle} label={tx(MOOD_LABEL[m.mood])} />
                    : <span className="badge queued">{tx(MOOD_LABEL[m.mood])} · {m.status === "failed" ? tx("ไม่สำเร็จ") : tx("กำลังเตรียม")}</span>}
                  <span className={`badge ${STATUS_BADGE[m.review === "draft" ? "pending" : (m.review ?? "pending")]}`}>
                    {m.review === "approved" ? tx("ใช้ได้") : m.review === "rejected" ? tx("ให้อัดใหม่")
                      : m.review === "draft" ? tx("บันทึกแล้ว ยังไม่ส่งตรวจ") : tx("รอตรวจ")}
                  </span>
                  {m.text && <span className="muted" style={{ fontSize: 13, flex: "1 1 200px" }}>{m.text}</span>}
                  <span style={{ marginLeft: "auto" }} className="row">
                    <button type="button" className="btn primary small" disabled={!!busy || m.status !== "ready" || m.review === "approved"}
                      onClick={() => reviewMood(v, m.mood, true)}>{tx("อนุมัติ")}</button>
                    <button type="button" className="btn small" disabled={!!busy || m.review === "rejected"}
                      onClick={() => reviewMood(v, m.mood, false)}>{tx("ให้อัดใหม่")}</button>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}

function Compensation() {
  const [month, setMonth] = useState(thisMonth());
  const [data, setData] = useState<{ rate: number; rows: UsageSummary[]; payouts: AdminActorPayout[]; wht: WhtRule } | null>(null);
  const [open, setOpen] = useState("");
  const [rows, setRows] = useState<UsageRow[]>([]);
  const load = useCallback(() => { api.adminActorUsage(month).then(setData).catch(() => setData(null)); }, [month]);
  const { busy, message, run } = useRun(load);
  useEffect(load, [load]);
  const toggle = (id: string) => {
    if (open === id) { setOpen(""); return; }
    setOpen(id);
    setRows([]);
    api.adminActorUsageRows(id, month).then(setRows).catch(() => setRows([]));
  };
  const [payee, setPayee] = useState<{ id: string; p: ActorPayment } | null>(null);
  const showPayee = (id: string) => {
    if (payee?.id === id) { setPayee(null); return; }
    api.adminActorPayment(id).then((p) => setPayee({ id, p })).catch(() => setPayee(null));
  };
  const pay = (u: UsageSummary) => {
    const net = u.due - u.wht;
    const tax = u.wht > 0 ? tx(" (ยอด {0} หักภาษี ณ ที่จ่าย {1})", { 0: fmtBaht(u.due), 1: fmtBaht(u.wht) }) : "";
    const note = window.prompt(tx("บันทึกว่าโอน {0}{1} ให้ {2} แล้ว หมายเหตุ (เช่น เลขอ้างอิงการโอน)", { 0: fmtBaht(net), 1: tax, 2: u.stage_name }), "");
    if (note === null) return;
    run(`p-${u.actor_id}`, () => api.adminPayout(u.actor_id, month, note), tx("บันทึกการจ่าย {0} แล้ว", { 0: u.stage_name }));
  };
  const total = (data?.rows ?? []).reduce((s, r) => s + Math.max(0, r.due), 0);
  return (
    <section className="card" aria-labelledby="comp">
      <div className="row" style={{ justifyContent: "space-between", gap: 10 }}>
        <h2 id="comp" style={{ margin: 0 }}>{tx("บันทึกการใช้เสียงและค่าตอบแทน")}</h2>
        <div className="row" style={{ gap: 8 }}>
          <input className="input" type="month" aria-label={tx("เดือน")} value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
          <a className="btn small" href={fileUrl.actorUsageCsv(month)} download>{tx("ดาวน์โหลด CSV")}</a>
          <a className="btn small" href={fileUrl.actorWhtCsv(month)} download title={tx("การจ่ายที่จ่ายจริงในเดือนนี้ สำหรับยื่นแบบหักภาษี ณ ที่จ่ายและออกหนังสือรับรอง")}>{tx("รายการหักภาษี")}</a>
        </div>
      </div>
      {data && <span className="muted">{tx("อัตรา")} {fmtBaht(data.rate)}  {tx("ต่อนาที (ตั้งที่ ACTOR_RATE_SATANG_PER_MIN) · ค้างจ่ายรวม")} {fmtBaht(total)}
        
        {tx("· นับเฉพาะงานของผู้ใช้คนอื่น งานที่พากย์ใหม่นับรอบล่าสุด")}
        {data.wht.percent > 0 ? tx(" · หักภาษี ณ ที่จ่ายร้อยละ {0} เมื่อจ่ายครั้งละตั้งแต่ {1} (ACTOR_WHT_PERCENT)", { 0: data.wht.percent, 1: fmtBaht(data.wht.min) }) : tx(" · ไม่หักภาษี ณ ที่จ่าย")}</span>}
      <Alert m={message} />
      {!data ? <div className="empty">{tx("กำลังโหลด...")}</div> : data.rows.length === 0 ? <span className="dim">{tx("เดือนนี้ยังไม่มีการใช้เสียงนักพากย์")}</span> : (
        <table className="ledger">
          <thead><tr><th>{tx("นักพากย์")}</th><th>{tx("เวลาที่ใช้")}</th><th>{tx("งาน / ผู้ใช้")}</th><th>{tx("ค่าตอบแทน")}</th><th>{tx("จ่ายแล้ว")}</th><th>{tx("ค้างจ่าย")}</th><th /></tr></thead>
          <tbody>
            {data.rows.map((u) => (
              <Fragment key={u.actor_id}>
                <tr>
                  <td>{u.stage_name}<div className="dim">{u.email}</div></td>
                  <td>{fmtMin(u.seconds)}{u.self_seconds > 0 && <div className="dim">{tx("ใช้เอง")} {fmtMin(u.self_seconds)}</div>}</td>
                  <td>{u.jobs} / {u.users}</td>
                  <td>{fmtBaht(u.amount)}</td>
                  <td>{fmtBaht(u.paid)}</td>
                  <td>
                    {u.due < 0 ? <span className="dim">{tx("จ่ายเกิน")} {fmtBaht(-u.due)}</span> : fmtBaht(u.due)}
                    {u.wht > 0 && <div className="dim">{tx("หักภาษี")} {fmtBaht(u.wht)}  {tx("โอน")} {fmtBaht(u.due - u.wht)}</div>}
                  </td>
                  <td>
                    <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                      <button type="button" className="btn small" onClick={() => toggle(u.actor_id)}>{open === u.actor_id ? tx("ซ่อน") : tx("รายการ")}</button>
                      {u.payee
                        ? <button type="button" className="btn small" onClick={() => showPayee(u.actor_id)}>{tx("บัญชี")}</button>
                        : <span className="dim" title={tx("นักพากย์ต้องกรอกข้อมูลรับเงินที่หน้าบัญชีก่อน")}>{tx("ยังไม่กรอกบัญชี")}</span>}
                      <button type="button" className="btn primary small" disabled={!!busy || u.due <= 0 || !u.payee} onClick={() => pay(u)}>{tx("จ่ายแล้ว")}</button>
                    </div>
                  </td>
                </tr>
                {payee?.id === u.actor_id && (
                  <tr><td colSpan={7}>
                    <dl className="profile-list">
                      <div><dt className="dim">{tx("ผู้รับเงิน")}</dt><dd>{payee.p.payee_name}</dd></div>
                      <div><dt className="dim">{tx("เลขผู้เสียภาษี")}</dt><dd>{payee.p.tax_id}</dd></div>
                      <div><dt className="dim">{tx("ที่อยู่")}</dt><dd>{payee.p.address}</dd></div>
                      <div><dt className="dim">{tx("บัญชี")}</dt><dd>{payee.p.bank} {payee.p.account_no} ({payee.p.account_name})</dd></div>
                    </dl>
                  </td></tr>
                )}
                {open === u.actor_id && (
                  <tr><td colSpan={7}>
                    {rows.length === 0 ? <span className="dim">{tx("กำลังโหลด...")}</span> : (
                      <table className="ledger">
                        <thead><tr><th>{tx("พากย์ล่าสุด")}</th><th>{tx("งาน")}</th><th>{tx("ประโยค")}</th><th>{tx("เวลา")}</th><th>{tx("เงิน")}</th></tr></thead>
                        <tbody>{rows.map((r) => (
                          <tr key={`${r.job_id}-${r.voice_id}`}>
                            <td>{fmtDate(r.updated_at)}</td>
                            <td><a href={`/jobs/${r.job_id}`}>{r.job_name || r.job_id}</a></td>
                            <td>{r.lines}</td>
                            <td>{fmtMin(r.seconds)}</td>
                            <td>{r.payable ? fmtBaht(r.amount) : <span className="dim">{tx("ใช้เอง")}</span>}</td>
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
      {data && data.payouts.length > 0 && (
        <details>
          <summary className="dim">{tx("ประวัติการจ่าย")}</summary>
          <table className="ledger">
            <tbody>{data.payouts.map((p) => (
              <tr key={p.id}>
                <td>{fmtDate(p.paid_at)}</td><td>{p.month}</td><td>{p.payee_name || "-"}</td><td>{fmtBaht(p.amount)}</td>
                <td>{p.wht > 0 ? tx("หัก {0}", { 0: fmtBaht(p.wht) }) : "-"}</td><td>{tx("โอน")} {fmtBaht(p.amount - p.wht)}</td><td>{p.note}</td><td className="dim">{p.paid_by}</td>
              </tr>
            ))}</tbody>
          </table>
        </details>
      )}
    </section>
  );
}

const TABS = [["voices", "ตรวจฟังเสียง"], ["actors", "ผู้สมัคร"], ["pay", "ค่าตอบแทน"]] as const;

export default function ActorsAdminPage() {
  const { user, loaded } = useAuth();
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("voices");
  if (!loaded) return <main className="page"><div className="empty">{tx("กำลังโหลด...")}</div></main>;
  if (!user?.admin) return <main className="page narrow"><div className="card"><span className="muted">{tx("เฉพาะผู้ดูแลระบบ")}</span></div></main>;
  return (
    <main className="page" style={{ maxWidth: 1080 }}>
      <div className="page-head">
        <h1>{tx("ตรวจนักพากย์")}</h1>
        <div className="seg" role="tablist" aria-label={tx("ส่วน")}>
          {TABS.map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} aria-pressed={tab === k} onClick={() => setTab(k)}>{tx(label)}</button>
          ))}
        </div>
      </div>
      {tab === "voices" ? <VoiceReview /> : tab === "actors" ? <Applicants /> : <Compensation />}
    </main>
  );
}
