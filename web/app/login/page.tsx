"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";
import { MicIcon, XIcon } from "@/components/Icons";

import Prefs from "@/components/Prefs";
import { tx } from "@/lib/i18n";
/** Google Identity Services (https://accounts.google.com/gsi/client) ใช้แค่ส่วนที่เรียก */
type CredentialResponse = { credential: string };
type GoogleId = {
  initialize(o: { client_id: string; callback: (r: CredentialResponse) => void; ux_mode?: "popup" }): void;
  renderButton(el: HTMLElement, o: Record<string, string | number>): void;
};
declare global { interface Window { google?: { accounts: { id: GoogleId } } } }

const GSI_SRC = "https://accounts.google.com/gsi/client";

function loadGsi(): Promise<GoogleId> {
  return new Promise((resolve, reject) => {
    if (window.google?.accounts?.id) return resolve(window.google.accounts.id);
    const s = document.createElement("script");
    s.src = GSI_SRC;
    s.async = true;
    s.onload = () => (window.google?.accounts?.id ? resolve(window.google.accounts.id) : reject());
    s.onerror = () => reject();
    document.head.appendChild(s);
  });
}

/** สิ่งที่ได้จากระบบ แสดงทีละข้อบนการ์ดฝั่งซ้าย (ข้อที่ไฮไลต์ = การ์ดที่แสดง) */
const OFFERS = [
  { title: "แยกเสียงตัวละครอัตโนมัติ", text: "รู้เองว่าใครพูดประโยคไหน ไม่ต้องบอกจำนวนคน" },
  { title: "แปลไทยให้พอดีปาก", text: "ย่อบทให้พูดทันเวลา ตามแนวเรื่องและชื่อตัวละคร" },
  { title: "เลียนเสียงนักแสดงต้นฉบับ", text: "หรือเลือกเสียงพากย์ไทยจากคลัง พร้อมหลายอารมณ์" },
  { title: "แก้บนไทม์ไลน์", text: "ลาก ตัด วางเสียงซ้อน แล้วพากย์ใหม่เฉพาะตรงที่แก้" },
  { title: "ซับไทยและเสียงแยกเลเยอร์", text: "ดาวน์โหลดวิดีโอพากย์ ซับ และเสียงแต่ละตัวละคร" },
  { title: "คิดเครดิตตามความยาวจริง", text: "คลิป 1:15 นาที ใช้ 1.25 เครดิต ไม่ปัดขึ้น" },
];
// ความสูงแท่งคลื่นเสียง (0–1) คงที่ ไม่สุ่มตอนเรนเดอร์ หน้าเซิร์ฟเวอร์กับเบราว์เซอร์จะได้ตรงกัน
const WAVE = Array.from({ length: 44 }, (_, i) => 0.18 + 0.82 * Math.abs(Math.sin(i * 0.55) * Math.cos(i * 0.21)));

