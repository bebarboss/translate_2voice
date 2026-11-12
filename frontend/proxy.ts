// ตัดผู้ที่ยังไม่ล็อกอินออกจากหน้าแอปก่อนเรนเดอร์ shell
// ไม่งั้นหน้าขึ้น 200 ค้างที่ "กำลังโหลด..." แล้วค่อยเด้งหลัง /api ตอบ 401
import { NextResponse, type NextRequest } from "next/server";
import { authGate, isAdminPath, isProtectedPath, type AdminState } from "@/lib/auth-routes";
import { SESSION_COOKIE } from "@/lib/session";

function runtimeEnv(name: string, fallback = ""): string {
  // Bracket access so `next build` does not bake the value into the image.
  const value = process.env[name];
  return (value ?? fallback).trim();
}

function backend(): string {
  return runtimeEnv("BACKEND_URL", "http://localhost:8000").replace(/\/+$/, "");
}

function backendHeaders(token?: string): Headers {
  const headers = new Headers();
  const key = runtimeEnv("API_KEY");
  if (key) headers.set("x-api-key", key);
  if (token) headers.set("x-user-token", token);
  headers.set("ngrok-skip-browser-warning", "1");
  return headers;
}

const CONFIG_TTL_MS = 30_000;
const CONFIG_FAIL_TTL_MS = 5_000;
let configCache: { at: number; ttl: number; auth: boolean } | null = null;

/** ระบบบัญชีปิดอยู่ (AUTH_ENABLED=0) ต้องไม่บังคับคุกกี้ ไม่งั้นทุกหน้าวนไป /login */
async function authRequired(): Promise<boolean> {
  if (configCache && Date.now() - configCache.at < configCache.ttl) return configCache.auth;
  try {
    const res = await fetch(`${backend()}/auth/config`, {
      headers: backendHeaders(),
      cache: "no-store",
      signal: AbortSignal.timeout(4_000),
    });
    if (!res.ok) {
      configCache = { at: Date.now(), ttl: CONFIG_FAIL_TTL_MS, auth: true };
      return true;
    }
    const body = (await res.json()) as { auth?: boolean };
    const auth = body.auth !== false;
    configCache = { at: Date.now(), ttl: CONFIG_TTL_MS, auth };
    return auth;
  } catch {
    // ต่อ API ไม่ได้: ค่าเริ่มต้นของเซิร์ฟเวอร์คือเปิดบัญชี กัน shell โผล่โดยไม่มี session
    configCache = { at: Date.now(), ttl: CONFIG_FAIL_TTL_MS, auth: true };
    return true;
  }
}

async function adminState(token: string): Promise<AdminState> {
  try {
    const res = await fetch(`${backend()}/auth/me`, {
      headers: backendHeaders(token),
      cache: "no-store",
      signal: AbortSignal.timeout(4_000),
    });
    if (res.status === 401) return "anon";
    if (!res.ok) return "unknown";
    const user = (await res.json()) as { admin?: boolean };
    return user.admin ? "admin" : "no";
  } catch {
    return "unknown";
  }
}

export async function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (!isProtectedPath(pathname)) return NextResponse.next();

  const authOn = await authRequired();
  const token = request.cookies.get(SESSION_COOKIE)?.value?.trim() ?? "";
  const admin = authOn && token && isAdminPath(pathname) ? await adminState(token) : undefined;
  const decision = authGate(pathname, search, { authOn, hasSession: Boolean(token), admin });
  if (decision.action === "redirect") {
    return NextResponse.redirect(new URL(decision.location, request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    // ไม่แตะ /api (รวม callback ของ Google ที่ตั้งคุกกี้) และไฟล์คงที่
    "/((?!api|_next/static|_next/image|favicon.ico|brand/|.*\\.(?:png|jpg|jpeg|gif|webp|svg|ico|mp4|txt|xml|woff2?)$).*)",
  ],
};
