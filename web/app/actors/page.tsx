"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { PreviewButton, usePreview } from "@/components/VoicePreview";
import { api, fileUrl, type ActorConsentRecord, type ActorPayment, type ActorPayout, type AdminActor, type LibraryVoice,
  type UsageRow, type UsageSummary, type WhtRule } from "@/lib/api";
import { fmtBaht, GENDER_LABEL, MOOD_LABEL, VOICE_STAGE_LABEL } from "@/lib/format";
import { useAuth } from "@/lib/useAuth";

type Message = { kind: "error" | "info"; text: string } | null;
const fmtDate = (unix: number) =>
  new Date(unix * 1000).toLocaleString("th-TH", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const fmtMin = (sec: number) => `${(sec / 60).toLocaleString("th-TH", { maximumFractionDigits: 1 })} นาที`;
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
    const note = approve ? "" : window.prompt(`เหตุผลที่ไม่อนุมัติ ${a.stage_name} (นักพากย์จะเห็น)`, "");
    if (note === null) return;
    run(`a-${a.user_id}`, () => api.adminReviewActor(a.user_id, approve, note), approve ? `อนุมัติ ${a.stage_name} แล้ว` : `ไม่อนุมัติ ${a.stage_name}`);
  };
  return (
    <section className="card" aria-labelledby="apps">
      <h2 id="apps">ผู้สมัครและนักพากย์</h2>
      <Alert m={message} />
      {!list ? <div className="empty">กำลังโหลด...</div> : list.length === 0 ? <span className="dim">ยังไม่มีผู้สมัคร</span> : (
        <table className="ledger">
          <thead><tr><th>นักพากย์</th><th>รายละเอียด</th><th>ความยินยอม</th><th>สถานะ</th><th /></tr></thead>
          <tbody>
            {list.map((a) => (
              <Fragment key={a.user_id}>
              <tr>
                <td><strong>{a.stage_name}</strong> · {GENDER_LABEL[a.gender]}<div className="dim">{a.email}</div></td>
                <td style={{ maxWidth: 280, whiteSpace: "pre-wrap" }}>{a.bio}<div className="dim">ติดต่อ: {a.contact || "-"}</div></td>
                <td>{a.consent_version ? <>{a.consent_version}<div className="dim">{a.consent_at && fmtDate(a.consent_at)}</div></> : <span className="dim">ไม่มี</span>}
                  <button type="button" className="btn small" style={{ marginTop: 4 }} onClick={() => toggle(a.user_id)}>
                    {open === a.user_id ? "ซ่อนประวัติ" : "ประวัติ"}</button></td>
                <td><span className={`badge ${STATUS_BADGE[a.status]}`}>{STATUS_LABEL[a.status]}</span>
                  <div className="dim">เสียง {a.voices}{a.pending ? ` · รอตรวจ ${a.pending}` : ""}</div></td>
                <td>
                  {a.status !== "withdrawn" && (
                    <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                      {a.status !== "approved" && <button type="button" className="btn primary small" disabled={!!busy} onClick={() => review(a, true)}>อนุมัติ</button>}
                      {a.status !== "rejected" && <button type="button" className="btn small" disabled={!!busy} onClick={() => review(a, false)}>{a.status === "approved" ? "ระงับ" : "ไม่อนุมัติ"}</button>}
                    </div>
                  )}
                </td>
              </tr>
              {open === a.user_id && (
                <tr><td colSpan={5}>
                  {history.length === 0 ? <span className="dim">กำลังโหลด...</span> : (
                    <table className="ledger">
                      <thead><tr><th>ยอมรับเมื่อ</th><th>ฉบับ</th><th>ข้อที่ยอมรับ</th><th>IP / เบราว์เซอร์</th><th>ถอนเมื่อ</th></tr></thead>
                      <tbody>{history.map((h) => (
                        <tr key={`${h.accepted_at}`}>
                          <td>{fmtDate(h.accepted_at)}</td>
                          <td>{h.version}<div className="dim mono" title={h.text_hash}>{h.text_hash.slice(0, 12)}</div></td>
                          <td>{h.items || <span className="dim">(ฉบับแรก ไม่ได้แยกข้อ)</span>}</td>
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
    const note = approve ? "" : window.prompt(`บอก ${v.actor} ว่าต้องแก้อะไร (เช่น เสียงแอร์ดัง อ่านเร็วเกิน)`, "");
    if (note === null) return;
    run(`v-${v.id}`, () => api.adminReviewVoice(v.id, approve, note), approve ? `เสียง ${v.name} ขึ้นคลังแล้ว` : `ส่งกลับให้ ${v.actor} อัดใหม่`);
  };
  const shown = (list ?? []).filter((v) => all || v.review === "pending");
  return (
    <section className="card" aria-labelledby="vr">
      <div className="row" style={{ justifyContent: "space-between", gap: 10 }}>
        <h2 id="vr" style={{ margin: 0 }}>ตรวจฟังเสียง</h2>
        <label className="agree"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />แสดงที่ตรวจแล้วด้วย</label>
      </div>
      <Alert m={message} />
      {!list ? <div className="empty">กำลังโหลด...</div> : shown.length === 0 ? <span className="dim">ไม่มีเสียงรอตรวจ</span> : shown.map((v) => (
        <div key={v.id} className="actor-voice">
          <div className="row" style={{ justifyContent: "space-between", gap: 10 }}>
            <div className="row" style={{ gap: 8 }}>
              <strong>{v.name}</strong><span className="dim">โดย {v.actor}</span>
              {v.status === "processing" ? <span className="badge running">{VOICE_STAGE_LABEL[v.stage] ?? v.stage}...</span>
                : v.status === "failed" ? <span className="badge failed">เตรียมไม่สำเร็จ</span>
                : <span className={`badge ${STATUS_BADGE[v.review ?? "pending"]}`}>{v.review === "approved" ? "อยู่ในคลัง" : v.review === "rejected" ? "ให้อัดใหม่" : "รอตรวจ"}</span>}
              {v.quality != null && <span className={`badge ${v.quality < 2.3 ? "warn" : "queued"}`}>ความสะอาด {v.quality.toFixed(1)}</span>}
            </div>
            <div className="row" style={{ gap: 6 }}>
              {v.status === "ready" && <PreviewButton url={fileUrl.voice(v.id, v.updated_at)} playing={preview.playing} onToggle={preview.toggle} />}
              <button type="button" className="btn primary small" disabled={!!busy || v.status !== "ready" || v.review === "approved"}
                onClick={() => review(v, true)}>อนุมัติขึ้นคลัง</button>
              <button type="button" className="btn small" disabled={!!busy || v.review === "rejected"} onClick={() => review(v, false)}>ให้อัดใหม่</button>
            </div>
          </div>
          {v.text && <span className="muted" style={{ fontSize: 14 }}>ข้อความที่ถอดได้: {v.text}</span>}
          {v.error && <div className="alert error">{v.error}</div>}
          {v.moods.length > 0 && (
            <div className="row" style={{ gap: 8 }}>
              {v.moods.map((m) => (
                <span key={m.mood} className="row" style={{ gap: 4 }}>
                  {m.status === "ready"
                    ? <PreviewButton url={fileUrl.voiceMood(v.id, m.mood, v.updated_at)} playing={preview.playing} onToggle={preview.toggle} label={MOOD_LABEL[m.mood]} />
                    : <span className="badge queued">{MOOD_LABEL[m.mood]} · {m.status === "failed" ? "ไม่สำเร็จ" : "กำลังเตรียม"}</span>}
                </span>
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
  const [data, setData] = useState<{ rate: number; rows: UsageSummary[]; payouts: ActorPayout[]; wht: WhtRule } | null>(null);
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
    const tax = u.wht > 0 ? ` (ยอด ${fmtBaht(u.due)} หักภาษี ณ ที่จ่าย ${fmtBaht(u.wht)})` : "";
    const note = window.prompt(`บันทึกว่าโอน ${fmtBaht(net)}${tax} ให้ ${u.stage_name} แล้ว หมายเหตุ (เช่น เลขอ้างอิงการโอน)`, "");
    if (note === null) return;
    run(`p-${u.actor_id}`, () => api.adminPayout(u.actor_id, month, note), `บันทึกการจ่าย ${u.stage_name} แล้ว`);
  };
  const total = (data?.rows ?? []).reduce((s, r) => s + Math.max(0, r.due), 0);
  return (
    <section className="card" aria-labelledby="comp">
      <div className="row" style={{ justifyContent: "space-between", gap: 10 }}>
        <h2 id="comp" style={{ margin: 0 }}>บันทึกการใช้เสียงและค่าตอบแทน</h2>
        <div className="row" style={{ gap: 8 }}>
          <input className="input" type="month" aria-label="เดือน" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
          <a className="btn small" href={fileUrl.actorUsageCsv(month)} download>ดาวน์โหลด CSV</a>
          <a className="btn small" href={fileUrl.actorWhtCsv(month)} download title="การจ่ายที่จ่ายจริงในเดือนนี้ สำหรับยื่นแบบหักภาษี ณ ที่จ่ายและออกหนังสือรับรอง">รายการหักภาษี</a>
        </div>
      </div>
      {data && <span className="muted">อัตรา {fmtBaht(data.rate)} ต่อนาที (ตั้งที่ ACTOR_RATE_SATANG_PER_MIN) · ค้างจ่ายรวม {fmtBaht(total)}
        · นับเฉพาะงานของผู้ใช้คนอื่น งานที่พากย์ใหม่นับรอบล่าสุด
        {data.wht.percent > 0 ? ` · หักภาษี ณ ที่จ่ายร้อยละ ${data.wht.percent} เมื่อจ่ายครั้งละตั้งแต่ ${fmtBaht(data.wht.min)} (ACTOR_WHT_PERCENT)` : " · ไม่หักภาษี ณ ที่จ่าย"}</span>}
      <Alert m={message} />
      {!data ? <div className="empty">กำลังโหลด...</div> : data.rows.length === 0 ? <span className="dim">เดือนนี้ยังไม่มีการใช้เสียงนักพากย์</span> : (
        <table className="ledger">
          <thead><tr><th>นักพากย์</th><th>เวลาที่ใช้</th><th>งาน / ผู้ใช้</th><th>ค่าตอบแทน</th><th>จ่ายแล้ว</th><th>ค้างจ่าย</th><th /></tr></thead>
          <tbody>
            {data.rows.map((u) => (
              <Fragment key={u.actor_id}>
                <tr>
                  <td>{u.stage_name}<div className="dim">{u.email}</div></td>
                  <td>{fmtMin(u.seconds)}{u.self_seconds > 0 && <div className="dim">ใช้เอง {fmtMin(u.self_seconds)}</div>}</td>
                  <td>{u.jobs} / {u.users}</td>
                  <td>{fmtBaht(u.amount)}</td>
                  <td>{fmtBaht(u.paid)}</td>
                  <td>
                    {u.due < 0 ? <span className="dim">จ่ายเกิน {fmtBaht(-u.due)}</span> : fmtBaht(u.due)}
                    {u.wht > 0 && <div className="dim">หักภาษี {fmtBaht(u.wht)} โอน {fmtBaht(u.due - u.wht)}</div>}
                  </td>
                  <td>
                    <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                      <button type="button" className="btn small" onClick={() => toggle(u.actor_id)}>{open === u.actor_id ? "ซ่อน" : "รายการ"}</button>
                      {u.payee
                        ? <button type="button" className="btn small" onClick={() => showPayee(u.actor_id)}>บัญชี</button>
                        : <span className="dim" title="นักพากย์ต้องกรอกข้อมูลรับเงินที่หน้านักพากย์ก่อน">ยังไม่กรอกบัญชี</span>}
                      <button type="button" className="btn primary small" disabled={!!busy || u.due <= 0 || !u.payee} onClick={() => pay(u)}>จ่ายแล้ว</button>
                    </div>
                  </td>
                </tr>
                {payee?.id === u.actor_id && (
                  <tr><td colSpan={7}>
                    <dl className="profile-list">
                      <div><dt className="dim">ผู้รับเงิน</dt><dd>{payee.p.payee_name}</dd></div>
                      <div><dt className="dim">เลขผู้เสียภาษี</dt><dd>{payee.p.tax_id}</dd></div>
                      <div><dt className="dim">ที่อยู่</dt><dd>{payee.p.address}</dd></div>
                      <div><dt className="dim">บัญชี</dt><dd>{payee.p.bank} {payee.p.account_no} ({payee.p.account_name})</dd></div>
                    </dl>
                  </td></tr>
                )}
                {open === u.actor_id && (
                  <tr><td colSpan={7}>
                    {rows.length === 0 ? <span className="dim">กำลังโหลด...</span> : (
                      <table className="ledger">
                        <thead><tr><th>พากย์ล่าสุด</th><th>งาน</th><th>ประโยค</th><th>เวลา</th><th>เงิน</th></tr></thead>
                        <tbody>{rows.map((r) => (
                          <tr key={`${r.job_id}-${r.voice_id}`}>
                            <td>{fmtDate(r.updated_at)}</td>
                            <td><a href={`/jobs/${r.job_id}`}>{r.job_name || r.job_id}</a></td>
                            <td>{r.lines}</td>
                            <td>{fmtMin(r.seconds)}</td>
                            <td>{r.payable ? fmtBaht(r.amount) : <span className="dim">ใช้เอง</span>}</td>
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
          <summary className="dim">ประวัติการจ่าย</summary>
          <table className="ledger">
            <tbody>{data.payouts.map((p) => (
              <tr key={p.id}>
                <td>{fmtDate(p.paid_at)}</td><td>{p.month}</td><td>{p.payee_name || "-"}</td><td>{fmtBaht(p.amount)}</td>
                <td>{p.wht > 0 ? `หัก ${fmtBaht(p.wht)}` : "-"}</td><td>โอน {fmtBaht(p.amount - p.wht)}</td><td>{p.note}</td><td className="dim">{p.paid_by}</td>
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
  if (!loaded) return <main className="page"><div className="empty">กำลังโหลด...</div></main>;
  if (!user?.admin) return <main className="page narrow"><div className="card"><span className="muted">เฉพาะผู้ดูแลระบบ</span></div></main>;
  return (
    <main className="page" style={{ maxWidth: 1080 }}>
      <div className="page-head">
        <h1>ตรวจนักพากย์</h1>
        <div className="seg" role="tablist" aria-label="ส่วน">
          {TABS.map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} aria-pressed={tab === k} onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>
      </div>
      {tab === "voices" ? <VoiceReview /> : tab === "actors" ? <Applicants /> : <Compensation />}
    </main>
  );
}