/** ฝั่งซ้าย: การ์ดซ้อนที่เปลี่ยนตามข้อที่ไฮไลต์ และรายการสิ่งที่ได้ */
function Showcase({ bonus }: { bonus: number }) {
  const offers = bonus ? [...OFFERS, { title: tx("ผูกบัตรรับฟรี {0} เครดิต", { 0: bonus }), text: tx("ผูกบัตรครั้งแรก รับเครดิตไว้ลองพากย์ได้ทันที") }] : OFFERS;
  const [i, setI] = useState(0);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    if (paused || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = window.setInterval(() => setI((x) => (x + 1) % offers.length), 3200);
    return () => window.clearInterval(id);
  }, [paused, offers.length]);
  const cur = offers[i % offers.length];
  return (
    <section className="auth-show" aria-label={tx("สิ่งที่ได้จาก Dubbing Studio")}>
      <div className="auth-stack" aria-hidden="true">
        <div className="auth-sheet back" />
        <div className="auth-sheet mid" />
        <div className="auth-sheet front">
          <div key={i} className="auth-sheet-body">
            <b>{tx(cur.title)}</b>
            <span>{tx(cur.text)}</span>
            <div className="auth-wave">
              {WAVE.map((h, n) => <i key={n} style={{ height: `${Math.round(h * 100)}%`, animationDelay: `${n * 40}ms` }} />)}
            </div>
          </div>
        </div>
        <span className="auth-badge"><MicIcon size={20} color="#1A0E06" /></span>
      </div>
      <div className="auth-offers" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
        <h2>{tx("สมัครแล้วใช้ได้เลย")}</h2>
        <ul>
          {offers.map((o, n) => (
            <li key={o.title}>
              <button type="button" aria-current={n === i % offers.length} onClick={() => setI(n)}
                onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>{tx(o.title)}</button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/** หน้าที่จะกลับไปหลังล็อกอิน (เฉพาะในเว็บนี้) */
function nextPath(): string {
  const next = new URLSearchParams(window.location.search).get("next") ?? "/dashboard";
  return next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
}

/** สมัครและเข้าสู่ระบบด้วยบัญชี Google เท่านั้น ครั้งแรกระบบสร้างบัญชีให้เลย */
export default function LoginPage() {
  const { config, loaded } = useAuth();
  const button = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // ปุ่ม "เริ่มพากย์คลิปแรก" ในหน้าแรกส่ง ?mode=signup มา
  const [signup, setSignup] = useState(false);
  useEffect(() => { setSignup(new URLSearchParams(window.location.search).get("mode") === "signup"); }, []);

  const [bonus, setBonus] = useState(0);
  useEffect(() => {
    if (config?.billing) api.plans().then((p) => setBonus(p.card_bonus)).catch(() => {});
  }, [config?.billing]);

  const clientId = config?.google_client_id ?? "";
  useEffect(() => {
    if (!clientId || !button.current) return;
    const el = button.current;
    loadGsi().then((gid) => {
      gid.initialize({
        client_id: clientId,
        ux_mode: "popup",
        callback: async ({ credential }) => {
          setBusy(true);
          setError("");
          try {
            const { user } = await api.googleLogin(credential);
            // โหลดใหม่ทั้งหน้า เมนูด้านบนจะเห็นผู้ใช้ทันที ครั้งแรกต้องกรอกข้อมูลเบื้องต้นก่อน
            window.location.href = (user.profile_complete && user.consent_current) || user.admin
              ? nextPath() : `/onboarding?next=${encodeURIComponent(nextPath())}`;
          } catch (err) {
            setError((err as Error).message);
            setBusy(false);
          }
        },
      });
      gid.renderButton(el, {
        theme: "outline", size: "large", shape: "pill", locale: "th",
        text: signup ? "signup_with" : "signin_with", width: 320,
      });
    }).catch(() => setError(tx("โหลดปุ่ม Google ไม่ได้ ตรวจการเชื่อมต่อแล้วรีเฟรชหน้า")));
  }, [clientId, signup, loaded]); // loaded: กล่องปุ่มเพิ่งมีหลังหน้าโหลดเสร็จ

  let body: React.ReactNode;
  if (!loaded) body = <div className="empty">{tx("กำลังโหลด...")}</div>;
  else if (!config?.auth) {
    body = (
      <>
        <h1 id="auth-title" className="auth-title">{tx("ระบบบัญชีผู้ใช้ยังไม่เปิดใช้งาน")}</h1>
        <p className="auth-note">{tx("ตอนนี้ใช้งานทุกหน้าได้เลยโดยไม่ต้องเข้าสู่ระบบ")}</p>
        <Link href="/" className="btn primary">{tx("ไปหน้าอัปโหลด")}</Link>
      </>
    );
  } else {
    body = (
      <>
        <h1 id="auth-title" className="auth-title">{signup ? tx("สมัครสมาชิก") : tx("เข้าสู่ระบบ")}</h1>
        {clientId
          ? <div ref={button} className="auth-google" aria-busy={busy} style={{ opacity: busy ? 0.5 : 1 }} />
          : <div className="alert error" role="alert">{tx("ยังไม่ได้ตั้งค่าการเข้าสู่ระบบด้วย Google ติดต่อผู้ดูแลระบบ")}</div>}
        {busy && <span className="dim" role="status">{tx("กำลังเข้าสู่ระบบ...")}</span>}
        {error && <div className="alert error" role="alert">{error}</div>}
        <p className="auth-note">{tx("ใช้บัญชี Google (Gmail) เท่านั้น ครั้งแรกระบบสร้างบัญชีให้อัตโนมัติ ไม่ต้องตั้งรหัสผ่าน")}</p>
      </>
    );
  }

  return (
    <main className="auth-page">
      <Showcase bonus={config?.billing ? bonus : 0} />
      <section className="auth-panel" aria-labelledby="auth-title">
        <Link href="/welcome" className="icon-only auth-close" aria-label={tx("กลับหน้าแรก")}><XIcon size={18} /></Link>
        <div className="auth-prefs"><Prefs compact /></div>
        <div className="auth-box">
          <Link href="/welcome" className="brand auth-brand">
            <span className="brand-mark"><MicIcon size={18} color="#1A0E06" /></span>
            <span className="auth-brand-text">Dubbing Studio<small>{tx("พากย์ไทยด้วย AI")}</small></span>
          </Link>
          {body}
        </div>
      </section>
    </main>
  );
}
