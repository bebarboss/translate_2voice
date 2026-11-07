"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ActorPaymentSection from "@/components/ActorPaymentSection";
import { fmtCredits, fmtDate, useWallet } from "@/components/Billing";
import { GearIcon, MicIcon, ShieldIcon, TagIcon, UserIcon } from "@/components/Icons";
import { api, fileUrl, type AccountType, type ActorMe, type User } from "@/lib/api";
import { fmtBaht, fmtNum } from "@/lib/format";
import { chooseLang, chooseTheme, currentTheme, getLang, locale, tx, type Lang, type Theme } from "@/lib/i18n";
import { useAuth } from "@/lib/useAuth";

const KIND_LABEL: Record<string, string> = {
  topup: "ซื้อเครดิต", subscribe: "ซื้อแพ็กเกจ", charge: "ใช้พากย์", refund: "คืนเครดิต", adjust: "ผู้ดูแลปรับ", bonus: "เครดิตฟรี",
  closed: "ปิดบัญชี",
};
const PAID = new Set(["topup", "subscribe"]); // รายการที่ผู้ใช้จ่ายเงินจริง
const signed = (n: number) => (n > 0 ? `+${fmtNum(n)}` : `−${fmtNum(Math.abs(n))}`);
const TYPE_LABEL: Record<AccountType, string> = { personal: "บุคคลทั่วไป", creator: "ครีเอเตอร์", business: "บริษัท / หน่วยงาน" };
const fmtDay = (unix: number) => new Date(unix * 1000).toLocaleDateString(locale(), { day: "numeric", month: "short", year: "numeric" });

type Tab = "profile" | "prefs" | "credits" | "payout" | "privacy";
const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "profile", label: "โปรไฟล์", icon: <UserIcon size={16} /> },
  { id: "prefs", label: "การตั้งค่า", icon: <GearIcon size={16} /> },
  { id: "credits", label: "เครดิต", icon: <TagIcon size={16} /> },
  { id: "payout", label: "รับเงินนักพากย์", icon: <MicIcon size={16} /> },
  { id: "privacy", label: "ข้อมูลและความเป็นส่วนตัว", icon: <ShieldIcon size={16} /> },
];

/** หัวข้อของกลุ่มแถว */
const Head = ({ title, text }: { title: string; text?: string }) => (
  <div className="set-head"><h2>{title}</h2>{text && <p>{text}</p>}</div>
);
/** แถวหนึ่งแถว: หัวข้อและคำอธิบายซ้าย ค่าหรือปุ่มขวา */
const Row = ({ title, desc, children }: { title: string; desc?: string; children?: React.ReactNode }) => (
  <div className="set-row">
    <div><b>{title}</b>{desc && <span className="d">{desc}</span>}</div>
    <div className="v">{children}</div>
  </div>
);

function ProfileTab({ user }: { user: User }) {
  const p = user.profile;
  const edit = <Link href="/onboarding?next=/account" className="btn small">{user.profile_complete ? tx("แก้ไข") : tx("กรอกข้อมูล")}</Link>;
  return (
    <>
      <Head title={tx("โปรไฟล์")} text={tx("ข้อมูลที่ใช้ติดต่อเรื่องบัญชีและการชำระเงิน")} />
      <div className="set-group">
        <Row title={tx("ข้อมูลเบื้องต้น")} desc={tx("ชื่อ เบอร์โทร ประเภทผู้ใช้ และงานที่พากย์")}>{edit}</Row>
        <Row title={tx("ชื่อที่แสดง")}>{user.name}</Row>
        <Row title={tx("ชื่อ-นามสกุล")}>{p.full_name || "-"}</Row>
        <Row title={tx("เบอร์โทร")}>{p.phone || "-"}</Row>
        <Row title={tx("ประเภทผู้ใช้")}>{p.account_type ? tx(TYPE_LABEL[p.account_type]) : "-"}{p.account_type === "business" && p.company ? ` · ${p.company}` : ""}</Row>
        <Row title={tx("ใช้พากย์งาน")}>{p.use_case || "-"}</Row>
      </div>
      <Head title={tx("การเข้าสู่ระบบ")} />
      <div className="set-group">
        <Row title={tx("อีเมล")} desc={tx("อีเมลของบัญชี ใช้รับแจ้งเตือน")}>{user.email}</Row>
        <Row title={tx("วิธีเข้าสู่ระบบ")} desc={tx("บัญชีที่เชื่อมไว้สำหรับเข้าสู่ระบบ")}>Google</Row>
        <Row title={tx("สิทธิ์")}>{user.owner ? tx("ผู้ดูแลหลัก") : user.admin ? tx("ผู้ดูแลระบบ") : tx("ผู้ใช้ทั่วไป")}</Row>
      </div>
    </>
  );
}

