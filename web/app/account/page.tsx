"use client";

import { useEffect, useState } from "react";
import { api, type Plan, type Wallet } from "@/lib/api";
import { fmtBaht } from "@/lib/format";
import { useAuth } from "@/lib/useAuth";

const TOPUP_PRESETS = [100, 300, 500, 1000]; // บาท
const KIND_LABEL: Record<string, string> = {
  topup: "เติมเงิน", subscribe: "ซื้อแพ็กเกจ", charge: "ใช้พากย์", refund: "คืนนาที", adjust: "ปรับยอด",
};
const fmtDate = (unix: number) =>
  new Date(unix * 1000).toLocaleDateString("th-TH", { day: "numeric", month: "short", year: "numeric" });

function WalletSection({ payments }: { payments: boolean }) {
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [amount, setAmount] = useState(300);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState<{ kind: "error" | "info"; text: string } | null>(null);

  const load = () => {
    api.wallet().then(setWallet).catch((e) => setMessage({ kind: "error", text: e.message }));
    api.plans().then((p) => setPlans(p.plans)).catch(() => setPlans([]));
  };
  useEffect(load, []);

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

  const sub = wallet?.subscription;
  const current = plans.find((p) => p.id === sub?.plan_id);
  return (
    <>
      <section className="card" aria-labelledby="wallet-title">
        <h2 id="wallet-title">กระเป๋าเงิน</h2>
        <div className="row" style={{ gap: 28, alignItems: "flex-end" }}>
          <div>
            <span className="label">ยอดคงเหลือ</span>
            <div style={{ fontSize: 30, fontWeight: 600 }}>{wallet ? fmtBaht(wallet.balance) : "..."}</div>
          </div>
          <div>
            <span className="label">แพ็กเกจ</span>
            <div style={{ fontSize: 17 }}>
              {sub && current ? `${current.name} · เหลือ ${sub.minutes_left} นาที · ถึง ${fmtDate(sub.expires_at)}` : "ยังไม่มีแพ็กเกจ"}
            </div>
          </div>
        </div>
        {wallet && (
          <span className="dim">ใช้นาทีในแพ็กเกจก่อน หมดแล้วหักจากกระเป๋านาทีละ {fmtBaht(wallet.payg_per_minute)} ตัดตอนเริ่มวิเคราะห์คลิป
            ปัดขึ้นเป็นนาที พากย์ซ้ำหรือแก้บทไม่เสียเพิ่ม งานที่วิเคราะห์ไม่สำเร็จได้นาทีคืน</span>
        )}
        <div className="field">
          <span className="label">เติมเงิน</span>
          <div className="row" style={{ gap: 8 }}>
            <div className="seg" role="group" aria-label="จำนวนเงินที่จะเติม">
              {TOPUP_PRESETS.map((b) => (
                <button key={b} type="button" aria-pressed={amount === b} onClick={() => setAmount(b)}>{b.toLocaleString()} บาท</button>
              ))}
            </div>
            <button type="button" className="btn primary small" disabled={!payments || !!busy}
              onClick={() => run("topup", () => api.topup(amount * 100), `เติมเงิน ${amount.toLocaleString()} บาทแล้ว`)}>
              {busy === "topup" ? "กำลังเติม..." : "เติมเงิน"}
            </button>
          </div>
          {!payments && <span className="dim">ยังไม่ได้เชื่อมช่องทางชำระเงิน</span>}
        </div>
        {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
      </section>

      <section aria-labelledby="plans-title" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 id="plans-title" style={{ margin: 0, fontSize: 17, fontWeight: 500 }}>แพ็กเกจรายเดือน</h2>
        <div className="plans">
          {plans.map((p) => (
            <article key={p.id} className={`card plan${p.id === sub?.plan_id ? " current" : ""}`}>
              <span style={{ fontSize: 17, fontWeight: 600 }}>{p.name}</span>
              <span style={{ fontSize: 26, fontWeight: 600 }}>{fmtBaht(p.price)}<span className="dim"> / {p.days} วัน</span></span>
              <span className="muted">พากย์ได้ {p.minutes} นาที · ตกนาทีละ {fmtBaht(Math.round(p.price / p.minutes))}</span>
              <button type="button" className="btn small" disabled={!!busy || !wallet || wallet.balance < p.price}
                onClick={() => window.confirm(`ซื้อแพ็กเกจ${p.name} ${fmtBaht(p.price)} จากเงินในกระเป๋า? นาทีที่เหลือของแพ็กเกจเดิมจะไม่ทบ`)
                  && run(p.id, () => api.subscribe(p.id), `ซื้อแพ็กเกจ${p.name}แล้ว`)}>
                {busy === p.id ? "กำลังซื้อ..." : p.id === sub?.plan_id ? "ต่ออายุ" : "ซื้อแพ็กเกจนี้"}
              </button>
              {wallet && wallet.balance < p.price && <span className="dim">เติมเงินอีก {fmtBaht(p.price - wallet.balance)}</span>}
            </article>
          ))}
        </div>
      </section>

      <section className="card" aria-labelledby="ledger-title">
        <h2 id="ledger-title">ประวัติ</h2>
        {!wallet?.ledger.length ? <div className="empty">ยังไม่มีรายการ</div> : (
          <table className="ledger">
            <thead><tr><th>วันที่</th><th>รายการ</th><th>รายละเอียด</th><th>นาที</th><th>เงิน</th></tr></thead>
            <tbody>
              {wallet.ledger.map((l, i) => (
                <tr key={i}>
                  <td>{fmtDate(l.created_at)}</td>
                  <td>{KIND_LABEL[l.kind] ?? l.kind}</td>
                  <td className="dim">{l.note}</td>
                  <td className="mono">{l.minutes ? (l.minutes > 0 ? `+${l.minutes}` : l.minutes) : ""}</td>
                  <td className="mono" style={{ color: l.amount > 0 ? "var(--success)" : undefined }}>
                    {l.amount ? `${l.amount > 0 ? "+" : "−"}${fmtBaht(Math.abs(l.amount))}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

function PasswordSection() {
  const [old, setOld] = useState("");
  const [next, setNext] = useState("");
  const [message, setMessage] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.changePassword(old, next);
      setOld(""); setNext("");
      setMessage({ kind: "info", text: "เปลี่ยนรหัสผ่านแล้ว" });
    } catch (err) {
      setMessage({ kind: "error", text: (err as Error).message });
    }
  };
  return (
    <form className="card" onSubmit={submit} aria-labelledby="pw-title">
      <h2 id="pw-title">เปลี่ยนรหัสผ่าน</h2>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="pw-old">รหัสผ่านเดิม</label>
          <input id="pw-old" className="input" type="password" required autoComplete="current-password" value={old} onChange={(e) => setOld(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="pw-new">รหัสผ่านใหม่</label>
          <input id="pw-new" className="input" type="password" required minLength={8} autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </div>
      </div>
      {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
      <button type="submit" className="btn small" style={{ alignSelf: "flex-start" }}>เปลี่ยนรหัสผ่าน</button>
    </form>
  );
}

export default function AccountPage() {
  const { config, user, loaded } = useAuth();

  useEffect(() => {
    if (loaded && config?.auth && !user) window.location.href = "/login?next=/account";
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
      {config.billing ? <WalletSection payments={config.payments} /> : (
        <div className="card"><span className="muted">กระเป๋าเงินและแพ็กเกจยังไม่เปิดใช้งาน</span></div>
      )}
      <PasswordSection />
    </main>
  );
}
