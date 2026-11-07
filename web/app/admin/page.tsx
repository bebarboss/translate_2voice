"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert, fmtCredits, fmtDate, useRunner } from "@/components/Billing";
import { api, fileUrl, type AccountType, type AdminUser, type Backups, type PaymentOrder, type Plan, type Quality, type QualityKind, type QualityLine } from "@/lib/api";
import { fmtBaht, fmtNum } from "@/lib/format";
import { locale, tx } from "@/lib/i18n";
import { useAuth } from "@/lib/useAuth";

const TYPE_LABEL: Record<AccountType, string> = { personal: "บุคคลทั่วไป", creator: "ครีเอเตอร์", business: "บริษัท / หน่วยงาน" };

/** ผู้ดูแล: ไฟล์สำรองข้อมูลอัตโนมัติ และปุ่มสำรองทันที */
function BackupSection() {
  const [data, setData] = useState<Backups | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = () => api.backups().then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  const now = async () => {
    setBusy(true); setError("");
    try { await api.backupNow(); await load(); } catch (e) { setError(e instanceof Error ? e.message : tx("สำรองไม่สำเร็จ")); }
    finally { setBusy(false); }
  };
  const last = data?.backups[0];
  return (
    <section className="card" aria-labelledby="backup-title">
      <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
        <h2 id="backup-title" style={{ margin: 0 }}>{tx("สำรองข้อมูล")}</h2>
        <button type="button" className="btn small" onClick={now} disabled={busy}>{busy ? tx("กำลังสำรอง...") : tx("สำรองทันที")}</button>
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {data && (
        <span className="muted" style={{ fontSize: 14 }}>
          {data.hours > 0 ? tx("สำรองอัตโนมัติทุก {0} ชั่วโมง เก็บ {1} ชุดล่าสุด", { 0: data.hours, 1: data.keep }) : tx("ปิดการสำรองอัตโนมัติอยู่ (BACKUP_HOURS=0)")}
          {" · "}{last ? tx("ล่าสุด {0} ({1} MB) ทั้งหมด {2} ชุด", { 0: new Date(last.created_at * 1000).toLocaleString(locale()), 1: (last.bytes / 1e6).toFixed(1), 2: data.backups.length }) : tx("ยังไม่มีไฟล์สำรอง")}
        </span>
      )}
    </section>
  );
}

/** ผู้ดูแล: ผู้ใช้แก้อะไรจากที่ AI ทำบ่อยแค่ไหน (วัดผลหลังปรับระบบ) และบรรทัดที่แก้ล่าสุด (ชุดทดสอบ) */
const KIND_LABEL: Record<string, string> = { text: "คำแปล", speaker: "ผู้พูด", time: "เวลา" };
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

