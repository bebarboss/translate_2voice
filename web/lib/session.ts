// คุกกี้เก็บ token ผู้ใช้ (httpOnly เบราว์เซอร์อ่านไม่ได้) proxy แปลงเป็น header X-User-Token ตอนส่งต่อไปที่ API
export const SESSION_COOKIE = "dub_session";
export const SESSION_MAX_AGE = 30 * 24 * 3600; // ตรงกับ SESSION_DAYS ใน app/accounts.py

export function sessionCookie(token: string): string {
  const secure = process.env.VERCEL ? "; Secure" : "";
  return `${SESSION_COOKIE}=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${SESSION_MAX_AGE}${secure}`;
}

export const clearSessionCookie = `${SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`;
