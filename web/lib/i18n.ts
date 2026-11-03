// ภาษาของหน้าเว็บ (ไทย / อังกฤษ) และธีม (มืด / สว่าง / ตามเครื่อง) เก็บในคุกกี้ให้หน้าเว็บฝั่งเซิร์ฟเวอร์รู้ตั้งแต่โหลดแรก
// ข้อความในโค้ดเขียนเป็นภาษาไทย ห่อด้วย tx("...") ภาษาอังกฤษค้นจากพจนานุกรม EN (ไม่มีคำแปล = แสดงภาษาไทย)
// ตัวแปรในข้อความเขียนเป็น {ชื่อ} เช่น tx("ลบ {n} ไฟล์", { n: 3 }) อย่าเรียกระดับโมดูล (ภาษาเปลี่ยนตามคำขอ) ให้เรียกตอนแสดงผล
// ข้อความจาก API (ข้อผิดพลาด) เอกสารกฎหมาย และเนื้อหาที่ผู้ใช้พิมพ์ ไม่แปล
import { EN } from "./i18n-en";

export type Lang = "th" | "en";
export type Theme = "system" | "dark" | "light";
export const LANG_COOKIE = "lang";
export const THEME_COOKIE = "theme";
const YEAR = 365 * 24 * 3600;

// ฝั่งเบราว์เซอร์อ่านจาก <html lang> ที่เซิร์ฟเวอร์ใส่ไว้ ฝั่งเซิร์ฟเวอร์ LangInit ตั้งให้ก่อนเรนเดอร์หน้า
let current: Lang = typeof document !== "undefined" && document.documentElement.lang === "en" ? "en" : "th";

export const setCurrentLang = (lang: Lang) => { current = lang; };
export const getLang = (): Lang => current;
export const isLang = (v: string | undefined): v is Lang => v === "th" || v === "en";
export const isTheme = (v: string | undefined): v is Theme => v === "system" || v === "dark" || v === "light";

export function tx(th: string, vars?: Record<string, unknown>): string {
  const s = current === "en" ? EN[th] ?? th : th;
  return vars ? s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m)) : s;
}

/** locale สำหรับ toLocaleString (ไทยแสดงปี พ.ศ.) */
export const locale = () => (current === "en" ? "en-GB" : "th-TH");

function setCookie(name: string, value: string) {
  document.cookie = `${name}=${value}; Path=/; Max-Age=${YEAR}; SameSite=Lax`;
}

/** เปลี่ยนภาษาแล้วโหลดหน้าใหม่ (หน้าที่มีบทแก้ค้างจะถามก่อนออกตามปกติ) */
export function chooseLang(lang: Lang) {
  if (lang === current) return;
  setCookie(LANG_COOKIE, lang);
  window.location.reload();
}

export function currentTheme(): Theme {
  const v = document.documentElement.dataset.theme;
  return isTheme(v) ? v : "system";
}

/** เปลี่ยนธีมทันทีไม่ต้องโหลดใหม่ system = ไม่ใส่ data-theme ให้ CSS ตาม prefers-color-scheme */
export function chooseTheme(theme: Theme) {
  setCookie(THEME_COOKIE, theme);
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
}
