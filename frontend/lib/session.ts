// คุกกี้เก็บ token ผู้ใช้ (httpOnly เบราว์เซอร์อ่านไม่ได้) proxy แปลงเป็น header X-User-Token ตอนส่งต่อไปที่ API
export const SESSION_COOKIE = "dub_session";
export const SESSION_MAX_AGE = 30 * 24 * 3600; // ตรงกับ SESSION_DAYS ใน app/accounts.py

function cookieSecureSuffix(): string {
  // Bracket access so Next does not inline the value at build time.
  const flag = (process.env["COOKIE_SECURE"] ?? "").trim().toLowerCase();
  const on = flag === "1" || flag === "true" || Boolean(process.env["VERCEL"]);
  return on ? "; Secure" : "";
}

export function sessionCookie(token: string): string {
  return `${SESSION_COOKIE}=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${SESSION_MAX_AGE}${cookieSecureSuffix()}`;
}

export function clearSessionCookie(): string {
  return `${SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0${cookieSecureSuffix()}`;
}
