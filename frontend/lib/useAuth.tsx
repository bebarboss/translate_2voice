"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type AuthConfig, type User } from "./api";

/** ระบบบัญชีเปิดอยู่ไหม และใครล็อกอินอยู่ (config = null ระหว่างโหลด)
 * ใช้ AuthProvider ใน layout เพื่อให้ Sidebar / ProfileGate / หน้า แชร์ผลโหลดรอบเดียว
 * ไม่ยิง /auth/config และ /auth/me ซ้ำหลายชุดต่อหน้า */

type AuthState = {
  config: AuthConfig | null;
  user: User | null;
  loaded: boolean;
  reload: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

const EMPTY: AuthConfig = {
  auth: false, billing: false, payments: false, payment_provider: "", google_client_id: "", stripe_publishable_key: "",
};

type Snapshot = { config: AuthConfig; user: User | null; at: number };
let cache: Snapshot | null = null;
let inflight: Promise<Snapshot> | null = null;
const CACHE_MS = 3_000;

const AUTH_TIMEOUT_MS = 12_000;

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("auth timeout")), ms);
    p.then((v) => { clearTimeout(t); resolve(v); }, (e) => { clearTimeout(t); reject(e); });
  });
}

async function fetchAuth(): Promise<Snapshot> {
  try {
    const config = await withTimeout(api.authConfig(), AUTH_TIMEOUT_MS);
    const user = config.auth ? await withTimeout(api.me().catch(() => null), AUTH_TIMEOUT_MS) : null;
    return { config, user, at: Date.now() };
  } catch {
    // tunnel/API ค้าง → อย่าค้าง "กำลังโหลด" ทั้งหน้า; สมมติว่าต้องล็อกอินเพื่อพาไป /login
    return { config: { ...EMPTY, auth: true }, user: null, at: Date.now() };
  }
}

/** แชร์คำขอที่กำลังวิ่ง และแคชสั้น ๆ กัน React Strict Mode / คอมโพเนนต์หลายตัวยิงซ้ำ */
function loadAuth(force = false): Promise<Snapshot> {
  if (force) {
    cache = null;
    inflight = null;
  } else if (cache && Date.now() - cache.at < CACHE_MS) {
    return Promise.resolve(cache);
  }
  if (!inflight) {
    inflight = fetchAuth().then((snap) => {
      cache = snap;
      return snap;
    }).finally(() => { inflight = null; });
  }
  return inflight;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [loaded, setLoaded] = useState(false);

  const reload = useCallback(async () => {
    const snap = await loadAuth(true);
    setConfig(snap.config);
    setUser(snap.user);
    setLoaded(true);
  }, []);

  useEffect(() => {
    let alive = true;
    loadAuth(false).then((snap) => {
      if (!alive) return;
      setConfig(snap.config);
      setUser(snap.user);
      setLoaded(true);
    });
    return () => { alive = false; };
  }, []);

  return (
    <AuthContext.Provider value={{ config, user, loaded, reload }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth ต้องห่อด้วย AuthProvider ใน layout");
  return ctx;
}
