"use client";

import { useEffect, useState } from "react";
import { api, fileUrl, type AccountType, type AdminUser, type Backups, type Cards, type Plan, type User, type Wallet } from "@/lib/api";
import { fmtBaht, fmtNum } from "@/lib/format";
import { useAuth } from "@/lib/useAuth";

import { locale, tx } from "@/lib/i18n";
const KIND_LABEL: Record<string, string> = {
  topup: "ซื้อเครดิต", subscribe: "ซื้อแพ็กเกจ", charge: "ใช้พากย์", refund: "คืนเครดิต", adjust: "ผู้ดูแลปรับ", bonus: "เครดิตฟรี",
  closed: "ปิดบัญชี",
};
const fmtDate = (unix: number) =>
  new Date(unix * 1000).toLocaleDateString(locale(), { day: "numeric", month: "short", year: "numeric" });
const PAID = new Set(["topup", "subscribe"]); // รายการที่ผู้ใช้จ่ายเงินจริง
const fmtCredits = (n: number) => tx("{0} เครดิต", { 0: fmtNum(n) });
const signed = (n: number) => (n > 0 ? `+${fmtNum(n)}` : `−${fmtNum(Math.abs(n))}`);

type Message = { kind: "error" | "info"; text: string } | null;
const TYPE_LABEL: Record<AccountType, string> = { personal: "บุคคลทั่วไป", creator: "ครีเอเตอร์", business: "บริษัท / หน่วยงาน" };

const fmtDay = (unix: number) => new Date(unix * 1000).toLocaleDateString(locale(), { day: "numeric", month: "short", year: "numeric" });

