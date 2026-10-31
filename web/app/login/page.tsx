"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";

type Mode = "login" | "signup";

/** หน้าที่จะกลับไปหลังล็อกอิน (เฉพาะในเว็บนี้) */
function nextPath(): string {
  const next = new URLSearchParams(window.location.search).get("next") ?? "/";
  return next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export default function LoginPage() {
  const { config, loaded } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "login") await api.login(email.trim(), password);
      else await api.signup(email.trim(), password, name.trim());
      window.location.href = nextPath(); // โหลดใหม่ทั้งหน้า เมนูด้านบนจะเห็นผู้ใช้ทันที
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

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
      <form className="card" onSubmit={submit} aria-labelledby="auth-title">
        <h1 id="auth-title" style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>
          {mode === "login" ? "เข้าสู่ระบบ" : "สมัครสมาชิก"}
        </h1>
        <div className="seg" role="group" aria-label="เลือกเข้าสู่ระบบหรือสมัคร" style={{ alignSelf: "flex-start" }}>
          <button type="button" aria-pressed={mode === "login"} onClick={() => { setMode("login"); setError(""); }}>เข้าสู่ระบบ</button>
          <button type="button" aria-pressed={mode === "signup"} onClick={() => { setMode("signup"); setError(""); }}>สมัครใหม่</button>
        </div>
        {mode === "signup" && (
          <div className="field">
            <label htmlFor="name">ชื่อที่แสดง</label>
            <input id="name" className="input" maxLength={80} autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
        )}
        <div className="field">
          <label htmlFor="email">อีเมล</label>
          <input id="email" className="input" type="email" required autoComplete="email" value={email}
            onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="password">รหัสผ่าน</label>
          <input id="password" className="input" type="password" required minLength={8}
            autoComplete={mode === "login" ? "current-password" : "new-password"} value={password}
            onChange={(e) => setPassword(e.target.value)} />
          {mode === "signup" && <span className="dim">อย่างน้อย 8 ตัว</span>}
        </div>
        {error && <div className="alert error" role="alert">{error}</div>}
        <button type="submit" className="btn primary lg" disabled={busy}>
          {busy ? "กำลังดำเนินการ..." : mode === "login" ? "เข้าสู่ระบบ" : "สมัครและเข้าสู่ระบบ"}
        </button>
      </form>
    </main>
  );
}
