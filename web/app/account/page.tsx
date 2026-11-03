"use client";

import { useEffect, useState } from "react";
import { api, fileUrl, type AccountType, type AdminUser, type Backups, type Cards, type Plan, type User, type Wallet } from "@/lib/api";
import { fmtBaht, fmtNum } from "@/lib/format";
import { useAuth } from "@/lib/useAuth";

const KIND_LABEL: Record<string, string> = {
  topup: "ซื้อเครดิต", subscribe: "ซื้อแพ็กเกจ", charge: "ใช้พากย์", refund: "คืนเครดิต", adjust: "ผู้ดูแลปรับ", bonus: "เครดิตฟรี",
  closed: "ปิดบัญชี",
};
const fmtDate = (unix: number) =>
  new Date(unix * 1000).toLocaleDateString("th-TH", { day: "numeric", month: "short", year: "numeric" });
const PAID = new Set(["topup", "subscribe"]); // รายการที่ผู้ใช้จ่ายเงินจริง
const fmtCredits = (n: number) => `${fmtNum(n)} เครดิต`;
const signed = (n: number) => (n > 0 ? `+${fmtNum(n)}` : `−${fmtNum(Math.abs(n))}`);

type Message = { kind: "error" | "info"; text: string } | null;
const TYPE_LABEL: Record<AccountType, string> = { personal: "บุคคลทั่วไป", creator: "ครีเอเตอร์", business: "บริษัท / หน่วยงาน" };

const fmtDay = (unix: number) => new Date(unix * 1000).toLocaleDateString("th-TH", { day: "numeric", month: "short", year: "numeric" });

function ProfileSection({ user: initial }: { user: User }) {
  const [user, setUser] = useState(initial);
  const [saving, setSaving] = useState(false);
  const p = user.profile;
  const toggle = async (fn: () => Promise<User>) => {
    setSaving(true);
    try { setUser(await fn()); } catch { /* คงค่าเดิม */ } finally { setSaving(false); }
  };
  const rows: [string, string][] = [
    ["ชื่อ-นามสกุล", p.full_name], ["เบอร์โทร", p.phone],
    ["ประเภทผู้ใช้", p.account_type ? TYPE_LABEL[p.account_type] : ""],
    ...(p.account_type === "business" ? [["บริษัท / หน่วยงาน", p.company] as [string, string]] : []),
    ["ใช้พากย์งาน", p.use_case],
  ];
  return (
    <section className="card" aria-labelledby="profile-title">
      <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
        <h2 id="profile-title" style={{ margin: 0 }}>ข้อมูลบัญชี</h2>
        <a className="btn small" href="/onboarding?next=/account">{user.profile_complete ? "แก้ไข" : "กรอกข้อมูล"}</a>
      </div>
      <dl className="profile-list">
        {rows.map(([k, v]) => <div key={k}><dt className="dim">{k}</dt><dd>{v || <span className="dim">-</span>}</dd></div>)}
      </dl>
      <div className="row" style={{ gap: 16, fontSize: 14 }}>
        <span className="dim">
          <a href="/terms" target="_blank" rel="noopener">ข้อกำหนดการใช้งาน</a>
          {user.consent.terms && ` ยอมรับฉบับ ${user.consent.terms.version} เมื่อ ${fmtDay(user.consent.terms.at)}`}
          {" · "}<a href="/privacy" target="_blank" rel="noopener">นโยบายความเป็นส่วนตัว</a>
          {user.consent.privacy && ` ฉบับ ${user.consent.privacy.version}`}
        </span>
        <label className="agree" style={{ fontSize: 14 }}>
          <input type="checkbox" checked={user.marketing} disabled={saving} onChange={() => toggle(() => api.setMarketing(!user.marketing))} />รับข่าวสารและโปรโมชันทางอีเมล
        </label>
        <label className="agree" style={{ fontSize: 14 }}>
          <input type="checkbox" checked={user.notify_email} disabled={saving} onChange={() => toggle(() => api.setNotify(!user.notify_email))} />แจ้งทางอีเมลเมื่องานรอตรวจบท พากย์เสร็จ หรือไม่สำเร็จ
        </label>
      </div>
    </section>
  );
}

