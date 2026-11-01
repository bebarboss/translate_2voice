"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";

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

/** หน้าที่จะกลับไปหลังล็อกอิน (เฉพาะในเว็บนี้) */
function nextPath(): string {
  const next = new URLSearchParams(window.location.search).get("next") ?? "/";
  return next.startsWith("/") && !next.startsWith("//") ? next : "/";
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
            await api.googleLogin(credential);
            window.location.href = nextPath(); // โหลดใหม่ทั้งหน้า เมนูด้านบนจะเห็นผู้ใช้ทันที
          } catch (err) {
            setError((err as Error).message);
            setBusy(false);
          }
        },
      });
      gid.renderButton(el, {
        theme: "outline", size: "large", shape: "pill", locale: "th",
        text: signup ? "signup_with" : "signin_with", width: 300,
      });
    }).catch(() => setError("โหลดปุ่ม Google ไม่ได้ ตรวจการเชื่อมต่อแล้วรีเฟรชหน้า"));
  }, [clientId, signup]);

  if (!loaded) return <main className="page narrow"><div className="empty">กำลังโหลด...</div></main>;
  if (!config?.auth) {
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
    <main className="page narrow">
      <section className="card" aria-labelledby="auth-title" style={{ alignItems: "center", textAlign: "center" }}>
        <h1 id="auth-title" style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>
          {signup ? "สมัครสมาชิก" : "เข้าสู่ระบบ"}
        </h1>
        <p className="muted" style={{ margin: 0 }}>ใช้บัญชี Google (Gmail) ครั้งแรกระบบสร้างบัญชีให้อัตโนมัติ ไม่ต้องตั้งรหัสผ่าน</p>
        {clientId
          ? <div ref={button} aria-busy={busy} style={{ minHeight: 44, opacity: busy ? 0.5 : 1 }} />
          : <div className="alert error" role="alert">ยังไม่ได้ตั้งค่าการเข้าสู่ระบบด้วย Google ติดต่อผู้ดูแลระบบ</div>}
        {busy && <span className="dim" role="status">กำลังเข้าสู่ระบบ...</span>}
        {error && <div className="alert error" role="alert">{error}</div>}
      </section>
    </main>
  );
}