function ProfileSection({ user: initial }: { user: User }) {
  const [user, setUser] = useState(initial);
  const [saving, setSaving] = useState(false);
  const p = user.profile;
  const toggle = async (fn: () => Promise<User>) => {
    setSaving(true);
    try { setUser(await fn()); } catch { /* คงค่าเดิม */ } finally { setSaving(false); }
  };
  const rows: [string, string][] = [
    [tx("ชื่อ-นามสกุล"), p.full_name], [tx("เบอร์โทร"), p.phone],
    [tx("ประเภทผู้ใช้"), p.account_type ? tx(TYPE_LABEL[p.account_type]) : ""],
    ...(p.account_type === "business" ? [[tx("บริษัท / หน่วยงาน"), p.company] as [string, string]] : []),
    [tx("ใช้พากย์งาน"), p.use_case],
  ];
  return (
    <section className="card" aria-labelledby="profile-title">
      <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
        <h2 id="profile-title" style={{ margin: 0 }}>{tx("ข้อมูลบัญชี")}</h2>
        <a className="btn small" href="/onboarding?next=/account">{user.profile_complete ? tx("แก้ไข") : tx("กรอกข้อมูล")}</a>
      </div>
      <dl className="profile-list">
        {rows.map(([k, v]) => <div key={k}><dt className="dim">{k}</dt><dd>{v || <span className="dim">-</span>}</dd></div>)}
      </dl>
      <div className="row" style={{ gap: 16, fontSize: 14 }}>
        <span className="dim">
          <a href="/terms" target="_blank" rel="noopener">{tx("ข้อกำหนดการใช้งาน")}</a>
          {user.consent.terms && tx(" ยอมรับฉบับ {0} เมื่อ {1}", { 0: user.consent.terms.version, 1: fmtDay(user.consent.terms.at) })}
          {" · "}<a href="/privacy" target="_blank" rel="noopener">{tx("นโยบายความเป็นส่วนตัว")}</a>
          {user.consent.privacy && tx(" ฉบับ {0}", { 0: user.consent.privacy.version })}
        </span>
        <label className="agree" style={{ fontSize: 14 }}>
          <input type="checkbox" checked={user.marketing} disabled={saving} onChange={() => toggle(() => api.setMarketing(!user.marketing))} />{tx("รับข่าวสารและโปรโมชันทางอีเมล")}
        </label>
        <label className="agree" style={{ fontSize: 14 }}>
          <input type="checkbox" checked={user.notify_email} disabled={saving} onChange={() => toggle(() => api.setNotify(!user.notify_email))} />{tx("แจ้งทางอีเมลเมื่องานรอตรวจบท พากย์เสร็จ หรือไม่สำเร็จ")}
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
      setError(e instanceof Error ? e.message : tx("ปิดบัญชีไม่สำเร็จ"));
      setBusy(false);
    }
  };
  return (
    <section className="card" aria-labelledby="mydata-title">
      <h2 id="mydata-title" style={{ margin: 0 }}>{tx("ข้อมูลของฉัน")}</h2>
      <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
        <span className="muted" style={{ fontSize: 14 }}>
          
          {tx("สำเนาข้อมูลบัญชี ความยินยอม ประวัติเครดิต งานพร้อมบทพากย์ และข้อมูลนักพากย์ เป็นไฟล์ JSON (ไฟล์คลิปและเสียงดาวน์โหลดได้จากหน้างานแต่ละงาน)")}
        </span>
        <a className="btn small" href={fileUrl.myData()} download>{tx("ดาวน์โหลดข้อมูลของฉัน")}</a>
      </div>
      {!open ? (
        <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
          <span className="muted" style={{ fontSize: 14 }}>{tx("ปิดบัญชีและลบข้อมูลทั้งหมด")}</span>
          <button type="button" className="btn small danger" onClick={() => setOpen(true)}>{tx("ปิดบัญชี")}</button>
        </div>
      ) : (
        <div className="alert error" role="alert" style={{ display: "grid", gap: 10 }}>
          <strong>{tx("ปิดบัญชีแล้วย้อนกลับไม่ได้")}</strong>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            <li>{tx("ลบงานทุกงาน พร้อมคลิป บทพากย์ และไฟล์ผลลัพธ์")}</li>
            <li>{tx("ลบข้อมูลเบื้องต้น (ชื่อ เบอร์โทร บริษัท) และออกจากระบบทุกเครื่อง")}</li>
            <li>{tx("เครดิตและแพ็กเกจที่เหลือถูกยกเลิก ไม่คืนเป็นเงิน")}</li>
            <li>{tx("ถ้าเป็นนักพากย์: ถอนความยินยอมและลบเสียงทั้งหมดออกจากคลัง")}</li>
            <li>{tx("ประวัติการซื้อและค่าตอบแทนเก็บไว้ตามกฎหมายบัญชีและภาษี โดยไม่มีชื่อ อีเมล หรือเบอร์โทร")}</li>
          </ul>
          <span>{tx("ดาวน์โหลดข้อมูลของฉันไว้ก่อนถ้าต้องการเก็บ พิมพ์")} <b>{user.email}</b>  {tx("เพื่อยืนยัน")}</span>
          <input className="input" value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder={user.email}
            aria-label={tx("พิมพ์อีเมลเพื่อยืนยันการปิดบัญชี")} autoComplete="off" />
          {error && <span>{error}</span>}
          <div className="row" style={{ gap: 10 }}>
            <button type="button" className="btn small danger" onClick={close}
              disabled={busy || confirm.trim().toLowerCase() !== user.email.toLowerCase()}>
              {busy ? tx("กำลังปิดบัญชี...") : tx("ปิดบัญชีและลบข้อมูล")}
            </button>
            <button type="button" className="btn small" onClick={() => { setOpen(false); setConfirm(""); setError(""); }}>{tx("ยกเลิก")}</button>
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
    (r) => (r.bonus ? tx("ผูกบัตรแล้ว ได้เครดิตฟรี {0}", { 0: fmtCredits(r.bonus) }) : tx("ผูกบัตรแล้ว")));
  return (
    <section className="card" aria-labelledby="cards-title">
      <h2 id="cards-title">{tx("บัตรที่ผูกไว้")}</h2>
      {data.bonus_available && (
        <div className="alert info">{tx("ผูกบัตรเครดิตหรือเดบิตครั้งแรก รับฟรี")} {fmtCredits(data.bonus)}  {tx("ยังไม่ตัดเงินตอนผูก")}</div>
      )}
      {data.cards.length > 0 && (
        <ul className="card-list">
          {data.cards.map((c) => (
            <li key={c.id}>
              <span>{c.brand} •••• {c.last4}</span>
              <span className="dim">{tx("หมดอายุ")} {String(c.exp_month).padStart(2, "0")}/{String(c.exp_year).slice(-2)}</span>
              <button type="button" className="btn small" disabled={!!busy}
                onClick={() => window.confirm(tx("ลบบัตร {0} ลงท้าย {1}?", { 0: c.brand, 1: c.last4 }))
                  && run(`rm-${c.id}`, () => api.removeCard(c.id), tx("ลบบัตรแล้ว"))}>
                {busy === `rm-${c.id}` ? "..." : tx("ลบ")}
              </button>
            </li>
          ))}
        </ul>
      )}
      {data.provider === "mock" ? (
        <div className="row" style={{ gap: 8 }}>
          <input className="input" style={{ width: 110 }} inputMode="numeric" maxLength={4} aria-label={tx("เลขท้าย 4 ตัวของบัตรทดสอบ")}
            value={last4} onChange={(e) => setLast4(e.target.value.replace(/\D/g, ""))} />
          <button type="button" className="btn primary small" disabled={!!busy || last4.length !== 4} onClick={add}>
            {busy === "add" ? tx("กำลังผูก...") : tx("ผูกบัตรทดสอบ")}
          </button>
          <span className="dim">{tx("โหมดทดสอบ ไม่มีการตัดเงินจริง")}</span>
        </div>
      ) : !data.provider ? (
        <span className="dim">{tx("ยังไม่ได้เชื่อมช่องทางชำระเงิน ผูกบัตรได้เร็ว ๆ นี้")}</span>
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
        <h2 id="wallet-title">{tx("เครดิต")}</h2>
        <div className="row" style={{ gap: 28, alignItems: "flex-end" }}>
          <div>
            <span className="label">{tx("ใช้ได้ทั้งหมด")}</span>
            <div style={{ fontSize: 30, fontWeight: 600 }}>{unlimited ? tx("ไม่จำกัด") : wallet ? fmtCredits(total) : "..."}</div>
          </div>
          <div>
            <span className="label">{tx("จากแพ็กเกจ")}</span>
            <div style={{ fontSize: 17 }}>
              {sub && current ? tx("{0} · {1} · หมดอายุ {2}", { 0: current.name, 1: fmtCredits(planCredits), 2: fmtDate(sub.expires_at) }) : tx("ยังไม่มีแพ็กเกจ")}
            </div>
          </div>
          <div>
            <span className="label">{tx("เครดิตเติม (ไม่หมดอายุ)")}</span>
            <div style={{ fontSize: 17 }}>{wallet ? fmtCredits(wallet.credits) : "..."}</div>
          </div>
        </div>
        {unlimited && <div className="alert info">{tx("บัญชีผู้ดูแลระบบพากย์ได้ไม่จำกัด ไม่ถูกตัดเครดิต")}</div>}
        <span className="dim">{tx("1 เครดิต = คลิป 1 นาที คิดตามความยาวจริง (คลิป 1:15 นาที = 1.25 เครดิต) ตัดตอนเริ่มวิเคราะห์คลิป ใช้เครดิตแพ็กเกจก่อน แล้วค่อยใช้เครดิตเติม พากย์ซ้ำหรือแก้บทไม่เสียเพิ่ม งานที่วิเคราะห์ไม่สำเร็จได้เครดิตคืน")}</span>
        {wallet && (
          <div className="field">
            <span className="label">{tx("ซื้อเครดิตเติม · เครดิตละ")} {fmtBaht(wallet.credit_price)}</span>
            <div className="row" style={{ gap: 8 }}>
              <div className="seg" role="group" aria-label={tx("จำนวนเครดิตที่จะซื้อ")}>
                {packs.map((n) => (
                  <button key={n} type="button" aria-pressed={pack === n} onClick={() => setPack(n)}>{n.toLocaleString()}</button>
                ))}
              </div>
              <button type="button" className="btn primary small" disabled={!payments || !!busy}
                onClick={() => run("topup", () => api.buyCredits(pack), tx("ได้ {0} แล้ว", { 0: fmtCredits(pack) }))}>
                {busy === "topup" ? tx("กำลังซื้อ...") : tx("ซื้อ {0}", { 0: fmtBaht(pack * wallet.credit_price) })}
              </button>
            </div>
            {!payments && <span className="dim">{tx("ยังไม่ได้เชื่อมช่องทางชำระเงิน ติดต่อผู้ดูแลเพื่อเติมเครดิต")}</span>}
          </div>
        )}
        {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
      </section>

      {!unlimited && <CardsSection onChange={load} />}

      <section aria-labelledby="plans-title" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 id="plans-title" style={{ margin: 0, fontSize: 17, fontWeight: 500 }}>{tx("แพ็กเกจรายเดือน")}</h2>
        <div className="plans">
          {plans.map((p) => (
            <article key={p.id} className={`card plan${p.id === sub?.plan_id ? " current" : ""}`}>
              <span style={{ fontSize: 17, fontWeight: 600 }}>{p.name}</span>
              <span style={{ fontSize: 26, fontWeight: 600 }}>{fmtCredits(p.minutes)}<span className="dim"> / {p.days}  {tx("วัน")}</span></span>
              <span className="muted">{fmtBaht(p.price)}  {tx("· ตกเครดิตละ")} {fmtBaht(Math.round(p.price / p.minutes))}</span>
              <button type="button" className="btn small" disabled={!payments || !!busy}
                onClick={() => window.confirm(tx("ซื้อแพ็กเกจ{0} {1}? เครดิตแพ็กเกจที่เหลือของรอบเดิมจะไม่ทบ", { 0: p.name, 1: fmtBaht(p.price) }))
                  && run(p.id, () => api.subscribe(p.id), tx("เริ่มแพ็กเกจ{0}แล้ว", { 0: p.name }))}>
                {busy === p.id ? tx("กำลังซื้อ...") : p.id === sub?.plan_id ? tx("ต่ออายุ") : tx("ซื้อแพ็กเกจนี้")}
              </button>
            </article>
          ))}
        </div>
      </section>

      <section className="card" aria-labelledby="ledger-title">
        <h2 id="ledger-title">{tx("ประวัติ")}</h2>
        {!wallet?.ledger.length ? <div className="empty">{tx("ยังไม่มีรายการ")}</div> : (
          <table className="ledger">
            <thead><tr><th>{tx("วันที่")}</th><th>{tx("รายการ")}</th><th>{tx("รายละเอียด")}</th><th>{tx("เครดิต")}</th><th>{tx("ชำระ")}</th></tr></thead>
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
        <h2 id="admin-title" style={{ margin: 0 }}>{tx("ผู้ใช้ทั้งหมด")}</h2>
        <input className="input" style={{ maxWidth: 260 }} type="search" placeholder={tx("ค้นหาอีเมล ชื่อ เบอร์ บริษัท")}
          aria-label={tx("ค้นหาผู้ใช้")} value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      {message && <div className={`alert ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</div>}
      {!users ? <div className="empty">{tx("กำลังโหลด...")}</div> : (
        <table className="ledger admin-users">
          <thead><tr><th>{tx("ผู้ใช้")}</th><th>{tx("เครดิต")}</th><th>{tx("แพ็กเกจ")}</th><th>{tx("เพิ่ม / หักเครดิต")}</th><th>{tx("ให้แพ็กเกจ")}</th><th>{tx("ผู้ดูแล")}</th></tr></thead>
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
                  <td className="mono">{fmtNum(u.credits)}</td>
                  <td>{u.subscription && plan
                    ? <>{plan.name} · {fmtNum(u.subscription.minutes_left)}<div className="dim">{tx("ถึง")} {fmtDate(u.subscription.expires_at)}</div></>
                    : <span className="dim">{tx("ไม่มี")}</span>}</td>
                  <td>
                    <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                      <input className="input" style={{ width: 84 }} type="number" step={0.01} placeholder={tx("เช่น 30")}
                        aria-label={tx("จำนวนเครดิตของ {0} (ติดลบ = หัก)", { 0: u.email })}
                        value={amounts[u.id] ?? ""} onChange={(e) => setAmounts({ ...amounts, [u.id]: e.target.value })} />
                      <button type="button" className="btn small" disabled={!!busy || !Number.isFinite(n) || n === 0}
                        onClick={() => window.confirm(tx("{0} {1} ให้ {2}?", { 0: n > 0 ? "เพิ่ม" : "หัก", 1: fmtCredits(Math.abs(n)), 2: u.email }))
                          && run(`c-${u.id}`, async () => { await api.adminCredit(u.id, n); setAmounts({ ...amounts, [u.id]: "" }); },
                            tx("{0} {1} ให้ {2} แล้ว", { 0: n > 0 ? "เพิ่ม" : "หัก", 1: fmtCredits(Math.abs(n)), 2: u.email }))}>
                        {busy === `c-${u.id}` ? "..." : tx("บันทึก")}
                      </button>
                    </div>
                  </td>
                  <td>
                    <select className="input" style={{ width: 130 }} aria-label={tx("ให้แพ็กเกจกับ {0}", { 0: u.email })} value="" disabled={!!busy}
                      onChange={(e) => {
                        const p = plans.find((x) => x.id === e.target.value);
                        if (p && window.confirm(tx("ให้แพ็กเกจ{0} ({1} / {2} วัน) กับ {3} ฟรี? เครดิตแพ็กเกจเดิมจะไม่ทบ", { 0: p.name, 1: fmtCredits(p.minutes), 2: p.days, 3: u.email })))
                          run(`p-${u.id}`, () => api.adminPlan(u.id, p.id), tx("ให้แพ็กเกจ{0}กับ {1} แล้ว", { 0: p.name, 1: u.email }));
                      }}>
                      <option value="">{tx("เลือกแพ็กเกจ")}</option>
                      {plans.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.minutes}</option>)}
                    </select>
                  </td>
                  <td>
                    {u.owner ? <span className="dim">{tx("ผู้ดูแลหลัก")}</span> : u.id === me ? <span className="dim">{tx("คุณ")}</span> : (
                      <button type="button" className="btn small" disabled={!!busy}
                        onClick={() => window.confirm(u.admin
                          ? tx("ถอดสิทธิ์ผู้ดูแลของ {0}?", { 0: u.email })
                          : tx("ให้ {0} เป็นผู้ดูแล? จะพากย์ได้ไม่จำกัด แก้คลังเสียง ค่าตั้งระบบ และสิทธิ์ของผู้ใช้คนอื่นได้", { 0: u.email }))
                          && run(`a-${u.id}`, () => api.adminSetAdmin(u.id, !u.admin),
                            tx("{0} {1} แล้ว", { 0: u.admin ? "ถอดสิทธิ์ผู้ดูแลของ" : "ให้สิทธิ์ผู้ดูแลกับ", 1: u.email }))}>
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

export default function AccountPage() {
  const { config, user, loaded } = useAuth();

  useEffect(() => {
    if (loaded && config?.auth && !user) window.location.href = "/welcome?next=/account";
  }, [loaded, config, user]);

  const logout = async () => {
    await api.logout().catch(() => undefined);
    window.location.href = "/login";
  };

  if (!loaded || (config?.auth && !user)) return <main className="page"><div className="empty">{tx("กำลังโหลด...")}</div></main>;
  if (!config?.auth || !user) {
    return (
      <main className="page narrow">
        <div className="card">
          <h2>{tx("ระบบบัญชีผู้ใช้ยังไม่เปิดใช้งาน")}</h2>
          <p className="muted" style={{ margin: 0 }}>{tx("ตอนนี้ใช้งานทุกหน้าได้เลยโดยไม่ต้องเข้าสู่ระบบ")}</p>
        </div>
      </main>
    );
  }

  return (
    <main className="page" style={{ maxWidth: 960 }}>
      <div className="page-head">
        <div>
          <h1>{user.name}</h1>
          <span className="muted">{user.email}{user.admin ? tx(" · ผู้ดูแลระบบ") : ""}</span>
        </div>
        <button type="button" className="btn small" onClick={logout}>{tx("ออกจากระบบ")}</button>
      </div>
      <ProfileSection user={user} />
      {config.billing ? <WalletSection payments={config.payments} unlimited={user.admin} /> : (
        <div className="card"><span className="muted">{tx("เครดิตและแพ็กเกจยังไม่เปิดใช้งาน")}</span></div>
      )}
      {config.billing && user.admin && <AdminSection me={user.id} />}
      {user.admin && <BackupSection />}
      <MyDataSection user={user} />
    </main>
  );
}
