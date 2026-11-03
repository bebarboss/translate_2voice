"use client";

import { useEffect, useState } from "react";
import { MicIcon } from "@/components/Icons";
import { api, type AccountType, type Legal } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";

import Prefs from "@/components/Prefs";
import { tx } from "@/lib/i18n";
const TYPES: { id: AccountType; label: string; hint: string }[] = [
  { id: "personal", label: "บุคคลทั่วไป", hint: "พากย์คลิปส่วนตัว" },
  { id: "creator", label: "ครีเอเตอร์", hint: "YouTube, TikTok, เพจ" },
  { id: "business", label: "บริษัท / หน่วยงาน", hint: "สตูดิโอ เอเจนซี องค์กร" },
];

function nextPath(): string {
  const next = new URLSearchParams(window.location.search).get("next") ?? "/";
  return next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/onboarding") ? next : "/";
}

/** ข้อมูลเบื้องต้นที่ต้องกรอกหลังล็อกอินด้วย Google ครั้งแรก (แก้ภายหลังได้จากหน้าบัญชี) */
export default function OnboardingPage() {
  const { config, user, loaded } = useAuth();
  const [name, setName] = useState("");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [type, setType] = useState<AccountType | "">("");
  const [company, setCompany] = useState("");
  const [useCase, setUseCase] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [legal, setLegal] = useState<Legal | null>(null);
  const [terms, setTerms] = useState(false);
  const [privacy, setPrivacy] = useState(false);
  const [marketing, setMarketing] = useState(false);
  useEffect(() => { api.legal().then(setLegal).catch((e) => setError(e.message)); }, []);

  useEffect(() => {
    if (!loaded) return;
    if (!config?.auth) { window.location.href = "/"; return; }
    if (!user) { window.location.href = `/login?next=${encodeURIComponent("/onboarding" + window.location.search)}`; return; }
    const p = user.profile;
    setName(user.name);
    setFullName(p.full_name);
    setPhone(p.phone);
    setType(p.account_type);
    setCompany(p.company);
    setUseCase(p.use_case);
    setMarketing(user.marketing);
  }, [loaded, config, user]);

  const editing = !!user?.profile_complete;
  const needConsent = !!user && !user.consent_current;
  const consentOnly = editing && needConsent; // ผู้ใช้เดิม: ข้อกำหนดมีฉบับใหม่ ยอมรับอย่างเดียว
  const consentOk = !needConsent || (terms && privacy && !!legal);
  const ready = consentOk && (consentOnly
    || (fullName.trim().length >= 2 && phone.trim() && type && (type !== "business" || company.trim())));
  const versions = legal && needConsent
    ? { terms_version: legal.terms.version, privacy_version: legal.privacy.version, marketing } : {};

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (consentOnly && legal) {
        await api.acceptConsent({ terms_version: legal.terms.version, privacy_version: legal.privacy.version, marketing });
      } else {
        if (!type) return;
        await api.saveProfile({ name, full_name: fullName, phone, account_type: type, company, use_case: useCase, ...versions });
      }
      window.location.href = nextPath();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  if (!loaded || !user) return <main className="page narrow"><div className="empty">{tx("กำลังโหลด...")}</div></main>;
  return (
    <main className="onboard">
      <div className="corner-prefs"><Prefs compact /></div>
      <form className="card onboard-card" onSubmit={submit} aria-labelledby="ob-title">
        <div className="brand" style={{ gap: 10 }}>
          <span className="brand-mark"><MicIcon size={18} color="#1A0E06" /></span>
          Dubbing Studio
        </div>
        <div>
          <h1 id="ob-title" style={{ margin: "0 0 4px", fontSize: 22 }}>
            {consentOnly ? tx("ข้อกำหนดฉบับใหม่") : editing ? tx("แก้ไขข้อมูลบัญชี") : tx("ข้อมูลเบื้องต้น")}
          </h1>
          <span className="muted">
            {consentOnly ? tx("ข้อกำหนดการใช้งานหรือนโยบายความเป็นส่วนตัวมีการแก้ไข อ่านและกดยอมรับก่อนใช้งานต่อ")
              : editing ? user.email : <>{tx("ยินดีต้อนรับ")} {user.email}  {tx("กรอกข้อมูลอีกนิดก่อนเริ่มใช้งาน")}</>}
          </span>
        </div>
        {!consentOnly && <>

        <div className="field">
          <label htmlFor="ob-full">{tx("ชื่อ-นามสกุล *")}</label>
          <input id="ob-full" className="input" autoComplete="name" maxLength={100} required
            value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ob-name">{tx("ชื่อที่แสดงในระบบ")}</label>
          <input id="ob-name" className="input" autoComplete="nickname" maxLength={80}
            value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ob-phone">{tx("เบอร์โทร *")}</label>
          <input id="ob-phone" className="input" type="tel" inputMode="tel" autoComplete="tel" maxLength={30} required
            placeholder="0812345678" value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>
        <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="label" style={{ marginBottom: 8 }}>{tx("ประเภทผู้ใช้ *")}</legend>
          <div className="onboard-types">
            {TYPES.map((t) => (
              <button key={t.id} type="button" className="onboard-type" aria-pressed={type === t.id} onClick={() => setType(t.id)}>
                <strong>{tx(t.label)}</strong><span className="dim">{tx(t.hint)}</span>
              </button>
            ))}
          </div>
        </fieldset>
        {type === "business" && (
          <div className="field">
            <label htmlFor="ob-company">{tx("ชื่อบริษัทหรือหน่วยงาน *")}</label>
            <input id="ob-company" className="input" autoComplete="organization" maxLength={120} required
              value={company} onChange={(e) => setCompany(e.target.value)} />
          </div>
        )}
        <div className="field">
          <label htmlFor="ob-use">{tx("ใช้พากย์งานแบบไหน")}</label>
          <textarea id="ob-use" className="input" rows={2} maxLength={300} placeholder={tx("เช่น ซีรีส์จีน คลิปสอน รีวิวสินค้า")}
            value={useCase} onChange={(e) => setUseCase(e.target.value)} />
        </div>
        </>}

        {needConsent && (
          <div className="consent-checks">
            <label className="agree">
              <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
              <span>{tx("ข้าพเจ้ายอมรับ")} <a href="/terms" target="_blank" rel="noopener">{tx("ข้อกำหนดการใช้งาน")}</a>
                {legal && <span className="dim">  {tx("(ฉบับ")} {legal.terms.version})</span>}  {tx("และรับรองว่ามีสิทธิ์ในคลิปและเสียงที่อัปโหลด *")}</span>
            </label>
            <label className="agree">
              <input type="checkbox" checked={privacy} onChange={(e) => setPrivacy(e.target.checked)} />
              <span>{tx("ข้าพเจ้าได้อ่านและรับทราบ")} <a href="/privacy" target="_blank" rel="noopener">{tx("นโยบายความเป็นส่วนตัว")}</a>
                {legal && <span className="dim">  {tx("(ฉบับ")} {legal.privacy.version})</span>}  {tx("รวมถึงการส่งข้อมูลไปประมวลผลกับผู้ให้บริการในต่างประเทศ *")}</span>
            </label>
            <label className="agree">
              <input type="checkbox" checked={marketing} onChange={(e) => setMarketing(e.target.checked)} />
              <span>{tx("รับข่าวสาร ฟีเจอร์ใหม่ และโปรโมชันทางอีเมล (ไม่บังคับ ยกเลิกได้ที่หน้าบัญชี)")}</span>
            </label>
          </div>
        )}

        {error && <div className="alert error" role="alert">{error}</div>}
        <button type="submit" className="btn primary" disabled={busy || !ready}>
          {busy ? tx("กำลังบันทึก...") : consentOnly ? tx("ยอมรับและใช้งานต่อ") : editing ? tx("บันทึก") : tx("เริ่มใช้งาน")}
        </button>
        <span className="dim" style={{ fontSize: 13 }}>{tx("ใช้ติดต่อเรื่องบัญชีและการชำระเงินเท่านั้น ไม่เปิดเผยให้ผู้อื่น")}</span>
      </form>
    </main>
  );
}