function PrefsTab({ user: initial }: { user: User }) {
  const [user, setUser] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [theme, setTheme] = useState<Theme>("system");
  useEffect(() => setTheme(currentTheme()), []);
  const toggle = async (fn: () => Promise<User>) => {
    setSaving(true);
    try { setUser(await fn()); } catch { /* คงค่าเดิม */ } finally { setSaving(false); }
  };
  const lang = getLang();
  return (
    <>
      <Head title={tx("การแสดงผล")} />
      <div className="set-group">
        <Row title={tx("ภาษา")} desc={tx("ภาษาของหน้าเว็บ (ข้อความจากระบบบางส่วนยังเป็นภาษาไทย)")}>
          <div className="seg" role="group" aria-label={tx("ภาษา")}>
            {([["th", "ไทย"], ["en", "English"]] as [Lang, string][]).map(([k, label]) => (
              <button key={k} type="button" lang={k} aria-pressed={lang === k} onClick={() => chooseLang(k)}>{label}</button>
            ))}
          </div>
        </Row>
        <Row title={tx("ธีม")} desc={tx("อัตโนมัติ = ตามการตั้งค่าของเครื่อง")}>
          <div className="seg" role="group" aria-label={tx("ธีม")}>
            {([["system", "อัตโนมัติ"], ["dark", "มืด"], ["light", "สว่าง"]] as [Theme, string][]).map(([k, label]) => (
              <button key={k} type="button" aria-pressed={theme === k} onClick={() => { chooseTheme(k); setTheme(k); }}>{tx(label)}</button>
            ))}
          </div>
        </Row>
      </div>
      <Head title={tx("อีเมล")} />
      <div className="set-group">
        <Row title={tx("แจ้งเตือนงาน")} desc={tx("แจ้งทางอีเมลเมื่องานรอตรวจบท พากย์เสร็จ หรือไม่สำเร็จ")}>
          <input type="checkbox" className="switch" role="switch" aria-label={tx("แจ้งเตือนงาน")} checked={user.notify_email} disabled={saving}
            onChange={() => toggle(() => api.setNotify(!user.notify_email))} />
        </Row>
        <Row title={tx("ข่าวสารและโปรโมชัน")} desc={tx("ฟีเจอร์ใหม่และโปรโมชัน ยกเลิกได้ทุกเมื่อ")}>
          <input type="checkbox" className="switch" role="switch" aria-label={tx("ข่าวสารและโปรโมชัน")} checked={user.marketing} disabled={saving}
            onChange={() => toggle(() => api.setMarketing(!user.marketing))} />
        </Row>
      </div>
    </>
  );
}

