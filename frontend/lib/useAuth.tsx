"use client";

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useState, type ReactNode } from "react";
import { ApiError, api, type AuthConfig, type User } from "./api";

/** ระบบบัญชีเปิดอยู่ไหม และใครล็อกอินอยู่ (config = null ระหว่างโหลด)
 * ใช้ AuthProvider ใน layout เพื่อให้ Sidebar / ProfileGate / หน้า แชร์ผลโหลดรอบเดียว
 * ไม่ยิง /auth/config และ /auth/me ซ้ำหลายชุดต่อหน้า
 *
 * 401 เท่านั้นที่แปลว่ายังไม่ล็อกอิน 5xx / เน็ตหลุด / timeout คงผู้ใช้ที่รู้ล่าสุด
 * ไม่สลับเมนูเป็นปุ่มเข้าสู่ระบบ */

type AuthState = {
  config: AuthConfig | null;
  user: User | null;
  loaded: boolean;
  /** คำขอยืนยันตัวตนล้มเพราะเซิร์ฟเวอร์หรือเน็ต ไม่ใช่เพราะไม่มี session */
  unavailable: boolean;
  reload: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

const EMPTY: AuthConfig = {
  auth: false, billing: false, payments: false, payment_provider: "", google_client_id: "", stripe_publishable_key: "",
};

type Snapshot = { config: AuthConfig; user: User | null; unavailable: boolean; at: number };
type StoredAuth = { config: AuthConfig; user: User };

let cache: Snapshot | null = null;
let inflight: Promise<Snapshot> | null = null;
let generation = 0;
const CACHE_MS = 3_000;
const STORE_KEY = "pakdee.auth.v1";

const AUTH_TIMEOUT_MS = 12_000;

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("auth timeout")), ms);
    p.then((v) => { clearTimeout(t); resolve(v); }, (e) => { clearTimeout(t); reject(e); });
  });
}

/** 401 = ยังไม่ล็อกอินหรือ session หมด รหัสอื่น (รวม 5xx และเน็ตหลุด status 0) ไม่ใช่ */
export function isUnauthenticated(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

function readStored(): StoredAuth | null {
  if (typeof localStorage === "undefined") return null;
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { config?: AuthConfig; user?: User };
    if (!parsed?.user?.id || !parsed.user.email || typeof parsed.config?.auth !== "boolean") return null;
    return { config: parsed.config, user: parsed.user };
  } catch {
    return null;
  }
}

function writeStored(value: StoredAuth | null) {
  if (typeof localStorage === "undefined") return;
  try {
    if (!value) localStorage.removeItem(STORE_KEY);
    else localStorage.setItem(STORE_KEY, JSON.stringify(value));
  } catch { /* โหมดส่วนตัวเขียนที่เก็บไม่ได้ */ }
}

/** ล้างผู้ใช้ที่จำไว้ เรียกตอนกดออกจากระบบ เพื่อไม่ให้ 5xx ดึงบัญชีเก่ากลับมา */
export function clearStoredSession() {
  cache = null;
  writeStored(null);
}

function remembered(): StoredAuth | null {
  if (cache?.user && cache.config) return { config: cache.config, user: cache.user };
  return readStored();
}

async function fetchAuth(): Promise<Snapshot> {
  const previous = remembered();
  try {
    const config = await withTimeout(api.authConfig(), AUTH_TIMEOUT_MS);
    if (!config.auth) {
      writeStored(null);
      return { config, user: null, unavailable: false, at: Date.now() };
    }
    try {
      const user = await withTimeout(api.me(), AUTH_TIMEOUT_MS);
      writeStored({ config, user });
      return { config, user, unavailable: false, at: Date.now() };
    } catch (e) {
      if (isUnauthenticated(e)) {
        writeStored(null);
        return { config, user: null, unavailable: false, at: Date.now() };
      }
      // 5xx / timeout / เน็ตหลุด: คงบัญชีที่เคยโหลดได้ อย่าทำให้เมนูกลายเป็นปุ่มเข้าสู่ระบบ
      return { config, user: previous?.user ?? null, unavailable: true, at: Date.now() };
    }
  } catch {
    if (previous) return { config: previous.config, user: previous.user, unavailable: true, at: Date.now() };
    // ยังไม่เคยรู้ว่าใครล็อกอิน แต่ก็ยังไม่ยืนยันว่าเป็น 401
    return { config: { ...EMPTY, auth: true }, user: null, unavailable: true, at: Date.now() };
  }
}

/** แชร์คำขอที่กำลังวิ่ง และแคชสั้น ๆ กัน React Strict Mode / คอมโพเนนต์หลายตัวยิงซ้ำ */
function loadAuth(force = false): Promise<Snapshot> {
  if (force) {
    cache = null;
    inflight = null;
    generation += 1;
  } else if (cache && Date.now() - cache.at < CACHE_MS) {
    return Promise.resolve(cache);
  }
  if (!inflight) {
    const gen = generation;
    inflight = fetchAuth().then((snap) => {
      if (gen === generation) cache = snap;
      return snap;
    }).finally(() => {
      if (gen === generation) inflight = null;
    });
  }
  return inflight;
}

/** จริง ๆ ว่าไม่ได้ล็อกอิน (401 หรือ auth เปิดและไม่มีผู้ใช้) ไม่นับตอนเซิร์ฟเวอร์ล่ม */
export function isSignedOut(state: { config: AuthConfig | null; user: User | null; unavailable: boolean }): boolean {
  return !!state.config?.auth && !state.user && !state.unavailable;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [unavailable, setUnavailable] = useState(false);

  const apply = useCallback((snap: Snapshot) => {
    setConfig(snap.config);
    setUser(snap.user);
    setUnavailable(snap.unavailable);
    setLoaded(true);
  }, []);

  const reload = useCallback(async () => {
    apply(await loadAuth(true));
  }, [apply]);

  // ก่อนเพนต์: ถ้าเบราว์เซอร์นี้เคยโหลดบัญชีได้ ให้โชว์ต่อทันที แม้รอบนี้ /auth/me จะ 502
  useLayoutEffect(() => {
    const stored = readStored();
    if (!stored) return;
    setConfig((current) => current ?? stored.config);
    setUser((current) => current ?? stored.user);
  }, []);

  useEffect(() => {
    let alive = true;
    loadAuth(false).then((snap) => {
      if (!alive) return;
      apply(snap);
    });
    return () => { alive = false; };
  }, [apply]);

  return (
    <AuthContext.Provider value={{ config, user, loaded, unavailable, reload }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth ต้องห่อด้วย AuthProvider ใน layout");
  return ctx;
}
