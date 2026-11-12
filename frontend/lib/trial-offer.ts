/** สถานะปุ่มรับแพ็กทดลองบนหน้าโปรโมชัน ใช้แพ็กที่ยังไม่หมดอายุ (subscription) และ trial_available */

export const ACTIVE_PLAN_NOTE = "คุณมีแพ็กเกจที่ใช้งานอยู่แล้ว";
export const ACTIVE_PLAN_KEPT = "คุณมีแพ็กเกจที่ใช้งานอยู่แล้ว แพ็กเกจเดิมไม่เปลี่ยนแปลง";

export type TrialOffer = "claim" | "using-trial" | "active-plan" | "claimed";

export function trialOffer(
  sub: { plan_id: string } | null | undefined,
  trialAvailable: boolean | undefined,
): TrialOffer {
  if (sub && sub.plan_id !== "trial") return "active-plan";
  if (sub?.plan_id === "trial") return "using-trial";
  if (!trialAvailable) return "claimed";
  return "claim";
}

/** 409 ตอนรับทดลองทับแพ็กที่ยังใช้: ข้อความที่เป็นมิตร และแพ็กเดิมไม่เปลี่ยน
 *  409 "รับไปแล้ว" คืน null ให้หน้าเว็บแสดงข้อความจาก API */
export function trialClaimNotice(
  status: number,
  detail: string,
  sub: { plan_id: string } | null | undefined,
): string | null {
  if (status !== 409) return null;
  const activePaid = !!sub && sub.plan_id !== "trial";
  const blockedOverwrite = detail.includes("หมดอายุ") || detail.includes("ทับ");
  if (activePaid || blockedOverwrite) return ACTIVE_PLAN_KEPT;
  return null;
}