/** สิทธิ์ตาม PDPA: ดาวน์โหลดสำเนาข้อมูล และปิดบัญชีพร้อมลบข้อมูล */
function MyDataSection({ user }: { user: User }) {
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const close = async () => {
    setBusy(true); setError("");
    try {
      await api.closeAccount(confirm);
      window.location.href = "/welcome";
    } catch (e) {
      setError(e instanceof Error ? e.message : "ปิดบัญชีไม่สำเร็จ");
      setBusy(false);
    }
  };
  return (
    <section className="card" aria-labelledby="mydata-title">
      <h2 id="mydata-title" style={{ margin: 0 }}>ข้อมูลของฉัน</h2>
      <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
        <span className="muted" style={{ fontSize: 14 }}>
          สำเนาข้อมูลบัญชี ความยินยอม ประวัติเครดิต งานพร้อมบทพากย์ และข้อมูลนักพากย์ เป็นไฟล์ JSON
          (ไฟล์คลิปและเสียงดาวน์โหลดได้จากหน้างานแต่ละงาน)
        </span>
        <a className="btn small" href={fileUrl.myData()} download>ดาวน์โหลดข้อมูลของฉัน</a>
      </div>
      {!open ? (
        <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
          <span className="muted" style={{ fontSize: 14 }}>ปิดบัญชีและลบข้อมูลทั้งหมด</span>
          <button type="button" className="btn small danger" onClick={() => setOpen(true)}>ปิดบัญชี</button>
        </div>
      ) : (
        <div className="alert error" role="alert" style={{ display: "grid", gap: 10 }}>
          <strong>ปิดบัญชีแล้วย้อนกลับไม่ได้</strong>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            <li>ลบงานทุกงาน พร้อมคลิป บทพากย์ และไฟล์ผลลัพธ์</li>
            <li>ลบข้อมูลเบื้องต้น (ชื่อ เบอร์โทร บริษัท) และออกจากระบบทุกเครื่อง</li>
            <li>เครดิตและแพ็กเกจที่เหลือถูกยกเลิก ไม่คืนเป็นเงิน</li>
            <li>ถ้าเป็นนักพากย์: ถอนความยินยอมและลบเสียงทั้งหมดออกจากคลัง</li>
            <li>ประวัติการซื้อและค่าตอบแทนเก็บไว้ตามกฎหมายบัญชีและภาษี โดยไม่มีชื่อ อีเมล หรือเบอร์โทร</li>
          </ul>
          <span>ดาวน์โหลดข้อมูลของฉันไว้ก่อนถ้าต้องการเก็บ พิมพ์ <b>{user.email}</b> เพื่อยืนยัน</span>
          <input className="input" value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder={user.email}
            aria-label="พิมพ์อีเมลเพื่อยืนยันการปิดบัญชี" autoComplete="off" />
          {error && <span>{error}</span>}
          <div className="row" style={{ gap: 10 }}>
            <button type="button" className="btn small danger" onClick={close}
              disabled={busy || confirm.trim().toLowerCase() !== user.email.toLowerCase()}>
              {busy ? "กำลังปิดบัญชี..." : "ปิดบัญชีและลบข้อมูล"}
            </button>
            <button type="button" className="btn small" onClick={() => { setOpen(false); setConfirm(""); setError(""); }}>ยกเลิก</button>
          </div>
        </div>
      )}
    </section>
  );
}

/** ผู้ดูแล: ไฟล์สำรองข้อมูลอัตโนมัติ และปุ่มสำรองทันที */
function BackupSection() {
  const [data, setData] = useState<Backups | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = () => api.backups().then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  const now = async () => {
    setBusy(true); setError("");
    try { await api.backupNow(); await load(); } catch (e) { setError(e instanceof Error ? e.message : "สำรองไม่สำเร็จ"); }
    finally { setBusy(false); }
  };
  const last = data?.backups[0];
  return (
    <section className="card" aria-labelledby="backup-title">
      <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
        <h2 id="backup-title" style={{ margin: 0 }}>สำรองข้อมูล</h2>
        <button type="button" className="btn small" onClick={now} disabled={busy}>{busy ? "กำลังสำรอง..." : "สำรองทันที"}</button>
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {data && (
        <span className="muted" style={{ fontSize: 14 }}>
          {data.hours > 0 ? `สำรองอัตโนมัติทุก ${data.hours} ชั่วโมง เก็บ ${data.keep} ชุดล่าสุด` : "ปิดการสำรองอัตโนมัติอยู่ (BACKUP_HOURS=0)"}
          {" · "}{last ? `ล่าสุด ${new Date(last.created_at * 1000).toLocaleString("th-TH")} (${(last.bytes / 1e6).toFixed(1)} MB) ทั้งหมด ${data.backups.length} ชุด` : "ยังไม่มีไฟล์สำรอง"}
        </span>
      )}
    </section>
  );
}

