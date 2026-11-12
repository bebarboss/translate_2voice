// หน้าแอปที่ต้องล็อกอิน (เมื่อระบบบัญชีเปิด) กับหน้าสาธารณะ
// proxy ใช้รายการนี้ตัดก่อนเรนเดอร์ ส่วน client ใช้ตอน API ตอบ 401 กลางคัน
// เส้นทางที่ไม่ได้อยู่ในรายการ (รวมหน้าที่ไม่มีอยู่) ไม่ถูกพาไปหน้าเข้าสู่ระบบ

const PREFIXES = [
  "/dashboard",
  "/jobs",
  "/projects",
  "/voices",
  "/timeline",
  "/admin",
  "/account",
  "/settings",
  "/support",
  "/actors",
  "/onboarding",
];

function matchesPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

/** หน้าสมัครนักพากย์ (ไม่รวม /actor-consent และ /actors) */
export function isActorApplyPath(pathname: string): boolean {
  return pathname === "/actor" || pathname.startsWith("/actor/");
}

export function isAdminPath(pathname: string): boolean {
  return matchesPrefix(pathname, "/admin");
}

/** ต้องมี session เมื่อ AUTH เปิด หน้าแรกของสตูดิโอคือ / ไม่ใช่แลนดิ้ง /welcome */
export function isProtectedPath(pathname: string): boolean {
  if (pathname === "/") return true;
  if (isActorApplyPath(pathname)) return true;
  return PREFIXES.some((prefix) => matchesPrefix(pathname, prefix));
}

/** กัน open redirect: รับเฉพาะ path ในเว็บนี้ */
export function safeNext(value: string): string {
  if (
    !value.startsWith("/")
    || value.startsWith("//")
    || value.includes("\\")
    || value.includes("//")
    || /[\u0000-\u001F]/.test(value)
  ) return "/dashboard";
  return value;
}

/** ปลายทางเข้าสู่ระบบที่หน้ารับ Google ใช้อยู่แล้ว (query next) หน้าสมัครนักพากย์เปิดโหมดสมัคร */
export function signInPath(pathname: string, search = "", opts?: { signup?: boolean }): string {
  const params = new URLSearchParams();
  if (opts?.signup || isActorApplyPath(pathname)) params.set("mode", "signup");
  params.set("next", safeNext(`${pathname}${search}`));
  return `/login?${params.toString()}`;
}

export type AdminState = "admin" | "no" | "anon" | "unknown";

export type Gate =
  | { action: "next" }
  | { action: "redirect"; location: string };

/**
 * ตัดสินใจก่อนเรนเดอร์.
 * ไม่มีคุกกี้ที่ `/` → `/welcome` (ผู้เยี่ยมชมและบอทที่ไม่มี session เหมือนกัน)
 * หน้าแอปอื่นที่ไม่มีคุกกี้ → `/login?next=`
 * คุกกี้ถูกปฏิเสธหรือไม่ใช่ผู้ดูแลที่ `/admin` → `/login?next=` หรือ `/dashboard`
 */
export function authGate(
  pathname: string,
  search: string,
  opts: { authOn: boolean; hasSession: boolean; admin?: AdminState },
): Gate {
  if (!opts.authOn || !isProtectedPath(pathname)) return { action: "next" };
  // `/` เป็นสตูดิโอสำหรับคนที่ล็อกอินแล้ว แต่คนที่ยังไม่มี session (รวม Googlebot) ต้องเห็นแลนดิ้ง
  if (!opts.hasSession && pathname === "/") {
    return { action: "redirect", location: "/welcome" };
  }
  if (!opts.hasSession || (isAdminPath(pathname) && opts.admin === "anon")) {
    return { action: "redirect", location: signInPath(pathname, search) };
  }
  if (isAdminPath(pathname) && opts.admin === "no") {
    return { action: "redirect", location: "/dashboard" };
  }
  return { action: "next" };
}

/** 401 กลางคันบนหน้าแอป: ไปหน้าเข้าสู่ระบบแทนการค้าง "กำลังโหลด..." หน้าสาธารณะและ 404 ไม่ถูกพาไป */
export function redirectToSignIn(): void {
  if (typeof window === "undefined") return;
  const { pathname, search } = window.location;
  if (!isProtectedPath(pathname)) return;
  const dest = signInPath(pathname, search);
  if (`${pathname}${search}` === dest) return;
  window.location.replace(dest);
}