function QualitySection() {
  const [days, setDays] = useState(30);
  const [kind, setKind] = useState<QualityKind>("");
  const [data, setData] = useState<Quality | null>(null);
  const [lines, setLines] = useState<QualityLine[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.quality(days).then(setData).catch((e) => setError(e.message)); }, [days]);
  useEffect(() => { setLines(null); api.qualityLines(days, kind, 30).then(setLines).catch((e) => setError(e.message)); }, [days, kind]);
  const t = data?.total;
  return (
    <section className="card" aria-labelledby="quality-title">
      <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
        <h2 id="quality-title" style={{ margin: 0 }}>{tx("คุณภาพงาน")}</h2>
        <div className="seg" role="group" aria-label={tx("ช่วงเวลา")}>
          {[7, 30, 90].map((d) => (
            <button key={d} type="button" aria-pressed={days === d} onClick={() => setDays(d)}>{tx("{0} วัน", { 0: d })}</button>
          ))}
        </div>
      </div>
      <span className="muted" style={{ fontSize: 14 }}>
        {tx("เทียบบทที่ AI ทำกับบทที่ผู้ใช้ใช้พากย์จริง ยิ่งต่ำยิ่งดี (นับทุกครั้งที่พากย์เสร็จ งานก่อนหน้านี้ไม่มีข้อมูล)")}
      </span>
      {error && <div className="alert error" role="alert">{error}</div>}
      {data && !data.available && (
        <div className="alert info">{tx("ยังไม่ได้สร้างตารางบน Supabase: รัน supabase/migrations/20261104010000_quality.sql ใน SQL Editor")}</div>
      )}
      {t && data?.available && (t.jobs === 0 ? <div className="empty">{tx("ยังไม่มีงานที่พากย์เสร็จในช่วงนี้")}</div> : <>
        <div className="row" style={{ gap: 24, flexWrap: "wrap" }}>
          {([
            [tx("แก้คำแปล"), pct(t.text_edited)],
            [tx("เปลี่ยนผู้พูด"), pct(t.speaker_changed)],
            [tx("เลื่อนเวลา"), pct(t.retimed)],
            [tx("ระยะแก้คำแปล"), pct(t.edit_distance)],
            [tx("พากย์ต่องาน"), tx("{0} ครั้ง", { 0: t.synth_runs })],
            [tx("งาน / บรรทัด"), `${fmtNum(t.jobs)} / ${fmtNum(t.lines)}`],
          ] as [string, string][]).map(([k, v]) => (
            <div key={k}><div className="dim">{k}</div><b className="mono" style={{ fontSize: 20 }}>{v}</b></div>
          ))}
        </div>
        <table className="ledger" style={{ minWidth: 0 }}>
          <thead><tr><th>{tx("สัปดาห์ / ภาษา")}</th><th>{tx("งาน")}</th><th>{tx("คำแปล")}</th><th>{tx("ผู้พูด")}</th><th>{tx("เวลา")}</th><th>{tx("ระยะแก้")}</th><th>{tx("พากย์ต่องาน")}</th></tr></thead>
          <tbody>
            {[...data.weeks.map((w) => ({ ...w, label: tx("สัปดาห์ {0}", { 0: new Date(w.key).toLocaleDateString(locale(), { day: "numeric", month: "short" }) }) })),
              ...data.langs.map((l) => ({ ...l, label: l.key }))].map((r) => (
              <tr key={r.label}>
                <td>{r.label}</td><td className="mono">{r.jobs}</td><td className="mono">{pct(r.text_edited)}</td>
                <td className="mono">{pct(r.speaker_changed)}</td><td className="mono">{pct(r.retimed)}</td>
                <td className="mono">{pct(r.edit_distance)}</td><td className="mono">{r.synth_runs}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </>)}
      {data?.available && (
        <>
          <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
            <h3 style={{ margin: 0 }}>{tx("บรรทัดที่ผู้ใช้แก้ล่าสุด")}</h3>
            <div className="row" style={{ gap: 8 }}>
              <div className="seg" role="group" aria-label={tx("แบบที่แก้")}>
                {(["", "text", "speaker", "time"] as QualityKind[]).map((k) => (
                  <button key={k || "all"} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}>{k ? tx(KIND_LABEL[k]) : tx("ทั้งหมด")}</button>
                ))}
              </div>
              <a className="btn small" href={fileUrl.qualityCsv(days, kind)} download>{tx("ดาวน์โหลดชุดทดสอบ (CSV)")}</a>
            </div>
          </div>
          {!lines ? <div className="empty">{tx("กำลังโหลด...")}</div> : lines.length === 0 ? <div className="empty">{tx("ยังไม่มี")}</div> : (
            <table className="ledger" style={{ minWidth: 0 }}>
              <thead><tr><th>{tx("งาน")}</th><th>{tx("ต้นฉบับ")}</th><th>{tx("AI")}</th><th>{tx("ผู้ใช้แก้เป็น")}</th></tr></thead>
              <tbody>
                {lines.map((l) => (
                  <tr key={`${l.job_id}-${l.line_id}`}>
                    <td><Link href={`/jobs/${l.job_id}`} className="mono">{l.job_id.slice(0, 6)}#{l.line_id}</Link>
                      <div className="dim">{l.kinds.split(",").map((k) => tx(KIND_LABEL[k] ?? k)).join(" · ")}</div></td>
                    <td className="muted">{l.source}</td>
                    <td>{l.ai_target}{l.ai_speaker !== l.final_speaker && <div className="dim">{l.ai_speaker}</div>}</td>
                    <td>{l.final_target}{l.ai_speaker !== l.final_speaker && <div className="dim">{l.final_speaker}</div>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

/** ผู้ดูแล: คิวสลิปที่ Typhoon OCR อ่านแล้วยอดไม่ตรง หรืออ่านไม่ได้ */
function PaymentsSection() {
  const [status, setStatus] = useState("review");
  const [rows, setRows] = useState<PaymentOrder[] | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const load = () => {
    api.adminPayments(status).then(setRows).catch((e) => setMessage({ kind: "error", text: e.message }));
  };
  const { busy, message, setMessage, run } = useRunner(load);
  useEffect(() => { load(); }, [status]);
  return (
    <section className="card" aria-labelledby="slips-title">
      <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
        <h2 id="slips-title" style={{ margin: 0 }}>{tx("สลิปโอนเงิน")}</h2>
        <div className="seg" role="group" aria-label={tx("สถานะสลิป")}>
          <button type="button" aria-pressed={status === "review"} onClick={() => setStatus("review")}>{tx("รอตรวจ")}</button>
          <button type="button" aria-pressed={status === ""} onClick={() => setStatus("")}>{tx("ทั้งหมด")}</button>
        </div>
      </div>
      <span className="muted" style={{ fontSize: 14 }}>
        {tx("ยอดตรงและเลขบัญชีปลายทางอยู่ในสลิปจะเติมให้อัตโนมัติ รายการในคิวนี้คือรายการที่ต้องดูรูปเอง")}
      </span>
      <Alert m={message} />
      {!rows ? null : rows.length === 0 ? <div className="empty">{tx(status === "review" ? "ยังไม่มีสลิปรอตรวจ" : "ยังไม่มีรายการ")}</div> : (
        <div style={{ overflowX: "auto" }}>
          <table className="ledger">
            <thead>
              <tr>
                <th>{tx("ผู้ใช้")}</th><th>{tx("รายการ")}</th><th>{tx("ยอดที่ต้องโอน")}</th><th>{tx("ยอดที่อ่านได้")}</th>
                <th>{tx("สลิป")}</th><th>{tx("หมายเหตุ")}</th><th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td>{p.email}<div className="dim">{p.name}</div></td>
                  <td>{p.plan_id ? p.plan_id : tx("{0} เครดิต", { 0: fmtNum(p.credits) })}<div className="dim">{tx(p.status === "review" ? "รอตรวจสลิป" : p.status === "paid" ? "เติมแล้ว" : p.status === "rejected" ? "สลิปไม่ผ่าน" : "รอโอน")}</div></td>
                  <td className="mono">{fmtBaht(p.amount)}</td>
                  <td className="mono">{p.ocr?.amount ? fmtBaht(p.ocr.amount) : tx("อ่านไม่ได้")}</td>
                  <td>
                    {p.has_slip
                      ? <a href={fileUrl.slip(p.id)} target="_blank" rel="noreferrer"><img src={fileUrl.slip(p.id)} alt={tx("ดูสลิป")} style={{ height: 72, borderRadius: 6 }} /></a>
                      : <span className="dim">—</span>}
                  </td>
                  <td className="dim">{p.note}{p.ocr?.payer ? <div>{tx("ผู้โอน")} {p.ocr.payer}</div> : null}</td>
                  <td>
                    {p.status === "review" && (
                      <div className="row" style={{ gap: 6 }}>
                        <button type="button" className="btn small" disabled={!!busy}
                          onClick={() => run(`ok-${p.id}`, () => api.adminApprovePayment(p.id), tx("อนุมัติสลิปแล้ว"))}>
                          {busy === `ok-${p.id}` ? "..." : tx("อนุมัติ")}
                        </button>
                        <input className="input" style={{ width: 140 }} placeholder={tx("เหตุผล (ไม่บังคับ)")} aria-label={tx("เหตุผล (ไม่บังคับ)")}
                          value={notes[p.id] ?? ""} onChange={(e) => setNotes({ ...notes, [p.id]: e.target.value })} />
                        <button type="button" className="btn small" disabled={!!busy}
                          onClick={() => run(`no-${p.id}`, () => api.adminRejectPayment(p.id, notes[p.id] ?? ""), tx("ไม่ผ่านสลิปแล้ว"))}>
                          {busy === `no-${p.id}` ? "..." : tx("ไม่ผ่าน")}
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** ผู้ดูแล: ดูผู้ใช้ทุกคน เพิ่ม/หักเครดิต และให้แพ็กเกจ (รับโอนนอกระบบ ชดเชย ฯลฯ) */
function UsersSection({ me, billing }: { me: string; billing: boolean }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const load = () => {
    api.adminUsers().then(setUsers).catch((e) => setMessage({ kind: "error", text: e.message }));
  };
  const { busy, message, setMessage, run } = useRunner(load);
  useEffect(() => {
    load();
    api.plans().then((p) => setPlans(p.plans)).catch(() => setPlans([]));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const q = query.trim().toLowerCase();
  const shown = (users ?? []).filter((u) => !q || u.email.includes(q) || u.name.toLowerCase().includes(q)
    || u.profile.full_name.toLowerCase().includes(q) || u.profile.phone.includes(q) || u.profile.company.toLowerCase().includes(q));
  return (
    <section className="card" aria-labelledby="admin-title">
      <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
        <h2 id="admin-title" style={{ margin: 0 }}>{tx("ผู้ใช้ทั้งหมด")}</h2>
        <input className="input" style={{ maxWidth: 260 }} type="search" placeholder={tx("ค้นหาอีเมล ชื่อ เบอร์ บริษัท")}
          aria-label={tx("ค้นหาผู้ใช้")} value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <Alert m={message} />
      {!users ? <div className="empty">{tx("กำลังโหลด...")}</div> : (
        <table className="ledger admin-users">
          <thead><tr><th>{tx("ผู้ใช้")}</th>{billing && <><th>{tx("เครดิต")}</th><th>{tx("แพ็กเกจ")}</th><th>{tx("เพิ่ม / หักเครดิต")}</th><th>{tx("ให้แพ็กเกจ")}</th></>}<th>{tx("ผู้ดูแล")}</th></tr></thead>
          <tbody>
            {shown.map((u) => {
              const plan = plans.find((p) => p.id === u.subscription?.plan_id);
              const n = Math.round(parseFloat(amounts[u.id] ?? "") * 100) / 100;
              return (
                <tr key={u.id}>
                  <td>{u.name}{u.admin ? tx(" · ผู้ดูแล") : ""}<div className="dim">{u.email}</div>
                    {u.profile_complete ? (
                      <div className="dim">{u.profile.full_name} · {u.profile.phone}
                        {u.profile.account_type && ` · ${tx(TYPE_LABEL[u.profile.account_type])}`}{u.profile.company && ` (${u.profile.company})`}</div>
                    ) : <div className="dim">{tx("ยังไม่กรอกข้อมูล")}</div>}
                    {!u.consent_current && <div className="dim">{tx("ยังไม่ยอมรับข้อกำหนดฉบับปัจจุบัน")}</div>}
                  </td>
                  {billing && <>
                  <td className="mono">{fmtNum(u.credits)}</td>
                  <td>{u.subscription && plan
                    ? <>{plan.name} · {fmtNum(u.subscription.minutes_left)}<div className="dim">{tx("ถึง")} {fmtDate(u.subscription.expires_at)}</div></>
                    : <span className="dim">{tx("ไม่มี")}</span>}</td>
                  <td>
                    <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                      <input className="input" style={{ width: 96 }} type="number" step={0.01} placeholder={tx("เช่น 30")}
                        aria-label={tx("จำนวนเครดิตของ {0} (ติดลบ = หัก)", { 0: u.email })}
                        value={amounts[u.id] ?? ""} onChange={(e) => setAmounts({ ...amounts, [u.id]: e.target.value })} />
                      <button type="button" className="btn small" disabled={!!busy || !Number.isFinite(n) || n === 0}
                        onClick={() => window.confirm(tx("{0} {1} ให้ {2}?", { 0: n > 0 ? tx("เพิ่ม") : tx("หัก"), 1: fmtCredits(Math.abs(n)), 2: u.email }))
                          && run(`c-${u.id}`, async () => { await api.adminCredit(u.id, n); setAmounts({ ...amounts, [u.id]: "" }); },
                            tx("{0} {1} ให้ {2} แล้ว", { 0: n > 0 ? tx("เพิ่ม") : tx("หัก"), 1: fmtCredits(Math.abs(n)), 2: u.email }))}>
                        {busy === `c-${u.id}` ? "..." : tx("บันทึก")}
                      </button>
                    </div>
                  </td>
                  <td>
                    <select className="select" style={{ width: 170 }} aria-label={tx("ให้แพ็กเกจกับ {0}", { 0: u.email })} value="" disabled={!!busy}
                      onChange={(e) => {
                        const p = plans.find((x) => x.id === e.target.value);
                        if (p && window.confirm(tx("ให้แพ็กเกจ{0} ({1} / {2} วัน) กับ {3} ฟรี? เครดิตแพ็กเกจเดิมจะไม่ทบ", { 0: p.name, 1: fmtCredits(p.minutes), 2: p.days, 3: u.email })))
                          run(`p-${u.id}`, () => api.adminPlan(u.id, p.id), tx("ให้แพ็กเกจ{0}กับ {1} แล้ว", { 0: p.name, 1: u.email }));
                      }}>
                      <option value="">{tx("เลือกแพ็กเกจ")}</option>
                      {plans.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.minutes}</option>)}
                    </select>
                  </td>
                  </>}
                  <td>
                    {u.owner ? <span className="dim">{tx("ผู้ดูแลหลัก")}</span> : u.id === me ? <span className="dim">{tx("คุณ")}</span> : (
                      <button type="button" className="btn small" disabled={!!busy}
                        onClick={() => window.confirm(u.admin
                          ? tx("ถอดสิทธิ์ผู้ดูแลของ {0}?", { 0: u.email })
                          : tx("ให้ {0} เป็นผู้ดูแล? จะพากย์ได้ไม่จำกัด แก้คลังเสียง ค่าตั้งระบบ และสิทธิ์ของผู้ใช้คนอื่นได้", { 0: u.email }))
                          && run(`a-${u.id}`, () => api.adminSetAdmin(u.id, !u.admin),
                            tx("{0} {1} แล้ว", { 0: u.admin ? tx("ถอดสิทธิ์ผู้ดูแลของ") : tx("ให้สิทธิ์ผู้ดูแลกับ"), 1: u.email }))}>
                        {busy === `a-${u.id}` ? "..." : u.admin ? tx("ถอดสิทธิ์") : tx("ให้สิทธิ์")}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

const FEEDBACK_CAT: Record<string, string> = {
  bug: "บั๊กหรือข้อผิดพลาด", billing: "เครดิตและการชำระเงิน", quality: "คุณภาพพากย์",
  feature: "ขอฟีเจอร์", other: "อื่น ๆ",
};

function FeedbackSection() {
  const [rows, setRows] = useState<import("@/lib/api").FeedbackItem[] | null>(null);
  const [error, setError] = useState("");
  const { busy, message, run } = useRunner(() => api.adminFeedback().then(setRows).catch((e) => setError(e.message)));
  useEffect(() => {
    api.adminFeedback().then(setRows).catch((e) => setError(e.message));
  }, []);
  const open = rows?.filter((r) => r.status === "open") ?? [];
  return (
    <section className="card" aria-labelledby="feedback-title">
      <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
        <h2 id="feedback-title" style={{ margin: 0 }}>{tx("แจ้งปัญหา")}{open.length ? ` (${open.length})` : ""}</h2>
        <Link href="/support" className="btn small">{tx("หน้าแจ้งปัญหา")}</Link>
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      <Alert m={message} />
      {!rows ? <div className="empty">{tx("กำลังโหลด...")}</div> : rows.length === 0 ? (
        <div className="empty">{tx("ยังไม่มีรายงาน")}</div>
      ) : (
        <ul style={{ listStyle: "none", margin: "12px 0 0", padding: 0 }}>
          {rows.map((f) => (
            <li key={f.id} style={{ padding: "12px 0", borderTop: "1px solid var(--border)" }}>
              <div className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <div>
                  <b>{f.subject}</b>
                  <div className="dim" style={{ fontSize: 13 }}>
                    {tx(FEEDBACK_CAT[f.category] || f.category)} · {f.email || f.name || f.user_id || "—"}
                    {" · "}{new Date(f.created_at * 1000).toLocaleString(locale())}
                    {f.job_id ? ` · ${f.job_id}` : ""}
                  </div>
                </div>
                <span className={`badge ${f.status === "done" ? "done" : "warn"}`}>
                  {f.status === "done" ? tx("ปิดแล้ว") : tx("รอดู")}
                </span>
              </div>
              <p style={{ margin: "8px 0", whiteSpace: "pre-wrap", fontSize: 14 }}>{f.body}</p>
              {f.status === "open" ? (
                <button type="button" className="btn small" disabled={!!busy}
                  onClick={() => run(`f-${f.id}`, () => api.adminResolveFeedback(f.id, "done"), tx("ปิดรายงานแล้ว"))}>
                  {busy === `f-${f.id}` ? "..." : tx("ปิดรายงาน")}
                </button>
              ) : (
                <button type="button" className="btn small" disabled={!!busy}
                  onClick={() => run(`f-${f.id}`, () => api.adminResolveFeedback(f.id, "open"), tx("เปิดรายงานใหม่แล้ว"))}>
                  {busy === `f-${f.id}` ? "..." : tx("เปิดใหม่")}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** ผู้ดูแลระบบ: ผู้ใช้ทั้งหมด (เครดิต แพ็กเกจ สิทธิ์ผู้ดูแล) คุณภาพงาน และการสำรองข้อมูล */
export default function AdminPage() {
  const { config, user, loaded } = useAuth();
  useEffect(() => {
    if (loaded && config?.auth && !user) window.location.href = "/welcome?next=/admin";
  }, [loaded, config, user]);

  if (!loaded || (config?.auth && !user)) return <main className="page"><div className="empty">{tx("กำลังโหลด...")}</div></main>;
  if (!config?.auth || !user?.admin) {
    return <main className="page narrow"><div className="card"><span className="muted">{tx("เฉพาะผู้ดูแลระบบ")}</span></div></main>;
  }
  return (
    <main className="page" style={{ maxWidth: 1120 }}>
      <div className="page-head">
        <h1>{tx("ผู้ดูแลระบบ")}</h1>
        <div className="row" style={{ gap: 8 }}>
          <Link href="/actors" className="btn small">{tx("ตรวจนักพากย์")}</Link>
          <Link href="/settings" className="btn small">{tx("ตั้งค่า")}</Link>
        </div>
      </div>
      <FeedbackSection />
      <UsersSection me={user.id} billing={config.billing} />
      {config.billing && <PaymentsSection />}
      <QualitySection />
      <BackupSection />
    </main>
  );
}