/** เครดิตคงเหลือและประวัติ (ซื้อเครดิตและแพ็กเกจที่หน้าแพ็กเกจและโปรโมชัน) */
function CreditsTab({ unlimited }: { unlimited: boolean }) {
  const { wallet, plans } = useWallet();
  const sub = wallet?.subscription;
  const current = plans.find((p) => p.id === sub?.plan_id);
  const planCredits = sub?.minutes_left ?? 0;
  const total = (wallet?.credits ?? 0) + planCredits;
  return (
    <>
      <Head title={tx("เครดิต")} text={tx("1 เครดิต = คลิป 1 นาที คิดตามความยาวจริง")} />
      <div className="set-group">
        <Row title={tx("ใช้ได้ทั้งหมด")}>
          <span style={{ fontSize: 20, fontWeight: 600, color: "var(--text)" }}>{unlimited ? tx("ไม่จำกัด") : wallet ? fmtCredits(total) : "..."}</span>
        </Row>
        {!unlimited && (
          <>
            <Row title={tx("จากแพ็กเกจ")} desc={tx("ใช้ก่อน หมดอายุพร้อมแพ็กเกจ")}>
              {sub && current ? tx("{0} · {1} · หมดอายุ {2}", { 0: current.name, 1: fmtCredits(planCredits), 2: fmtDate(sub.expires_at) }) : tx("ยังไม่มีแพ็กเกจ")}
            </Row>
            <Row title={tx("เครดิตเติม (ไม่หมดอายุ)")}>{wallet ? fmtCredits(wallet.credits) : "..."}</Row>
            <Row title={tx("เติมเครดิต / ซื้อแพ็กเกจ")} desc={tx("ดูแพ็กเกจและโปรโมชันทั้งหมด")}>
              <Link href="/promotions" className="btn primary small">{tx("ดูแพ็กเกจ")}</Link>
            </Row>
          </>
        )}
      </div>
      <Head title={tx("ประวัติ")} />
      <div className="set-group" style={{ padding: "8px 14px" }}>
        {!wallet?.ledger.length ? <div className="empty">{tx("ยังไม่มีรายการ")}</div> : (
          <table className="ledger" style={{ minWidth: 0 }}>
            <thead><tr><th>{tx("วันที่")}</th><th>{tx("รายการ")}</th><th>{tx("รายละเอียด")}</th><th>{tx("เครดิต")}</th><th>{tx("ชำระ")}</th></tr></thead>
            <tbody>
              {wallet.ledger.map((l, i) => {
                const change = l.credits + l.minutes;
                return (
                  <tr key={i}>
                    <td>{fmtDate(l.created_at)}</td>
                    <td>{KIND_LABEL[l.kind] ? tx(KIND_LABEL[l.kind]) : l.kind}</td>
                    <td className="dim">{l.note}</td>
                    <td className="mono" style={{ color: change > 0 ? "var(--success)" : undefined }}>{change ? signed(change) : ""}</td>
                    <td className="mono">{l.amount && PAID.has(l.kind) ? fmtBaht(Math.abs(l.amount)) : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

/** สิทธิ์ตาม PDPA: ความยินยอม ดาวน์โหลดสำเนาข้อมูล และปิดบัญชีพร้อมลบข้อมูล */
function PrivacyTab({ user }: { user: User }) {
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
    <>
      <Head title={tx("ความยินยอม")} />
      <div className="set-group">
        <Row title={tx("ข้อกำหนดการใช้งาน")}
          desc={user.consent.terms ? tx("ยอมรับฉบับ {0} เมื่อ {1}", { 0: user.consent.terms.version, 1: fmtDay(user.consent.terms.at) }) : undefined}>
          <a href="/terms" target="_blank" rel="noopener">{tx("อ่าน")}</a>
        </Row>
        <Row title={tx("นโยบายความเป็นส่วนตัว")}
          desc={user.consent.privacy ? tx("รับทราบฉบับ {0} เมื่อ {1}", { 0: user.consent.privacy.version, 1: fmtDay(user.consent.privacy.at) }) : undefined}>
          <a href="/privacy" target="_blank" rel="noopener">{tx("อ่าน")}</a>
        </Row>
      </div>
      <Head title={tx("ข้อมูลของฉัน")} />
      <div className="set-group">
        <Row title={tx("ดาวน์โหลดข้อมูลของฉัน")}
          desc={tx("สำเนาข้อมูลบัญชี ความยินยอม ประวัติเครดิต งานพร้อมบทพากย์ และข้อมูลนักพากย์ เป็นไฟล์ JSON (ไฟล์คลิปและเสียงดาวน์โหลดได้จากหน้างานแต่ละงาน)")}>
          <a className="btn small" href={fileUrl.myData()} download>{tx("ดาวน์โหลด")}</a>
        </Row>
        <Row title={tx("ปิดบัญชี")} desc={tx("ปิดบัญชีและลบข้อมูลทั้งหมด")}>
          {!open && <button type="button" className="btn small danger" onClick={() => setOpen(true)}>{tx("ปิดบัญชี")}</button>}
        </Row>
        {open && (
          <div className="set-row block">
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
          </div>
        )}
      </div>
    </>
  );
}

function PayoutTab({ me, reload }: { me: ActorMe | null; reload: () => void }) {
  if (!me) return <div className="empty">{tx("กำลังโหลด...")}</div>;
  const a = me.actor;
  if (!a || a.status === "withdrawn") {
    return (
      <>
        <Head title={tx("รับเงินนักพากย์")} text={tx("กรอกบัญชีรับค่าตอบแทนเมื่อสมัครและได้รับอนุมัติเป็นนักพากย์แล้ว")} />
        <div className="set-group">
          <div className="set-row">
            <div><b>{tx("ยังไม่ได้เป็นนักพากย์")}</b><span className="d">{tx("ไปสมัครที่หน้านักพากย์ก่อน")}</span></div>
            <div className="v"><Link href="/actor" className="btn primary small">{tx("เปิดหน้านักพากย์")}</Link></div>
          </div>
        </div>
      </>
    );
  }
  if (a.status !== "approved") {
    return (
      <>
        <Head title={tx("รับเงินนักพากย์")} text={tx("กรอกได้เมื่อผู้ดูแลอนุมัติใบสมัครแล้ว")} />
        <div className="set-group">
          <div className="set-row">
            <div><b>{a.status === "pending" ? tx("รออนุมัติใบสมัคร") : tx("ใบสมัครยังไม่ผ่าน")}</b>
              <span className="d">{tx("สถานะใบสมัครดูได้ที่หน้านักพากย์")}</span></div>
            <div className="v"><Link href="/actor" className="btn small">{tx("เปิดหน้านักพากย์")}</Link></div>
          </div>
        </div>
      </>
    );
  }
  return <ActorPaymentSection key={me.payment?.updated_at ?? 0} me={me} onSaved={reload} />;
}

/** โปรไฟล์และการตั้งค่าของบัญชี: เมนูย่อยซ้าย (จำแท็บไว้ใน #hash ของลิงก์) */
export default function AccountPage() {
  const { config, user, loaded } = useAuth();
  const [tab, setTab] = useState<Tab>("profile");
  const [actorMe, setActorMe] = useState<ActorMe | null>(null);
  const reloadActor = useCallback(() => {
    api.actorMe().then(setActorMe).catch(() => setActorMe(null));
  }, []);
  useEffect(() => {
    const h = window.location.hash.slice(1);
    if (TABS.some((t) => t.id === h)) setTab(h as Tab);
  }, []);
  useEffect(() => {
    if (loaded && config?.auth && !user) window.location.href = "/welcome?next=/account";
  }, [loaded, config, user]);
  useEffect(() => {
    if (user) reloadActor();
  }, [user, reloadActor]);
  const pick = (t: Tab) => { setTab(t); window.history.replaceState(null, "", `#${t}`); };

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
  const isActor = !!actorMe?.actor && actorMe.actor.status !== "withdrawn";
  const tabs = TABS.filter((t) => {
    if (t.id === "credits") return !!config.billing;
    if (t.id === "payout") return isActor || tab === "payout";
    return true;
  });
  const shown = tabs.some((t) => t.id === tab) ? tab : "profile";
  return (
    <main className="page" style={{ maxWidth: 1040 }}>
      <div className="settings">
        <nav className="settings-nav" aria-label={tx("การตั้งค่าบัญชี")}>
          <span className="ttl">{tx("การตั้งค่าบัญชี")}</span>
          {tabs.map((t) => (
            <button key={t.id} type="button" aria-current={shown === t.id} onClick={() => pick(t.id)}>{t.icon}{tx(t.label)}</button>
          ))}
          {user.admin && <Link href="/admin" className="btn small" style={{ marginTop: 14, alignSelf: "flex-start" }}><ShieldIcon size={14} />{tx("ผู้ดูแลระบบ")}</Link>}
        </nav>
        <div className="settings-body">
          {shown === "profile" && <ProfileTab user={user} />}
          {shown === "prefs" && <PrefsTab user={user} />}
          {shown === "credits" && <CreditsTab unlimited={user.admin} />}
          {shown === "payout" && <PayoutTab me={actorMe} reload={reloadActor} />}
          {shown === "privacy" && <PrivacyTab user={user} />}
        </div>
      </div>
    </main>
  );
}
