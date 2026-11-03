"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert, fmtCredits, fmtDate, useRunner } from "@/components/Billing";
import { api, type AccountType, type AdminUser, type Backups, type Plan } from "@/lib/api";
import { fmtNum } from "@/lib/format";
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

/** ผู้ดูแลระบบ: ผู้ใช้ทั้งหมด (เครดิต แพ็กเกจ สิทธิ์ผู้ดูแล) และการสำรองข้อมูล */
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
      <UsersSection me={user.id} billing={config.billing} />
      <BackupSection />
    </main>
  );
}
