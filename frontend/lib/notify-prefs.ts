// การตั้งค่าอีเมลแจ้งเตือน: รวมคำตอบ GET/PUT /auth/notify-prefs และตัดสินใจถอยไปสวิตช์เดียวเมื่อ API ยังไม่ขึ้น

export const EMAIL_PREF_KINDS = ["job_review", "job_done", "job_failed", "credits_low"] as const;
export type EmailPrefKind = (typeof EMAIL_PREF_KINDS)[number];
export type EmailPrefs = Record<EmailPrefKind, boolean>;
export type EmailPrefPatch = Partial<EmailPrefs>;

/** ค่าเริ่มต้นตรงกับ users.notify_email ที่เปิดไว้ (ปิดเองได้) */
export const EMAIL_PREF_DEFAULTS: EmailPrefs = {
  job_review: true,
  job_done: true,
  job_failed: true,
  credits_low: true,
};

export const EMAIL_PREF_LABEL: Record<EmailPrefKind, string> = {
  job_review: "รอตรวจบท",
  job_done: "พากย์เสร็จ",
  job_failed: "งานไม่สำเร็จ",
  credits_low: "เครดิตใกล้หมด",
};

export const EMAIL_PREF_DESC: Record<EmailPrefKind, string> = {
  job_review: "แจ้งเมื่อแปลเสร็จและรอคุณตรวจบทก่อนพากย์",
  job_done: "แจ้งเมื่องานพากย์เสร็จ พร้อมลิงก์ไปดูผลและดาวน์โหลด",
  job_failed: "แจ้งเมื่องานทำไม่สำเร็จ และบอกว่าเครดิตขั้นถอดเสียงที่ไม่สำเร็จคืนให้อัตโนมัติ",
  credits_low: "แจ้งเมื่อยอดที่ใช้ได้เหลือไม่เกิน 1.00 เครดิต จะเตือนอีกครั้งเมื่อยอดกลับไปอย่างน้อย 2.00 แล้วลดลงอีก",
};

export const PREF_SAVED = "บันทึกการตั้งค่าแล้ว";
export const PREF_SAVE_ERROR = "บันทึกไม่สำเร็จ ลองอีกครั้ง";
export const PREF_SAVE_INVALID = "บันทึกไม่สำเร็จ ค่าที่ส่งไม่ถูกต้อง ไม่มีการเปลี่ยนแปลง (รหัส 422)";
export const LEGACY_NOTIFY_DESC = "แจ้งทางอีเมลเมื่องานรอตรวจบท พากย์เสร็จ ไม่สำเร็จ หรือเครดิตใกล้หมด";

export type PrefSaveNotice = { role: "status" | "alert"; text: string };

export const EMAIL_PREFS_LOAD_ERROR = {
  title: "โหลดการตั้งค่าอีเมลไม่สำเร็จ",
  description: "เซิร์ฟเวอร์ขัดข้องชั่วคราว การตั้งค่าอีเมลของคุณยังอยู่ครบ ลองใหม่อีกครั้งในอีกสักครู่",
} as const;

const ALWAYS_ON_GROUPS: { id: string; kinds: string[]; label: string; desc: string; note: string }[] = [
  {
    id: "actor_review",
    kinds: ["actor_approved", "actor_rejected", "voice_approved", "voice_rejected", "actor", "voice_actor"],
    label: "ผลใบสมัครและผลตรวจเสียงนักพากย์",
    desc: "ส่งเสมอเพราะเป็นเรื่องบัญชี",
    note: "ส่งเสมอ · เรื่องบัญชี",
  },
  {
    id: "payout",
    kinds: ["actor_paid", "payout"],
    label: "ค่าตอบแทนนักพากย์",
    desc: "ส่งเสมอเพื่อเป็นหลักฐานการโอน",
    note: "ส่งเสมอ · หลักฐานการโอน",
  },
  {
    id: "payment",
    kinds: ["payment", "payment_receipt", "billing", "receipt", "money"],
    label: "ใบยืนยันการชำระเงิน",
    desc: "ส่งเสมอเพื่อเป็นหลักฐานการชำระเงิน",
    note: "ส่งเสมอ · หลักฐานการชำระ",
  },
];

export type LockedRow = { id: string; label: string; desc: string; note: string };

export type NotifyPrefs = {
  email: EmailPrefs;
  /** ชนิดที่ปิดไม่ได้ รวมชนิดที่ซ้ำกับสวิตช์สี่ตัว (ถ้ารายการนั้นโผล่มา จะล็อกสวิตช์นั้นไว้) */
  always_on: string[];
  /** ชนิดที่ไม่มีสวิตช์ของตัวเอง แสดงเป็นแถวล็อกเพิ่ม */
  locked: string[];
};

export type LoadedNotifyPrefs =
  | { mode: "granular"; prefs: NotifyPrefs }
  | { mode: "legacy" }
  | { mode: "error" };

