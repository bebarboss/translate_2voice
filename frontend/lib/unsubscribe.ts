// แมปผล GET/POST /notifications/unsubscribe เป็นสถานะของหน้า
// ไม่รับโทเคนเข้าฟังก์ชันแมป และไม่คืนโทเคน หน้าเว็บห้ามแสดงหรือบันทึกโทเคน

/** เส้นทางเดียวของคำขออ่านชนิดและยกเลิกรับอีเมล */
export const UNSUBSCRIBE_PATH = "/notifications/unsubscribe";

export const CONFIRM_TITLE = "ปิดการรับอีเมลนี้?";
export const CONFIRM_BODY = "กดยืนยันเมื่อต้องการหยุดรับอีเมลชนิดนี้ หน้านี้จะยังไม่ปิดให้จนกว่าคุณจะกดปุ่ม";
export const CONFIRM_BUTTON = "ยืนยันว่าไม่รับอีเมลนี้แล้ว";
export const GENERIC_CATEGORY = "อีเมลแจ้งเตือนงาน";
export const GENERIC_HINT = "จะทราบชนิดที่ปิดได้หลังยืนยัน";
export const EXPIRED_TITLE = "ลิงก์นี้หมดอายุแล้ว";
export const EXPIRED_BODY = "ลิงก์ยกเลิกมีอายุจำกัด ไม่มีการเปลี่ยนแปลงการตั้งค่า ไปเปิดหรือปิดอีเมลได้จากหน้าบัญชี";
export const EXPIRED_BUTTON = "ไปที่การตั้งค่าอีเมล";
export const INVALID_TITLE = "ลิงก์ไม่ถูกต้อง";
export const INVALID_BODY = "ลิงก์นี้อาจถูกใช้ผิดหรือไม่สมบูรณ์ ไม่มีการเปลี่ยนแปลงการตั้งค่าของคุณ";
export const INVALID_BUTTON = "เข้าสู่ระบบเพื่อตั้งค่าอีเมล";
export const SUCCESS_TITLE = "ปิดการรับอีเมลนี้แล้ว";
export const SUBMITTING_TITLE = "กำลังปิดการรับอีเมล…";
export const ERROR_TITLE = "ดำเนินการไม่สำเร็จ";
export const ERROR_BODY = "ระบบบันทึกไม่สำเร็จในตอนนี้ การตั้งค่ายังไม่เปลี่ยน";

/** ป้ายชนิด ต้องตรงกับ EMAIL_PREF_LABEL */
const CATEGORY_LABEL: Record<string, string> = {
  job_review: "รอตรวจบท",
  job_done: "พากย์เสร็จ",
  job_failed: "งานไม่สำเร็จ",
  credits_low: "เครดิตใกล้หมด",
};

export type UnsubscribePreviewState =
  | { state: "confirm"; category: string | null }
  | { state: "invalid" }
  | { state: "expired" };

export type UnsubscribePostState =
  | { state: "success"; category: string }
  | { state: "invalid" }
  | { state: "expired" }
  | { state: "retry" };

export function readUnsubscribeToken(value: string | null | undefined): string {
  return typeof value === "string" ? value.trim() : "";
}

export function categoryLabel(category: string): string | null {
  return CATEGORY_LABEL[category] ?? null;
}

/** บรรทัดบนหน้ายืนยันเมื่อรู้ชนิดแล้ว ไม่รู้ชนิดใช้ข้อความกลาง */
export function confirmCategoryLine(category: string | null): string {
  const label = category ? categoryLabel(category) : null;
  return label ? `ยกเลิกอีเมล ${label}` : GENERIC_CATEGORY;
}

/**
 * GET อ่านอย่างเดียว
 * 200 {category} = หน้ายืนยันพร้อมชื่อชนิด
 * 400 = ลิงก์ไม่ถูกต้อง, 410 = หมดอายุ
 * 404 หรือล้มเหลวอย่างอื่น = หน้ายืนยันแบบไม่ระบุชนิด (แบ็กเอนด์ยังไม่ขึ้น)
 */
export function mapUnsubscribePreview(status: number, body: unknown): UnsubscribePreviewState {
  if (status === 400) return { state: "invalid" };
  if (status === 410) return { state: "expired" };
  if (status === 200) {
    const category = readCategory(body);
    return { state: "confirm", category };
  }
  return { state: "confirm", category: null };
}

/**
 * POST ยกเลิกจริง
 * 200 {ok:true, category} = สำเร็จ
 * 400 = ลิงก์ไม่ถูกต้องหรือถูกแก้ไข, 401 = ใช้ลิงก์ไม่ได้
 * 410 = หมดอายุ
 * ที่เหลือให้กดลองใหม่ โดยยังไม่เปลี่ยนการตั้งค่า
 */
export function mapUnsubscribeResponse(status: number, body: unknown): UnsubscribePostState {
  if (status === 200 && isSuccessBody(body)) return { state: "success", category: body.category };
  if (status === 400 || status === 401) return { state: "invalid" };
  if (status === 410) return { state: "expired" };
  return { state: "retry" };
}

function readCategory(body: unknown): string | null {
  if (!isRecord(body) || typeof body.category !== "string") return null;
  const category = body.category.trim();
  return category || null;
}

function isSuccessBody(body: unknown): body is { ok: true; category: string } {
  if (!isRecord(body) || body.ok !== true || typeof body.category !== "string") return false;
  return true;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
