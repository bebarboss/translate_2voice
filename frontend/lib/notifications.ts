// กติกาของกระดิ่งที่ไม่มีผลข้างเคียง: เวลาแบบสั้น, ป้าย 9+, ไอคอนตามชนิด, ลิงก์ภายใน
// คำ title/body ของแต่ละแถวมาจากเซิร์ฟเวอร์ โมดูลนี้ไม่ประกอบข้อความจาก job.error

export type BellLabel =
  | { template: "การแจ้งเตือน" }
  | { template: "การแจ้งเตือน ({n} ยังไม่อ่าน)"; n: number };

export type RelativeTime =
  | { template: "เมื่อกี้" }
  | { template: "{n} นาทีที่แล้ว" | "{n} ชั่วโมงที่แล้ว" | "{n} วันที่แล้ว"; n: number };

/** ชั้นไอคอนที่แบบกำหนดไว้ ชนิดอื่นใช้ neutral */
export type NotifIcon = "done" | "fail" | "credits" | "review" | "actor" | "neutral";

const KNOWN: Record<string, NotifIcon> = {
  job_done: "done",
  job_failed: "fail",
  credits_low: "credits",
  job_review: "review",
};

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** จำนวนเต็มที่ไม่ติดลบ ปัดเศษทิ้ง ค่าที่ไม่ใช่จำนวนนับเป็น 0 */
export function unreadCount(unread: number): number {
  if (typeof unread !== "number" || !Number.isFinite(unread)) return 0;
  return Math.max(0, Math.trunc(unread));
}

/** ข้อความบนป้ายแดง null = ไม่มีป้าย มากกว่า 9 เป็น 9+ ไม่ใช่ 99+ */
export function badgeText(unread: number): string | null {
  const n = unreadCount(unread);
  if (n <= 0) return null;
  if (n > 9) return "9+";
  return String(n);
}

/** aria-label ของปุ่ม ใช้จำนวนจริงแม้ป้ายจะเป็น 9+ ศูนย์คือ «การแจ้งเตือน» */
export function bellAriaLabel(unread: number): BellLabel {
  const n = unreadCount(unread);
  if (n > 0) return { template: "การแจ้งเตือน ({n} ยังไม่อ่าน)", n };
  return { template: "การแจ้งเตือน" };
}

/**
 * เวลาแบบสั้นจากวินาทีของเซิร์ฟเวอร์ (created_at) เทียบกับ now หน่วยวินาที
 * เมื่อกี้ / n นาทีที่แล้ว / n ชั่วโมงที่แล้ว / n วันที่แล้ว
 * เวลาในอนาคตนับเป็นเมื่อกี้
 */
export function relativeTime(createdAtSec: number, nowSec: number): RelativeTime {
  const created = typeof createdAtSec === "number" && Number.isFinite(createdAtSec) ? createdAtSec : nowSec;
  const now = typeof nowSec === "number" && Number.isFinite(nowSec) ? nowSec : created;
  const elapsed = Math.max(0, now - created);
  if (elapsed < MINUTE) return { template: "เมื่อกี้" };
  if (elapsed < HOUR) return { template: "{n} นาทีที่แล้ว", n: Math.floor(elapsed / MINUTE) };
  if (elapsed < DAY) return { template: "{n} ชั่วโมงที่แล้ว", n: Math.floor(elapsed / HOUR) };
  return { template: "{n} วันที่แล้ว", n: Math.floor(elapsed / DAY) };
}

/**
 * ไอคอนตามชนิด
 * job_done / job_failed / credits_low / job_review ตามแบบ
 * actor_* (อนุมัติ ปฏิเสธ ค่าตอบแทน) ใช้ไมค์
 * ชนิดที่ยังไม่ได้ออกแบบ รวม voice_* และใบชำระ ใช้ไอคอนกลาง
 */
export function notifIcon(kind: string): NotifIcon {
  if (typeof kind !== "string") return "neutral";
  const key = kind.trim();
  const known = KNOWN[key];
  if (known) return known;
  if (key.startsWith("actor_")) return "actor";
  return "neutral";
}

/**
 * path ในแอปเท่านั้น สำหรับ next/link
 * ปฏิเสธ URL เต็ม, protocol-relative, backslash, และอักขระควบคุม
 */
export function internalNotifPath(link: string): string | null {
  if (typeof link !== "string") return null;
  const value = link.trim();
  if (value.length === 0 || value.length > 2048) return null;
  if (!value.startsWith("/") || value.startsWith("//")) return null;
  if (value.includes("\\") || value.includes("//")) return null;
  if (value.includes(":")) return null;
  if (/[\u0000-\u001F\u007F\s]/.test(value)) return null;
  return value;
}
