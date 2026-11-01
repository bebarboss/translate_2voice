"use client";

import { useEffect, useState } from "react";
import { api, type AdminUser, type Plan, type Wallet } from "@/lib/api";
import { fmtBaht } from "@/lib/format";
import { useAuth } from "@/lib/useAuth";

const KIND_LABEL: Record<string, string> = {
  topup: "ซื้อเครดิต", subscribe: "ซื้อแพ็กเกจ", charge: "ใช้พากย์", refund: "คืนเครดิต", adjust: "ผู้ดูแลปรับ",
};
const fmtDate = (unix: number) =>
  new Date(unix * 1000).toLocaleDateString("th-TH", { day: "numeric", month: "short", year: "numeric" });
const PAID = new Set(["topup", "subscribe"]); // รายการที่ผู้ใช้จ่ายเงินจริง
const fmtCredits = (n: number) => `${n.toLocaleString()} เครดิต`;
const signed = (n: number) => (n > 0 ? `+${n.toLocaleString()}` : `−${Math.abs(n).toLocaleString()}`);

type Message = { kind: "error" | "info"; text: string } | null;

function useRunner(load: () => void) {
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState<Message>(null);
  const run = async (key: string, fn: () => Promise<unknown>, done: string) => {
    setBusy(key);
    setMessage(null);
    try {
      await fn();
      load();
      setMessage({ kind: "info", text: done });
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally { setBusy(""); }
  };
  return { busy, message, setMessage, run };
}

function WalletSection({ payments, unlimited }: { payments: boolean; unlimited: boolean }) {
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [packs, setPacks] = useState<number[]>([]);
  const [pack, setPack] = useState(30);

  const load = () => {
    api.wallet().then(setWallet).catch((e) => setMessage({ kind: "error", text: e.message }));
    api.plans().then((p) => { setPlans(p.plans); setPacks(p.credit_packs); }).catch(() => setPlans([]));
  };
  const { busy, message, setMessage, run } = useRunner(load);
  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  const sub = wallet?.subscription;
  const current = plans.find((p) => p.id === sub?.plan_id);
  const planCredits = sub?.minutes_left ?? 0;
  const total = (wallet?.credits ?? 0) + planCredits;
  return (
    <>
      <section className="card" aria-labelledby="wallet-title">
        <h2 id="wallet-title">เครดิต</h2>
        <div className="row" style={{ gap: 28, alignItems: "flex-end" }}>
          <div>
            <span className="label">ใช้ได้ทั้งหมด</span>
            <div style={{ fontSize: 30, fontWeight: 600 }}>{unlimited ? "ไม่จำกัด" : wallet ? fmtCredits(total) : "..."}</div>
          </div>
          <div>
            <span className="label">จากแพ็กเกจ</span>
            <div style={{ fontSize: 17 }}>
              {sub && current ? `${current.name} · ${fmtCredits(planCredits)} · หมดอายุ ${fmtDate(sub.expires_at)}` : "ยังไม่มีแพ็กเกจ"}
            </div>
          </div>
          <div>
            <span className="label">เครดิตเติม (ไม่หมดอายุ)</span>
            <div style={{ fontSize: 17 }}>{wallet ? fmtCredits(wallet.credits) : "..."}</div>
          </div>
        </div>
        {unlimited && <div className="alert info">บัญชีผู้ดูแลระบบพากย์ได้ไม่จำกัด ไม่ถูกตัดเครดิต</div>}
        <span className="dim">1 เครดิต = คลิป 1 นาที (ปัดขึ้น) ตัดตอนเริ่มวิเคราะห์คลิป ใช้เครดิตแพ็กเกจก่อน แล้วค่อยใช้เครดิตเติม
          พากย์ซ้ำหรือแก้บทไม่เสียเพิ่ม งานที่วิเคราะห์ไม่สำเร็จได้เครดิตคืน</span>
        {wallet && (
          <div className="field">
            <span className="label">ซื้อเครดิตเติม · เครดิตละ {fmtBaht(wallet.credit_price)}</span>
            <div className="row" style={{ gap: 8 }}>
              <div className="seg" role="group" aria-label="จำนวนเครดิตที่จะซื้อ">
                {packs.map((n) => (
                  <button key={n} type="button" aria-pressed={pack === n} onClick={() => setPack(n)}>{n.toLocaleString()}</button>
                ))}
              </div>
              <button type="button" className="btn primary small" disabled={!payments || !!busy}
                onClick={() => run("topup", () => api.buyCredits(pack), `ได้ ${fmtCredits(pack)} แล้ว`)}>
                {busy === "topup" ? "กำลังซื้อ..." : `ซื้อ ${fmtBaht(pack * wallet.credit_price)}`}
              </button>
            </div>
            {!payments && <span className="dim">ยังไม่ได้เชื่อมช่องทางชำระเงิน ติดต่อผู้ดูแลเพื่อเติมเครดิต</span>}
          </div>
        )}
        {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
      </section>

      <section aria-labelledby="plans-title" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 id="plans-title" style={{ margin: 0, fontSize: 17, fontWeight: 500 }}>แพ็กเกจรายเดือน</h2>
        <div className="plans">
          {plans.map((p) => (
            <article key={p.id} className={`card plan${p.id === sub?.plan_id ? " current" : ""}`}>
              <span style={{ fontSize: 17, fontWeight: 600 }}>{p.name}</span>
              <span style={{ fontSize: 26, fontWeight: 600 }}>{fmtCredits(p.minutes)}<span className="dim"> / {p.days} วัน</span></span>
              <span className="muted">{fmtBaht(p.price)} · ตกเครดิตละ {fmtBaht(Math.round(p.price / p.minutes))}</span>
              <button type="button" className="btn small" disabled={!payments || !!busy}
                onClick={() => window.confirm(`ซื้อแพ็กเกจ${p.name} ${fmtBaht(p.price)}? เครดิตแพ็กเกจที่เหลือของรอบเดิมจะไม่ทบ`)
                  && run(p.id, () => api.subscribe(p.id), `เริ่มแพ็กเกจ${p.name}แล้ว`)}>
                {busy === p.id ? "กำลังซื้อ..." : p.id === sub?.plan_id ? "ต่ออายุ" : "ซื้อแพ็กเกจนี้"}
              </button>
            </article>
          ))}
        </div>
      </section>

      <section className="card" aria-labelledby="ledger-title">
        <h2 id="ledger-title">ประวัติ</h2>
        {!wallet?.ledger.length ? <div className="empty">ยังไม่มีรายการ</div> : (
          <table className="ledger">
            <thead><tr><th>วันที่</th><th>รายการ</th><th>รายละเอียด</th><th>เครดิต</th><th>ชำระ</th></tr></thead>
            <tbody>
              {wallet.ledger.map((l, i) => {
                const change = l.credits + l.minutes;
                return (
                  <tr key={i}>
                    <td>{fmtDate(l.created_at)}</td>
                    <td>{KIND_LABEL[l.kind] ?? l.kind}</td>
                    <td className="dim">{l.note}</td>
                    <td className="mono" style={{ color: change > 0 ? "var(--success)" : undefined }}>{change ? signed(change) : ""}</td>
                    <td className="mono">{l.amount && PAID.has(l.kind) ? fmtBaht(Math.abs(l.amount)) : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

/** ผู้ดูแล: ดูผู้ใช้ทุกคน เพิ่ม/หักเครดิต และให้แพ็กเกจ (รับโอนนอกระบบ ชดเชย ฯลฯ) */
function AdminSection() {
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
  const shown = (users ?? []).filter((u) => !q || u.email.includes(q) || u.name.toLowerCase().includes(q));
  return (
    <section className="card" aria-labelledby="admin-title">
      <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
        <h2 id="admin-title" style={{ margin: 0 }}>ผู้ใช้ทั้งหมด</h2>
        <input className="input" style={{ maxWidth: 260 }} type="search" placeholder="ค้นหาอีเมลหรือชื่อ"
          aria-label="ค้นหาผู้ใช้" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
      {!users ? <div className="empty">กำลังโหลด...</div> : (
        <table className="ledger admin-users">
          <thead><tr><th>ผู้ใช้</th><th>เครดิต</th><th>แพ็กเกจ</th><th>เพิ่ม / หักเครดิต</th><th>ให้แพ็กเกจ</th></tr></thead>
          <tbody>
            {shown.map((u) => {
              const plan = plans.find((p) => p.id === u.subscription?.plan_id);
              const n = parseInt(amounts[u.id] ?? "", 10);
              return (
                <tr key={u.id}>
                  <td>{u.name}{u.admin ? " · ผู้ดูแล" : ""}<div className="dim">{u.email}</div></td>
                  <td className="mono">{u.credits.toLocaleString()}</td>
                  <td>{u.subscription && plan
                    ? <>{plan.name} · {u.subscription.minutes_left}<div className="dim">ถึง {fmtDate(u.subscription.expires_at)}</div></>
                    : <span className="dim">ไม่มี</span>}</td>
                  <td>
                    <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                      <input className="input" style={{ width: 84 }} type="number" step={1} placeholder="เช่น 30"
                        aria-label={`จำนวนเครดิตของ ${u.email} (ติดลบ = หัก)`}
                        value={amounts[u.id] ?? ""} onChange={(e) => setAmounts({ ...amounts, [u.id]: e.target.value })} />
                      <button type="button" className="btn small" disabled={!!busy || !Number.isFinite(n) || n === 0}
                        onClick={() => window.confirm(`${n > 0 ? "เพิ่ม" : "หัก"} ${fmtCredits(Math.abs(n))} ให้ ${u.email}?`)
                          && run(`c-${u.id}`, async () => { await api.adminCredit(u.id, n); setAmounts({ ...amounts, [u.id]: "" }); },
                            `${n > 0 ? "เพิ่ม" : "หัก"} ${fmtCredits(Math.abs(n))} ให้ ${u.email} แล้ว`)}>
                        {busy === `c-${u.id}` ? "..." : "บันทึก"}
                      </button>
                    </div>
                  </td>
                  <td>
                    <select className="input" style={{ width: 130 }} aria-label={`ให้แพ็กเกจกับ ${u.email}`} value="" disabled={!!busy}
                      onChange={(e) => {
                        const p = plans.find((x) => x.id === e.target.value);
                        if (p && window.confirm(`ให้แพ็กเกจ${p.name} (${fmtCredits(p.minutes)} / ${p.days} วัน) กับ ${u.email} ฟรี? เครดิตแพ็กเกจเดิมจะไม่ทบ`))
                          run(`p-${u.id}`, () => api.adminPlan(u.id, p.id), `ให้แพ็กเกจ${p.name}กับ ${u.email} แล้ว`);
                      }}>
                      <option value="">เลือกแพ็กเกจ</option>
                      {plans.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.minutes}</option>)}
                    </select>
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

export default function AccountPage() {
  const { config, user, loaded } = useAuth();

  useEffect(() => {
    if (loaded && config?.auth && !user) window.location.href = "/welcome?next=/account";
  }, [loaded, config, user]);

  const logout = async () => {
    await api.logout().catch(() => undefined);
    window.location.href = "/login";
  };

  if (!loaded || (config?.auth && !user)) return <main className="page"><div className="empty">กำลังโหลด...</div></main>;
  if (!config?.auth || !user) {
    return (
      <main className="page narrow">
        <div className="card">
          <h2>ระบบบัญชีผู้ใช้ยังไม่เปิดใช้งาน</h2>
          <p className="muted" style={{ margin: 0 }}>ตอนนี้ใช้งานทุกหน้าได้เลยโดยไม่ต้องเข้าสู่ระบบ</p>
        </div>
      </main>
    );
  }

  return (
    <main className="page" style={{ maxWidth: 960 }}>
      <div className="page-head">
        <div>
          <h1>{user.name}</h1>
          <span className="muted">{user.email}{user.admin ? " · ผู้ดูแลระบบ" : ""}</span>
        </div>
        <button type="button" className="btn small" onClick={logout}>ออกจากระบบ</button>
      </div>
      {config.billing ? <WalletSection payments={config.payments} unlimited={user.admin} /> : (
        <div className="card"><span className="muted">เครดิตและแพ็กเกจยังไม่เปิดใช้งาน</span></div>
      )}
      {config.billing && user.admin && <AdminSection />}
    </main>
  );
}
