// คลิปตัวอย่าง "ฟังตัวอย่าง" (ก่อน/หลังพากย์) บนหน้า /welcome
// รายการว่าง = ซ่อนทั้งส่วน ใส่ได้ 2–3 คลิป (เกินจากนั้นตัดทิ้ง)
//
// วิธีเพิ่มคลิป:
// 1) วางไฟล์เสียงไว้ที่ public/brand/demo/ เช่น public/brand/demo/anime-before.mp3
//    (ต้องเป็นไฟล์ในเว็บนี้เอง: CSP media-src อนุญาตแค่ 'self' และ /brand/ ไม่ผ่าน proxy ตรวจล็อกอิน)
// 2) เพิ่มรายการด้านล่าง ข้อความใส่ได้ทั้งแบบเดียว (ไทย) หรือ { th, en }
//
//   {
//     title: { th: "อนิเมะ: ฉากทะเลาะในห้องเรียน", en: "Anime: classroom argument" },
//     before: "/brand/demo/anime-before.mp3",
//     after: "/brand/demo/anime-after.mp3",
//     caption: { th: "ญี่ปุ่น → ไทย · 3 ตัวละคร", en: "Japanese → Thai · 3 characters" },
//   },
//
// ใช้เฉพาะคลิปที่มีสิทธิ์เผยแพร่ และเสียงที่เจ้าของอนุญาตเท่านั้น

export type Localized = string | { th: string; en?: string };

export type DemoClip = {
  title: Localized;
  /** เสียงต้นฉบับก่อนพากย์ */
  before: string;
  /** เสียงหลังพากย์ไทย */
  after: string;
  caption?: Localized;
};

export const DEMO_CLIPS: DemoClip[] = [];

export const MAX_DEMO_CLIPS = 3;

/** เลือกข้อความตามภาษา ไม่มีอังกฤษ = ใช้ไทย */
export function pickLang(text: Localized | undefined, lang: "th" | "en"): string {
  if (!text) return "";
  if (typeof text === "string") return text;
  return (lang === "en" ? text.en : undefined) || text.th;
}

/** คลิปที่แสดงได้จริง: ต้องมีชื่อและเสียงทั้งก่อน/หลัง เป็น path ในเว็บนี้ (/... ไม่ใช่ //...) */
export function visibleDemoClips(clips: readonly DemoClip[] = DEMO_CLIPS): DemoClip[] {
  const local = (u: string) => typeof u === "string" && u.startsWith("/") && !u.startsWith("//");
  return clips
    .filter((c) => pickLang(c.title, "th").trim() && local(c.before) && local(c.after))
    .slice(0, MAX_DEMO_CLIPS);
}
