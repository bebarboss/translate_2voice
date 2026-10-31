// ส่งต่อทุกคำขอ /api/* ไปที่ Thai Dubbing API
// ทำให้เบราว์เซอร์ไม่ต้องรู้ที่อยู่หรือคีย์ของ API และไม่ติดปัญหา CORS
import type { NextRequest } from "next/server";
import { SESSION_COOKIE, clearSessionCookie, sessionCookie } from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
// สตรีมวิดีโอยาว ๆ บน Vercel (Hobby สูงสุด 300 วินาที)
export const maxDuration = 300;

const BACKEND = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "") + "/";
const API_KEY = process.env.API_KEY ?? "";

const FORWARD_REQUEST = ["content-type", "content-length", "range", "accept", "if-none-match"];
const FORWARD_RESPONSE = [
  "content-type", "content-length", "content-range", "accept-ranges",
  "content-disposition", "etag", "last-modified",
];

type Ctx = { params: Promise<{ path: string[] }> };

async function proxy(req: NextRequest, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  const url = new URL(path.map(encodeURIComponent).join("/"), BACKEND);
  url.search = req.nextUrl.search;

  const headers = new Headers();
  for (const name of FORWARD_REQUEST) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (API_KEY) headers.set("x-api-key", API_KEY);
  const session = req.cookies.get(SESSION_COOKIE)?.value;
  if (session) headers.set("x-user-token", session);
  headers.set("ngrok-skip-browser-warning", "1"); // ngrok แบบฟรีจะไม่แทรกหน้าเตือน

  const init: RequestInit & { duplex?: "half" } = { method: req.method, headers, redirect: "manual" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = req.body;
    init.duplex = "half"; // สตรีมไฟล์อัปโหลดต่อไปเลย ไม่ต้องพักไว้ในหน่วยความจำ
  }

  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    return Response.json(
      { detail: "เชื่อมต่อ API พากย์เสียงไม่ได้ ตรวจว่าเปิด API ไว้ และตั้งค่า BACKEND_URL ถูกต้อง" },
      { status: 502 },
    );
  }

  const out = new Headers();
  for (const name of FORWARD_RESPONSE) {
    const value = res.headers.get(name);
    if (value) out.set(name, value);
  }
  out.set("cache-control", "no-store");

  // ล็อกอิน/สมัคร: เก็บ token ลงคุกกี้ httpOnly ไม่ส่ง token ให้สคริปต์ในหน้าเว็บ
  const route = path.join("/");
  if (res.ok && (route === "auth/login" || route === "auth/signup")) {
    const { token, user } = (await res.json()) as { token: string; user: unknown };
    out.delete("content-length");
    out.append("set-cookie", sessionCookie(token));
    return Response.json({ user }, { status: res.status, headers: out });
  }
  if (route === "auth/logout" || (res.status === 401 && session)) out.append("set-cookie", clearSessionCookie);
  return new Response(res.body, { status: res.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as HEAD };
