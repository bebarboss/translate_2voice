import type { Gender, Job, JobStatus, Mood, TargetLang } from "./api";

export const LANGS: { code: string; label: string }[] = [
  { code: "zh", label: "จีน" },
  { code: "en", label: "อังกฤษ" },
  { code: "ko", label: "เกาหลี" },
  { code: "ja", label: "ญี่ปุ่น" },
  { code: "yue", label: "จีนกวางตุ้ง" },
  { code: "vi", label: "เวียดนาม" },
  { code: "id", label: "อินโดนีเซีย" },
  { code: "hi", label: "ฮินดี" },
  { code: "es", label: "สเปน" },
  { code: "fr", label: "ฝรั่งเศส" },
  { code: "th", label: "ไทย" },
];

export const TARGET_LABEL: Record<TargetLang, string> = { th: "ไทย", en: "อังกฤษ" };

export function langName(code: string | null | undefined): string {
  if (!code) return "—";
  return LANGS.find((l) => l.code === code)?.label ?? code;
}

export const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "รอคิว",
  running: "กำลังทำ",
  awaiting_review: "รอตรวจบท",
  done: "เสร็จแล้ว",
  failed: "ล้มเหลว",
  cancelled: "ยกเลิกแล้ว",
};

export const STAGE_LABEL: Record<string, string> = {
  queued: "รอคิว",
  download: "ดาวน์โหลดคลิปจากลิงก์",
  extract_audio: "ดึงเสียงออกจากวิดีโอ",
  separate_vocals: "แยกเสียงพูดกับเพลง",
  diarize: "แยกว่าใครพูดตอนไหน",
  transcribe: "ถอดเสียงและตรวจภาษา",
  translate: "แปลบทพากย์",
  fit_lengths: "ปรับบทให้พอดีเวลา",
  analyzed: "เตรียมบทเสร็จ",
  awaiting_review: "รอตรวจบท",
  tts: "พากย์เสียงทีละประโยค",
  mix: "ผสมเสียงพากย์กับเพลง",
  mux_video: "รวมเสียงเข้ากับวิดีโอ",
  burn_subs: "ฝังซับลงวิดีโอ",
  done: "เสร็จแล้ว",
  cancelling: "กำลังยกเลิก",
  cancelled: "ยกเลิกแล้ว",
};

export function stageLabel(stage: string): string {
  return STAGE_LABEL[stage] ?? stage;
}

/** ขั้นย่อยของแต่ละขั้นใหญ่ ใช้แสดงในหน้ากำลังประมวลผล */
export function stepsFor(job: Job): string[] {
  if (job.phase === "render") return ["burn_subs"];
  if (job.phase === "synthesize") {
    return ["tts", "mix", "mux_video", ...(job.burn_subs ? ["burn_subs"] : [])];
  }
  return [
    ...(job.source_url ? ["download"] : []),
    "extract_audio", "separate_vocals", "diarize", "transcribe", "translate", "fit_lengths",
  ];
}

export function fmtTime(sec: number): string {
  const s = Math.max(0, sec);
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${String(m).padStart(2, "0")}:${r.toFixed(1).padStart(4, "0")}`;
}

export function fmtDuration(sec: number | null | undefined): string {
  if (sec == null) return "—";
  const total = Math.round(sec);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function fmtWhen(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const time = d.toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return `วันนี้ ${time}`;
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `เมื่อวาน ${time}`;
  return `${d.toLocaleDateString("th-TH", { day: "numeric", month: "short" })} ${time}`;
}

/** ชื่อตัวละคร: ชื่อที่ผู้ใช้ตั้ง ไม่มีใช้ "ตัวละคร N" */
export function speakerLabel(speaker: string, names?: Record<string, string>): string {
  if (names?.[speaker]) return names[speaker];
  const n = Number(speaker.replace(/\D/g, ""));
  return n ? `ตัวละคร ${n}` : speaker;
}

const SPEAKER_COLORS = ["#6AB0FF", "#4FD1B5", "#C99BFF", "#F5C27A", "#FF8FA3", "#9BE06A", "#7FD3F5", "#E0A0FF"];

export function speakerColor(speaker: string, all: string[]): string {
  const i = Math.max(0, all.indexOf(speaker));
  return SPEAKER_COLORS[i % SPEAKER_COLORS.length];
}

/** ประมาณเวลาพูด ไทยนับจากตัวอักษร (ไม่นับสระบนล่างและวรรณยุกต์) อังกฤษนับจากคำ */
export function estimateSeconds(text: string, lang: TargetLang): number {
  if (lang === "en") return text.trim().split(/\s+/).filter(Boolean).length / 2.6;
  const base = Array.from(text).filter((ch) => !/\s/.test(ch) && !/\p{Mn}/u.test(ch)).length;
  return base / 11;
}

export const GENDER_LABEL: Record<Gender, string> = { male: "ชาย", female: "หญิง", "": "ไม่ระบุ" };

export const MOOD_LABEL: Record<Mood, string> = {
  angry: "โกรธ/ตะโกน", sad: "เศร้า", happy: "ดีใจ/ตื่นเต้น", whisper: "กระซิบ/เบา", scared: "ตกใจ/กลัว",
};
export const MOODS = Object.keys(MOOD_LABEL) as Mood[];

/** สตางค์ → "1,234 บาท" (มีเศษสตางค์แสดงทศนิยม) */
export const fmtBaht = (satang: number) =>
  `${(satang / 100).toLocaleString("th-TH", { minimumFractionDigits: satang % 100 ? 2 : 0, maximumFractionDigits: 2 })} บาท`;

export const TONES = ["ทุ้มลึก", "นุ่มนวล", "สดใส", "แหลม", "หนักแน่น", "อ่อนโยน", "แหบ", "เสียงเด็ก", "เสียงผู้สูงอายุ"];

export const VOICE_STAGE_LABEL: Record<string, string> = {
  queued: "รอคิว",
  clean: "ทำความสะอาดเสียง",
  transcribe: "ถอดข้อความ",
  trim: "ตัดท่อนที่ชัดที่สุด",
  measure: "วัดโทนเสียง",
};

export function isActive(job: Job): boolean {
  return job.status === "queued" || job.status === "running";
}
