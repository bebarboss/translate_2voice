// ออกตั๋วให้เบราว์เซอร์อัปโหลดไฟล์ตรงไปที่ API (ผ่าน ngrok) ไม่ผ่าน proxy
// เพราะ Vercel รับ body ได้ไม่เกิน 4.5 MB ตั๋วเป็น HMAC ของ API_KEY ที่หมดอายุเอง คีย์จริงไม่หลุดไปเบราว์เซอร์
import { createHmac } from "node:crypto";
import { SESSION_COOKIE } from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function runtimeEnv(name: string, fallback = ""): string {
  // Bracket access so `next build` does not bake the value into the image.
  const value = process.env[name];
  return (value ?? fallback).trim();
}

// proxy ภายในใช้ BACKEND_URL (เช่น http://api:8000) — URL ที่ส่งให้เบราว์เซอร์ต้องเป็นโดเมนสาธารณะ
function backendUrl(): string {
  return runtimeEnv("BACKEND_URL", "http://localhost:8000").replace(/\/+$/, "");
}

function publicBackendUrl(): string {
  return (runtimeEnv("PUBLIC_BACKEND_URL") || backendUrl()).replace(/\/+$/, "");
}

// บน Vercel อัปโหลดตรงเสมอ บนเครื่องตัวเองผ่าน proxy ได้ (ตั้ง DIRECT_UPLOAD=1/0 เพื่อบังคับ)
function directUpload(): boolean {
  const explicit = process.env["DIRECT_UPLOAD"];
  if (explicit !== undefined && explicit.trim() !== "") return explicit.trim() === "1";
  return Boolean(process.env["VERCEL"]);
}

const TTL_SEC = 15 * 60;
// ปลายทางที่รับไฟล์อัปโหลดได้ (งาน ไทม์ไลน์และไฟล์สื่อของไทม์ไลน์ เสียงในคลัง เสียงอารมณ์ และรูปของเสียงในคลัง)
const PATHS = /^(jobs|timeline|jobs\/[0-9a-f]{12}\/timeline\/media|voices|voices\/[0-9a-f]{12}\/(moods|image))$/;

/** id ผู้ใช้ของคุกกี้นี้ (ระบบบัญชีปิดอยู่หรือยังไม่ล็อกอิน = "") ใส่ในตั๋วให้ API รู้ว่างานเป็นของใคร */
async function userId(req: Request): Promise<string> {
  const token = req.headers.get("cookie")?.match(new RegExp(`(?:^|; )${SESSION_COOKIE}=([^;]+)`))?.[1];
  if (!token) return "";
  try {
    const res = await fetch(`${backendUrl()}/auth/me`, {
      headers: { "x-api-key": runtimeEnv("API_KEY"), "x-user-token": token, "ngrok-skip-browser-warning": "1" }, cache: "no-store",
    });
    return res.ok ? ((await res.json()) as { id: string }).id : "";
  } catch {
    return "";
  }
}

export async function GET(req: Request): Promise<Response> {
  if (!directUpload()) return Response.json({ url: null, token: null });
  const path = new URL(req.url).searchParams.get("path") ?? "jobs";
  if (!PATHS.test(path)) return Response.json({ detail: "ปลายทางอัปโหลดไม่ถูกต้อง" }, { status: 400 });
  const apiKey = runtimeEnv("API_KEY");
  let token: string | null = null;
  if (apiKey) {
    const exp = Math.floor(Date.now() / 1000) + TTL_SEC;
    const uid = await userId(req);
    const msg = uid ? `upload:${exp}:${uid}` : `upload:${exp}`;
    token = `${uid ? `${exp}.${uid}` : exp}.${createHmac("sha256", apiKey).update(msg).digest("hex")}`;
  }
  return Response.json({ url: `${publicBackendUrl()}/${path}`, token }, { headers: { "cache-control": "no-store" } });
}