function useRunner(load: () => void) {
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState<Message>(null);
  /** done: ข้อความเมื่อสำเร็จ หรือฟังก์ชันสร้างข้อความจากผลลัพธ์ */
  const run = async <T,>(key: string, fn: () => Promise<T>, done: string | ((r: T) => string)) => {
    setBusy(key);
    setMessage(null);
    try {
      const r = await fn();
      load();
      setMessage({ kind: "info", text: typeof done === "string" ? done : done(r) });
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally { setBusy(""); }
  };
  return { busy, message, setMessage, run };
}

/** บัตรที่ผูกไว้ ผูกบัตรครั้งแรกได้เครดิตฟรี ตอนนี้มีแค่ผู้ให้บริการจำลอง (PAYMENT_PROVIDER=mock)
 * ต่อผู้ให้บริการจริงเมื่อไหร่ ฟอร์มนี้เปลี่ยนเป็นสคริปต์เก็บบัตรของผู้ให้บริการ (ได้ token มา ไม่ส่งเลขบัตรให้เซิร์ฟเวอร์เรา) */
function CardsSection({ onChange }: { onChange: () => void }) {
  const [data, setData] = useState<Cards | null>(null);
  const [last4, setLast4] = useState("4242");
  const load = () => {
    api.cards().then(setData).catch((e) => setMessage({ kind: "error", text: e.message }));
    onChange();
  };
  const { busy, message, setMessage, run } = useRunner(load);
  useEffect(() => { api.cards().then(setData).catch(() => setData(null)); }, []);

  if (!data) return null;
  const add = () => run("add", () => api.addCard(`tok_mock_${last4}`),
    (r) => (r.bonus ? `ผูกบัตรแล้ว ได้เครดิตฟรี ${fmtCredits(r.bonus)}` : "ผูกบัตรแล้ว"));
  return (
    <section className="card" aria-labelledby="cards-title">
      <h2 id="cards-title">บัตรที่ผูกไว้</h2>
      {data.bonus_available && (
        <div className="alert info">ผูกบัตรเครดิตหรือเดบิตครั้งแรก รับฟรี {fmtCredits(data.bonus)} ยังไม่ตัดเงินตอนผูก</div>
      )}
      {data.cards.length > 0 && (
        <ul className="card-list">
          {data.cards.map((c) => (
            <li key={c.id}>
              <span>{c.brand} •••• {c.last4}</span>
              <span className="dim">หมดอายุ {String(c.exp_month).padStart(2, "0")}/{String(c.exp_year).slice(-2)}</span>
              <button type="button" className="btn small" disabled={!!busy}
                onClick={() => window.confirm(`ลบบัตร ${c.brand} ลงท้าย ${c.last4}?`)
                  && run(`rm-${c.id}`, () => api.removeCard(c.id), "ลบบัตรแล้ว")}>
                {busy === `rm-${c.id}` ? "..." : "ลบ"}
              </button>
            </li>
          ))}
        </ul>
      )}
      {data.provider === "mock" ? (
        <div className="row" style={{ gap: 8 }}>
          <input className="input" style={{ width: 110 }} inputMode="numeric" maxLength={4} aria-label="เลขท้าย 4 ตัวของบัตรทดสอบ"
            value={last4} onChange={(e) => setLast4(e.target.value.replace(/\D/g, ""))} />
          <button type="button" className="btn primary small" disabled={!!busy || last4.length !== 4} onClick={add}>
            {busy === "add" ? "กำลังผูก..." : "ผูกบัตรทดสอบ"}
          </button>
          <span className="dim">โหมดทดสอบ ไม่มีการตัดเงินจริง</span>
        </div>
      ) : !data.provider ? (
        <span className="dim">ยังไม่ได้เชื่อมช่องทางชำระเงิน ผูกบัตรได้เร็ว ๆ นี้</span>
      ) : null}
      {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
    </section>
  );
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
        <span className="dim">1 เครดิต = คลิป 1 นาที คิดตามความยาวจริง (คลิป 1:15 นาที = 1.25 เครดิต) ตัดตอนเริ่มวิเคราะห์คลิป ใช้เครดิตแพ็กเกจก่อน แล้วค่อยใช้เครดิตเติม
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

      {!unlimited && <CardsSection onChange={load} />}

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
function AdminSection({ me }: { me: string }) {
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
        <h2 id="admin-title" style={{ margin: 0 }}>ผู้ใช้ทั้งหมด</h2>
        <input className="input" style={{ maxWidth: 260 }} type="search" placeholder="ค้นหาอีเมล ชื่อ เบอร์ บริษัท"
          aria-label="ค้นหาผู้ใช้" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
      {!users ? <div className="empty">กำลังโหลด...</div> : (
        <table className="ledger admin-users">
          <thead><tr><th>ผู้ใช้</th><th>เครดิต</th><th>แพ็กเกจ</th><th>เพิ่ม / หักเครดิต</th><th>ให้แพ็กเกจ</th><th>ผู้ดูแล</th></tr></thead>
          <tbody>
            {shown.map((u) => {
              const plan = plans.find((p) => p.id === u.subscription?.plan_id);
              const n = Math.round(parseFloat(amounts[u.id] ?? "") * 100) / 100;
              return (
                <tr key={u.id}>
                  <td>{u.name}{u.admin ? " · ผู้ดูแล" : ""}<div className="dim">{u.email}</div>
                    {u.profile_complete ? (
                      <div className="dim">{u.profile.full_name} · {u.profile.phone}
                        {u.profile.account_type && ` · ${TYPE_LABEL[u.profile.account_type]}`}{u.profile.company && ` (${u.profile.company})`}</div>
                    ) : <div className="dim">ยังไม่กรอกข้อมูล</div>}
                    {!u.consent_current && <div className="dim">ยังไม่ยอมรับข้อกำหนดฉบับปัจจุบัน</div>}
                  </td>
                  <td className="mono">{fmtNum(u.credits)}</td>
                  <td>{u.subscription && plan
                    ? <>{plan.name} · {fmtNum(u.subscription.minutes_left)}<div className="dim">ถึง {fmtDate(u.subscription.expires_at)}</div></>
                    : <span className="dim">ไม่มี</span>}</td>
                  <td>
                    <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                      <input className="input" style={{ width: 84 }} type="number" step={0.01} placeholder="เช่น 30"
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
                  <td>
                    {u.owner ? <span className="dim">ผู้ดูแลหลัก</span> : u.id === me ? <span className="dim">คุณ</span> : (
                      <button type="button" className="btn small" disabled={!!busy}
                        onClick={() => window.confirm(u.admin
                          ? `ถอดสิทธิ์ผู้ดูแลของ ${u.email}?`
                          : `ให้ ${u.email} เป็นผู้ดูแล? จะพากย์ได้ไม่จำกัด แก้คลังเสียง ค่าตั้งระบบ และสิทธิ์ของผู้ใช้คนอื่นได้`)
                          && run(`a-${u.id}`, () => api.adminSetAdmin(u.id, !u.admin),
                            `${u.admin ? "ถอดสิทธิ์ผู้ดูแลของ" : "ให้สิทธิ์ผู้ดูแลกับ"} ${u.email} แล้ว`)}>
                        {busy === `a-${u.id}` ? "..." : u.admin ? "ถอดสิทธิ์" : "ให้สิทธิ์"}
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
      <ProfileSection user={user} />
      {config.billing ? <WalletSection payments={config.payments} unlimited={user.admin} /> : (
        <div className="card"><span className="muted">เครดิตและแพ็กเกจยังไม่เปิดใช้งาน</span></div>
      )}
      {config.billing && user.admin && <AdminSection me={user.id} />}
      {user.admin && <BackupSection />}
      <MyDataSection user={user} />
    </main>
  );
}