export type SettledPrefs =
  | { ok: true; prefs: NotifyPrefs }
  | { ok: false; email: EmailPrefs; error: typeof PREF_SAVE_ERROR };

const KIND_SET = new Set<string>(EMAIL_PREF_KINDS);

export function isEmailPrefKind(kind: string): kind is EmailPrefKind {
  return KIND_SET.has(kind);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** ป้ายของอีเมลที่ปิดไม่ได้ ไม่แสดงคีย์ภายในถ้ายังไม่มีคำแปล */
export function alwaysOnLabel(kind: string): string {
  for (const group of ALWAYS_ON_GROUPS) {
    if (group.kinds.includes(kind)) return group.label;
  }
  const text = kind.trim();
  if (/[\u0E00-\u0E7F]/.test(text)) return text;
  return "อีเมลที่ปิดไม่ได้";
}

/** รวมชนิด always_on ที่เป็นเรื่องเดียวกันให้เหลือแถวล็อกแถวเดียว */
export function lockedRows(alwaysOn: string[]): LockedRow[] {
  const remaining = new Set(alwaysOn.filter((kind) => !isEmailPrefKind(kind)));
  const rows: LockedRow[] = [];
  for (const group of ALWAYS_ON_GROUPS) {
    if (!group.kinds.some((kind) => remaining.has(kind))) continue;
    for (const kind of group.kinds) remaining.delete(kind);
    rows.push({ id: group.id, label: group.label, desc: group.desc, note: group.note });
  }
  for (const kind of alwaysOn) {
    if (!remaining.has(kind)) continue;
    remaining.delete(kind);
    rows.push({ id: kind, label: alwaysOnLabel(kind), desc: "ส่งเสมอ ปิดไม่ได้", note: "ส่งเสมอ" });
  }
  return rows;
}

/** 200 = บันทึกแล้ว, 422 = ค่าที่ส่งไม่ถูกและไม่มีการเปลี่ยน, ที่เหลือ = ลองใหม่ */
export function prefSaveNotice(status: number): PrefSaveNotice {
  if (status === 200) return { role: "status", text: PREF_SAVED };
  if (status === 422) return { role: "alert", text: PREF_SAVE_INVALID };
  return { role: "alert", text: PREF_SAVE_ERROR };
}

/** เนื้อ PUT ทีละตัว เช่น { job_done: false } ไม่ส่งคีย์ที่เซิร์ฟเวอร์ไม่รู้จัก */
export function emailPrefPatch(kind: EmailPrefKind, on: boolean): EmailPrefPatch {
  return { [kind]: on };
}

export function optimisticEmailPrefs(email: EmailPrefs, kind: EmailPrefKind, on: boolean): EmailPrefs {
  return { ...email, [kind]: on };
}

/** แปลงร่าง GET/PUT คีย์อีเมลที่ไม่รู้จักถูกทิ้ง ชนิดใน always_on ถูกบังคับเปิด */
export function parseNotifyPrefs(body: unknown): NotifyPrefs | null {
  if (!isRecord(body) || !isRecord(body.email) || !Array.isArray(body.always_on)) return null;
  const email: EmailPrefs = { ...EMAIL_PREF_DEFAULTS };
  for (const kind of EMAIL_PREF_KINDS) {
    const value = body.email[kind];
    if (value === undefined) continue;
    if (typeof value !== "boolean") return null;
    email[kind] = value;
  }
  const always: string[] = [];
  const seen = new Set<string>();
  for (const item of body.always_on) {
    if (typeof item !== "string") return null;
    const key = item.trim();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    always.push(key);
  }
  for (const kind of EMAIL_PREF_KINDS) {
    if (seen.has(kind)) email[kind] = true;
  }
  return {
    email,
    always_on: always,
    locked: always.filter((kind) => !KIND_SET.has(kind)),
  };
}

/**
 * 200 ที่อ่านได้ = สวิตช์แยกชนิด
 * 404 = แบ็กเอนด์ยังไม่มี /auth/notify-prefs ให้ใช้สวิตช์ notify_email เดิม
 * อื่น ๆ = โหลดไม่สำเร็จ
 */
export function loadNotifyPrefs(status: number, body: unknown): LoadedNotifyPrefs {
  if (status === 404) return { mode: "legacy" };
  if (status !== 200) return { mode: "error" };
  const prefs = parseNotifyPrefs(body);
  return prefs ? { mode: "granular", prefs } : { mode: "error" };
}

/** คำตอบ PUT ที่อ่านได้ทับค่าเดิม ที่อ่านไม่ได้ให้กลับไปค่าก่อนกด */
export function settlePrefToggle(snapshot: EmailPrefs, body: unknown): SettledPrefs {
  const loaded = loadNotifyPrefs(200, body);
  if (loaded.mode !== "granular") return { ok: false, email: snapshot, error: PREF_SAVE_ERROR };
  return { ok: true, prefs: loaded.prefs };
}
