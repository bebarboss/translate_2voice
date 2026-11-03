"use client";

import { useEffect, useState } from "react";
import { MicIcon } from "@/components/Icons";
import { api, type AccountType } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";

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
  }, [loaded, config, user]);

  const editing = !!user?.profile_complete;
  const ready = fullName.trim().length >= 2 && phone.trim() && type && (type !== "business" || company.trim());

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!type) return;
    setBusy(true);
    setError("");
    try {
      await api.saveProfile({ name, full_name: fullName, phone, account_type: type, company, use_case: useCase });
      window.location.href = nextPath();
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  if (!loaded || !user) return <main className="page narrow"><div className="empty">กำลังโหลด...</div></main>;
  return (
    <main className="onboard">
      <form className="card onboard-card" onSubmit={submit} aria-labelledby="ob-title">
        <div className="brand" style={{ gap: 10 }}>
          <span className="brand-mark"><MicIcon size={18} color="#1A0E06" /></span>
          Dubbing Studio
        </div>
        <div>
          <h1 id="ob-title" style={{ margin: "0 0 4px", fontSize: 22 }}>{editing ? "แก้ไขข้อมูลบัญชี" : "ข้อมูลเบื้องต้น"}</h1>
          <span className="muted">
            {editing ? user.email : <>ยินดีต้อนรับ {user.email} กรอกข้อมูลอีกนิดก่อนเริ่มใช้งาน</>}
          </span>
        </div>

        <div className="field">
          <label htmlFor="ob-full">ชื่อ-นามสกุล *</label>
          <input id="ob-full" className="input" autoComplete="name" maxLength={100} required
            value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ob-name">ชื่อที่แสดงในระบบ</label>
          <input id="ob-name" className="input" autoComplete="nickname" maxLength={80}
            value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ob-phone">เบอร์โทร *</label>
          <input id="ob-phone" className="input" type="tel" inputMode="tel" autoComplete="tel" maxLength={30} required
            placeholder="0812345678" value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>
        <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="label" style={{ marginBottom: 8 }}>ประเภทผู้ใช้ *</legend>
          <div className="onboard-types">
            {TYPES.map((t) => (
              <button key={t.id} type="button" className="onboard-type" aria-pressed={type === t.id} onClick={() => setType(t.id)}>
                <strong>{t.label}</strong><span className="dim">{t.hint}</span>
              </button>
            ))}
          </div>
        </fieldset>
        {type === "business" && (
          <div className="field">
            <label htmlFor="ob-company">ชื่อบริษัทหรือหน่วยงาน *</label>
            <input id="ob-company" className="input" autoComplete="organization" maxLength={120} required
              value={company} onChange={(e) => setCompany(e.target.value)} />
          </div>
        )}
        <div className="field">
          <label htmlFor="ob-use">ใช้พากย์งานแบบไหน</label>
          <textarea id="ob-use" className="input" rows={2} maxLength={300} placeholder="เช่น ซีรีส์จีน คลิปสอน รีวิวสินค้า"
            value={useCase} onChange={(e) => setUseCase(e.target.value)} />
        </div>

        {error && <div className="alert error" role="alert">{error}</div>}
        <button type="submit" className="btn primary" disabled={busy || !ready}>
          {busy ? "กำลังบันทึก..." : editing ? "บันทึก" : "เริ่มใช้งาน"}
        </button>
        <span className="dim" style={{ fontSize: 13 }}>ใช้ติดต่อเรื่องบัญชีและการชำระเงินเท่านั้น ไม่เปิดเผยให้ผู้อื่น</span>
      </form>
    </main>
  );
}
