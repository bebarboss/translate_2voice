// ออกตั๋วให้เบราว์เซอร์อัปโหลดไฟล์ตรงไปที่ API (ผ่าน ngrok) ไม่ผ่าน proxy
// เพราะ Vercel รับ body ได้ไม่เกิน 4.5 MB ตั๋วเป็น HMAC ของ API_KEY ที่หมดอายุเอง คีย์จริงไม่หลุดไปเบราว์เซอร์
import { createHmac } from "node:crypto";
import { SESSION_COOKIE } from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const API_KEY = process.env.API_KEY ?? "";
// บน Vercel อัปโหลดตรงเสมอ บนเครื่องตัวเองผ่าน proxy ได้ (ตั้ง DIRECT_UPLOAD=1/0 เพื่อบังคับ)
const DIRECT = (process.env.DIRECT_UPLOAD ?? (process.env.VERCEL ? "1" : "0")) === "1";
const TTL_SEC = 15 * 60;
// ปลายทางที่รับไฟล์อัปโหลดได้ (งาน เสียงในคลัง และเสียงอารมณ์ของเสียงในคลัง)
const PATHS = /^(jobs|voices|voices\/[0-9a-f]{12}\/moods)$/;

/** id ผู้ใช้ของคุกกี้นี้ (ระบบบัญชีปิดอยู่หรือยังไม่ล็อกอิน = "") ใส่ในตั๋วให้ API รู้ว่างานเป็นของใคร */
async function userId(req: Request): Promise<string> {
  const token = req.headers.get("cookie")?.match(new RegExp(`(?:^|; )${SESSION_COOKIE}=([^;]+)`))?.[1];
  if (!token) return "";
  try {
    const res = await fetch(`${BACKEND}/auth/me`, {
      headers: { "x-api-key": API_KEY, "x-user-token": token, "ngrok-skip-browser-warning": "1" }, cache: "no-store",
    });
    return res.ok ? ((await res.json()) as { id: string }).id : "";
  } catch {
    return "";
  }
}

export async function GET(req: Request): Promise<Response> {
  if (!DIRECT) return Response.json({ url: null, token: null });
  const path = new URL(req.url).searchParams.get("path") ?? "jobs";
  if (!PATHS.test(path)) return Response.json({ detail: "ปลายทางอัปโหลดไม่ถูกต้อง" }, { status: 400 });
  let token: string | null = null;
  if (API_KEY) {
    const exp = Math.floor(Date.now() / 1000) + TTL_SEC;
    const uid = await userId(req);
    const msg = uid ? `upload:${exp}:${uid}` : `upload:${exp}`;
    token = `${uid ? `${exp}.${uid}` : exp}.${createHmac("sha256", API_KEY).update(msg).digest("hex")}`;
  }
  return Response.json({ url: `${BACKEND}/${path}`, token }, { headers: { "cache-control": "no-store" } });
}
