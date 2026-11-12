import { redirectToSignIn } from "@/lib/auth-routes";
import { tx } from "@/lib/i18n";
// ชนิดข้อมูลและฟังก์ชันเรียก Dubbing API (ผ่าน proxy /api ของ Next.js)

export type JobStatus = "queued" | "running" | "awaiting_review" | "done" | "failed" | "cancelled";
export type TargetLang = "th" | "en";
export type SubPosition = "bottom" | "top";

export interface SubtitleStyle {
  font: string;
  color: string;
  outline_color: string;
  size: number;
  position: SubPosition;
}

export interface Job {
  id: string;
  status: JobStatus;
  stage: string;
  progress: number;
  phase: "analyze" | "synthesize" | "render" | string;
  filename: string;
  input_path: string;
  source_url: string | null;
  source_lang: string | null;
  detected_lang: string | null;
  target_lang: TargetLang;
  num_speakers: number | null;
  review: boolean;
  genre?: string;
  glossary?: string;
  burn_subs: boolean;
  sub_style: SubtitleStyle | null;
  speakers: string[];
  duration: number | null;
  synth_stats: { redubbed: number; reused: number; unclear?: number; repaired?: number; quality_ok?: boolean } | null;
  voice_map: Record<string, string>;
  queue_position?: number | null; // ลำดับคิว (เฉพาะตอนรอคิว)
  speaker_names?: Record<string, string>; // ชื่อที่ผู้ใช้ตั้งให้ตัวละคร
  library?: boolean; // งานเก็บเสียงเข้าคลัง: แยกผู้พูดและถอดเสียงอย่างเดียว
  saved_voices?: Record<string, string>; // ตัวละคร → id เสียงในคลังที่บันทึกจากงานนี้
  timeline?: boolean; // งานไทม์ไลน์จากโปรแกรมตัดต่อ (ไม่มีวิดีโอ ผลลัพธ์ส่งออกเป็น XML + เสียงแยกแทร็ก)
  watermark?: boolean; // แพ็กฟรี: มีลายน้ำ
  story?: StoryAnalysis | null; // ผลวิเคราะห์บททั้งเรื่องก่อนแปล
  project_id?: string | null;
  project_matches?: Record<string, ProjectMatch>; // ผู้พูด → ตัวละครของโปรเจกต์ที่จับคู่ด้วยลายเสียง
  error: string | null;
  /** โหมดฟรี: วันหมดอายุไฟล์บน R2 */
  expires_at?: string | null;
  share_token?: string | null;
  /** ตัดช่วงก่อนพากย์ (วินาที) */
  clip_start?: number | null;
  clip_end?: number | null;
  created_at: string;
  updated_at: string;
}

export type Gender = "male" | "female" | "";

/** ตัวละครประจำโปรเจกต์ (จำข้ามตอน) learned = มีลายเสียงไว้จับคู่ตอนถัดไปแล้ว */
export interface ProjectCharacter {
  id: string; name: string; gender: string; role: string; self: string; addresses: string;
  voice_id: string | null; pitch: number | null; samples: number; learned: boolean; updated_at: string;
}
export interface Project {
  id: string; name: string; owner: string | null; genre: string; glossary: string; speech_style: string;
  target_lang: TargetLang; characters: ProjectCharacter[]; episodes: number; created_at: string; updated_at: string;
}
/** sure = ลายเสียงตรงพอ ตั้งชื่อและเสียงให้เอง, confirmed = ผู้ใช้บันทึกเข้าโปรเจกต์แล้ว */
export interface ProjectMatch { character: string; name: string; score: number | null; sure: boolean; confirmed?: boolean }
/** ความจำคำแปล: total = บรรทัดที่จำไว้, edited = บรรทัดที่ผู้ใช้แก้ (ใช้เป็นตัวอย่าง), available = ใช้ได้ (ตารางพร้อม) */
export interface ProjectMemory {
  available: boolean; total: number; edited: number;
  items: { id: number; job_id: string; line_id: number; speaker_name: string; source: string; target: string; updated_at: string | number }[];
}
export type ProjectInput = Pick<Project, "name" | "genre" | "glossary" | "speech_style" | "target_lang">;

/** AI อ่านบทต้นฉบับทั้งเรื่องก่อนแปล: แนวเรื่อง ระดับภาษา ตัวละคร ชื่อเฉพาะ จุดที่น่าจะถอดผิด ผู้พูดที่น่าสงสัย */
export interface StoryAnalysis {
  content_type?: "continuous" | "teaser" | ""; // เรื่องต่อเนื่อง หรือทีเซอร์/รวมฉาก
  genre: string; setting: string; register: string;
  characters: { speaker: string; name: string; gender: string; role: string; self: string; addresses: string }[];
  glossary: string[];
  asr_fixes: { id: number; likely: string }[];
  speaker_doubts: { id: number; speaker?: string; note: string }[];
}

// ---- ไทม์ไลน์จากโปรแกรมตัดต่อ (POST /timeline) เวลาเป็นเฟรม timecode เป็นสตริงตามอัตราเฟรมของไทม์ไลน์
export interface TimelineClip {
  name: string; media: string; file: string | null; start: number; end: number; start_tc: string; end_tc: string;
  channel: number | null;
}
export interface TimelineTrack {
  index: number; name: string; clips: TimelineClip[]; speaker: string; enabled: boolean; duplicate_of: number | null;
  speaker_name: string; voice_id: string | null;
}
export interface TimelineInfo {
  format: string; source: string; name: string; fps: number; drop_frame: boolean; sample_rate: number;
  start_tc: string; duration_tc: string; duration: number; tracks: TimelineTrack[]; missing: string[]; warnings: string[];
}
export interface TimelineState { job: Job; timeline: TimelineInfo }
export interface TrackSetup { index: number; enabled?: boolean; speaker_name?: string; voice_id?: string | null }
export interface TimelineImport {
  fps?: number | null; dropFrame?: boolean | null; sourceLang: string; targetLang: TargetLang; genre: string;
  glossary: string; review: boolean;
}
export type TimelineFormat = "xml" | "fcpxml" | "stems" | "mix" | "srt";

// ---- บัญชีผู้ใช้ เครดิต แพ็กเกจ (เปิดหรือไม่ ดู AuthConfig) 1 เครดิต = คลิป 1 นาที (ทศนิยมได้ 2 ตำแหน่ง) เงินเป็นสตางค์
/** google_client_id ว่าง = ยังไม่ได้ตั้งปุ่มเข้าสู่ระบบด้วย Google ที่ API */
/** payment_provider: ว่าง = ยังไม่รับชำระ, mock = ทดสอบเติมทันที, slip = โอนแล้วแนบสลิป, stripe = Stripe Checkout */
export interface AuthConfig {
  auth: boolean; billing: boolean; payments: boolean; payment_provider: string; google_client_id: string;
  stripe_publishable_key?: string;
}
/** owner = ผู้ดูแลหลักจาก ADMIN_EMAILS (ถอดสิทธิ์ไม่ได้) */
export type AccountType = "personal" | "creator" | "business";
/** ข้อมูลเบื้องต้นที่ผู้ใช้กรอกหลังล็อกอินครั้งแรก (account_type ว่าง = ยังไม่กรอก) */
export interface Profile { full_name: string; phone: string; account_type: AccountType | ""; company: string; use_case: string }
export interface User {
  id: string; email: string; name: string; admin: boolean; owner: boolean; credits: number;
  profile_complete: boolean; profile: Profile;
  /** ยอมรับข้อกำหนดและนโยบายฉบับปัจจุบันแล้ว (false = ต้องยอมรับก่อนใช้งาน) */
  consent_current: boolean; marketing: boolean; notify_email: boolean;
  consent: { terms: ConsentRecord | null; privacy: ConsentRecord | null };
}
export interface ConsentRecord { version: string; at: number }
export interface LegalDoc { version: string; text: string }
export interface Legal { terms: LegalDoc; privacy: LegalDoc }
export interface ConsentChoice { terms_version: string; privacy_version: string; marketing?: boolean }
/** minutes = เครดิตแพ็กเกจต่อรอบ */
export interface Plan {
  id: string; name: string; price: number; minutes: number; days: number;
  max_clip_minutes?: number; voices?: "standard" | "all" | string;
  timeline?: boolean; watermark?: boolean; free_once?: boolean;
  available?: boolean; // false = ปิดขายชั่วคราว (อยู่ระหว่างพัฒนา)
  features?: string[];
}
export interface Entitlements {
  plan_id: string | null; plan_name: string | null; max_clip_minutes: number;
  voices: string; timeline: boolean; watermark: boolean;
  can_topup: boolean; trial_available: boolean; has_plan: boolean;
}
/** minutes_left = เครดิตแพ็กเกจที่เหลือ หมดอายุพร้อมแพ็กเกจ */
export interface Subscription { plan_id: string; minutes_left: number; started_at: number; expires_at: number }
/** credits = เครดิตเติมที่เปลี่ยน, minutes = เครดิตแพ็กเกจที่เปลี่ยน, amount = เงินที่จ่าย */
export interface LedgerEntry { kind: string; credits: number; minutes: number; amount: number; ref: string | null; note: string; created_at: number }
export interface Wallet {
  credits: number; subscription: Subscription | null; credit_price: number;
  entitlements?: Entitlements; ledger: LedgerEntry[];
}
export interface Payee { name: string; bank: string; account: string }
/** amount ของ ocr เป็นสตางค์ เท่ากับ amount ของรายการ (null = อ่านยอดไม่ได้) */
export interface SlipOcr {
  amount: number | null; ref: string | null; payer: string | null; payee: string | null;
  payee_account: string | null; transferred_at: string | null;
}
/** สถานะ: pending รอชำระ/โอน, review รอผู้ดูแล (slip), paid เติมแล้ว, rejected ไม่ผ่าน */
export interface PaymentOrder {
  id: string; status: string; amount: number; credits: number; plan_id: string | null; provider: string;
  created_at: number; paid_at: number | null; note: string; has_slip: boolean;
  payee: Payee | null; ocr: SlipOcr | null;
  checkout_url?: string | null; provider_ref?: string | null;
  email?: string; name?: string; ocr_text?: string;
}
export interface Card { id: string; brand: string; last4: string; exp_month: number; exp_year: number; created_at: number }
export interface FeedbackItem {
  id: string; user_id: string | null; email: string; name: string;
  category: "bug" | "billing" | "quality" | "feature" | "other";
  subject: string; body: string; job_id: string; status: "open" | "done";
  admin_note: string; created_at: number; resolved_at: number | null;
}
/** bonus = เครดิตฟรีเมื่อผูกบัตรครั้งแรก, provider = ผู้ให้บริการชำระเงิน (ว่าง = ยังไม่เชื่อม, mock = ทดสอบ) */
export interface Cards { cards: Card[]; bonus: number; bonus_available: boolean; provider: string }
export interface AdminUser extends User { created_at: number; subscription: Subscription | null }

export type Mood = "angry" | "sad" | "happy" | "whisper" | "scared";

/** ผลประเมินไฟล์ที่อัปโหลดทั้งไฟล์ ตอนเตรียมเสียงในคลัง */
export interface VoiceAnalysis {
  source_sec: number | null;
  speech_sec: number | null;
  windows: number | null;
  other_voices: number | null; // สัดส่วนเสียงคนอื่นที่ปนมา 0–1
  best_quality: number | null;
}

/** เสียงตัวอย่างอารมณ์หนึ่งของเสียงในคลัง (คนพากย์คนเดิม) */
export interface VoiceMood {
  mood: Mood;
  status: "processing" | "ready" | "failed";
  stage: string;
  error: string | null;
  filename: string;
  text: string;
  duration: number | null;
  quality: number | null;
  analysis?: VoiceAnalysis | null;
  review?: string | null; // เสียงอารมณ์ของนักพากย์: draft / pending / approved / rejected
  review_note?: string;
}

export interface LibraryVoice {
  id: string;
  name: string;
  gender: Gender;
  tone: string;
  description: string;
  categories: string[]; // หมวดหมู่ เช่น ละคร หนัง การ์ตูน
  image: string; // "" = ไม่มีรูป
  status: "processing" | "ready" | "failed";
  stage: string;
  error: string | null;
  filename: string;
  text: string;
  duration: number | null;
  pitch_hz: number | null;
  quality: number | null;
  analysis?: VoiceAnalysis | null;
  moods: VoiceMood[];
  actor?: string | null; // ชื่อนักพากย์ (เสียงที่นักพากย์อัดเอง)
  review?: "draft" | "pending" | "approved" | "rejected" | null; // draft = อัดแล้วยังไม่ส่งตรวจ
  review_note?: string;
  mine?: boolean; // เจ้าของเสียงนักพากย์นี้ (แก้รูป/ข้อมูลได้)
  created_at: string;
  updated_at: string;
}

// ---- นักพากย์ (เงินเป็นสตางค์ เวลาเป็น unix วินาที)
export type ActorStatus = "pending" | "approved" | "rejected" | "withdrawn";
export interface Actor {
  user_id: string; stage_name: string; gender: Gender; bio: string; contact: string; status: ActorStatus;
  note: string; created_at: number; reviewed_at: number | null;
}
/** ยอดของนักพากย์หนึ่งคนในเดือนหนึ่ง seconds = เวลาที่คิดเงิน, self_seconds = ใช้พากย์งานของตัวเอง (ไม่คิดเงิน) */
export interface UsageSummary {
  actor_id: string; month: string; stage_name: string; email: string | null; seconds: number; self_seconds: number;
  jobs: number; users: number; amount: number; paid: number; due: number;
  payee: boolean; // กรอกข้อมูลรับเงินแล้ว
  wht: number; // ภาษีหัก ณ ที่จ่ายถ้าจ่ายยอดค้างตอนนี้ (สตางค์)
}
export interface UsageRow {
  job_id: string; voice_id: string; user_id: string; job_name: string; seconds: number; lines: number;
  month: string; created_at: number; updated_at: number; payable: boolean; amount: number;
}
/** ประวัติรับเงินของนักพากย์ amount = ยอดก่อนหักภาษี, wht = ภาษีหัก ณ ที่จ่าย (โอนจริง = amount − wht)
 *  ไม่มีเลขผู้เสียภาษีหรือที่อยู่ */
export interface ActorPayout {
  id: number; month: string; amount: number; wht: number; paid_at: number;
}
/** ประวัติการจ่ายในหน้าผู้ดูแล ไม่มีเลขผู้เสียภาษีหรือที่อยู่ */
export interface AdminActorPayout {
  id: number; month: string; amount: number; wht: number; payee_name: string; note: string; paid_by: string; paid_at: number;
}
/** ข้อมูลรับค่าตอบแทน (หน้าบัญชี · เลขผู้เสียภาษีและเลขบัญชีปิดเหลือ 4 ตัวท้าย) */
export interface ActorPayment {
  payee_name: string; tax_id: string; address: string; bank: string; account_no: string; account_name: string;
  updated_at?: number;
}
export interface WhtRule { percent: number; min: number } // min เป็นสตางค์
export interface ActorMe {
  actor: Actor | null;
  consent: { version: string; accepted_at: number } | null;
  consent_current: boolean;
  consent_version: string;
  rate: number; // สตางค์ต่อนาที
  voices: LibraryVoice[];
  usage: UsageSummary[];
  payouts: ActorPayout[];
  /** id เสียง → อารมณ์ ("" = ปกติ) → จำนวนประโยคที่ถูกใช้พากย์ */
  mood_usage: Record<string, Record<string, number>>;
  payment: ActorPayment | null;
  banks: string[];
  wht: WhtRule;
}
export interface ActorConsentDoc { version: string; text: string; rate: number; items: { id: string; text: string }[] }
export interface ActorConsentRecord {
  version: string; items: string; text_hash: string; ip: string; user_agent: string; accepted_at: number; withdrawn_at: number | null;
}
export interface AdminActor extends Actor {
  email: string | null; account_name: string | null; voices: number; pending: number;
  consent_version: string | null; consent_at: number | null;
}

export interface SpeakerVoice {
  speaker: string;
  voice_id: string | null;
  pitch_hz: number | null;
  gender: Gender;
  suggestions: { voice_id: string; score: number }[];
}

export interface VoiceMeta {
  name: string;
  gender: Gender;
  tone: string;
  description: string;
  categories: string[];
  denoise?: boolean; // ลดเสียงรบกวนหลังแยกเพลง
}

/** บันทึกเสียงของตัวละครในงานลงคลัง: new = เสียงใหม่, replace = แทนเสียงตัวอย่างของ voice_id, mood = เสียงอารมณ์ของ voice_id */
export interface SpeakerSave extends VoiceMeta {
  target: "new" | "replace" | "mood";
  voice_id?: string;
  mood?: Mood;
  lines?: number[]; // id ประโยคที่ใช้ ไม่ส่ง = ทุกประโยคที่พูดคนเดียว
}

export interface Utterance {
  id: number;
  speaker: string;
  start: number;
  end: number;
  source: string;
  target: string;
  take: number;
  /** "" = ให้ระบบเลือก (ดู mood_auto), "normal" = อารมณ์ปกติ */
  mood: LineMood;
  mood_auto?: Mood | "";
  mood_auto_text?: string;
  /** ตรวจเสียงพากย์แล้วไม่ตรงบท: สิ่งที่ระบบได้ยิน และคะแนน 0–1 */
  heard?: string;
  heard_score?: number | null;
  unclear?: boolean;
  /** เหตุผลที่ AI ไม่มั่นใจ เช่น ฟังเสียงไม่ชัด / เนื้อเพลง / ชื่อเฉพาะ / บทยาวเกิน */
  unclear_reason?: string;
  /** ตรวจหลังแปลแล้วควรให้คนดู: เหตุผล */
  check_note?: string;
  ref_reading: string;
}

export type LineMood = Mood | "" | "normal";

export interface UtteranceEdit {
  id: number;
  target?: string;
  speaker?: string;
  start?: number;
  end?: number;
  take?: number;
  mood?: LineMood;
}

export interface RuntimeSettings {
  voice_gain: number;
  bgm_gain: number;
  max_speedup: number;
  f5_steps: number;
  default_target_lang: TargetLang;
  default_review: boolean;
  default_burn_subs: boolean;
  sub_font_th: string;
  sub_font_en: string;
  sub_color: string;
  sub_outline_color: string;
  sub_size: number;
  sub_position: SubPosition;
}

export interface SystemInfo {
  mock: boolean;
  gpu: string | null;
  device: string;
  models: Record<string, string>;
  keys: { hf_token: boolean; typhoon: boolean };
  queue: { running: string | null; running_jobs?: string[]; queued: number; slots?: number; light_slots?: number; user_max_jobs?: number };
  limits: { max_upload_mb: number; max_url_minutes: number };
}

export interface Fonts {
  thai: string[];
  english: string[];
}

export interface CreateOptions {
  sourceLang: string;
  targetLang: TargetLang;
  /** ว่าง/ไม่ส่ง = ให้ระบบประมาณจำนวนผู้พูดเอง */
  numSpeakers?: number | null;
  review: boolean;
  burnSubs: boolean;
  genre?: string;
  glossary?: string;
  library?: boolean;
  projectId?: string; // ส่งเข้าโปรเจกต์
  /** ตัดช่วงก่อนพากย์ (วินาที) — ไม่ส่ง = ทั้งคลิป */
  clipStart?: number | null;
  clipEnd?: number | null;
}

const BASE = "/api";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return tx("ข้อมูลไม่ถูกต้อง: {0}", { 0: detail[0].msg });
  return tx("คำขอล้มเหลว (รหัส {0})", { 0: status });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, { cache: "no-store", ...init });
  } catch {
    throw new ApiError(tx("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้"), 0);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    // session หมดหรือยังไม่ล็อกอินบนหน้าแอป → /login?next= (หน้าสาธารณะและ 404 ไม่ถูกพาไป)
    if (res.status === 401 && (body as { detail?: string } | null)?.detail === "กรุณาเข้าสู่ระบบ") {
      redirectToSignIn();
    }
    // ล็อกอินแล้วแต่ยังไม่ได้กรอกข้อมูลเบื้องต้น → หน้ากรอกข้อมูล แล้วกลับมาหน้านี้
    if (res.status === 428 && typeof window !== "undefined" && !/^\/(onboarding|login|welcome|terms|privacy|actor-consent)/.test(window.location.pathname)) {
      window.location.href = `/onboarding?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
    }
    throw new ApiError(errorMessage(res.status, body), res.status);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  try {
    return JSON.parse(text) as T;
  } catch {
    const hint = text.trim().slice(0, 120).replace(/\s+/g, " ");
    throw new ApiError(
      hint.startsWith("<") || /<!DOCTYPE|cloudflare|nginx/i.test(hint)
        ? tx("เซิร์ฟเวอร์ตอบไม่ใช่ JSON (ตรวจ BACKEND_URL / proxy)")
        : tx("อ่านคำตอบจากเซิร์ฟเวอร์ไม่ได้"),
      res.status,
    );
  }
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  authConfig: () => request<AuthConfig>("/auth/config"),
  me: () => request<User>("/auth/me"),
  /** สมัครหรือเข้าสู่ระบบด้วย ID token จากปุ่ม Google (บัญชีใหม่สร้างให้เลย) */
  googleLogin: (credential: string) => request<{ user: User }>("/auth/google", json("POST", { credential })),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  saveProfile: (body: Profile & { name?: string } & Partial<ConsentChoice>) => request<User>("/auth/profile", json("PUT", body)),
  legal: () => request<Legal>("/legal"),
  acceptConsent: (body: ConsentChoice) => request<User>("/auth/consent", json("POST", body)),
  setMarketing: (on: boolean) => request<User>("/auth/marketing", json("PUT", { on })),
  setNotify: (on: boolean) => request<User>("/auth/notify", json("PUT", { on })),
  /** ปิดบัญชีและลบข้อมูล ต้องพิมพ์อีเมลของบัญชียืนยัน ย้อนกลับไม่ได้ */
  closeAccount: (confirm: string) => request<void>("/auth/close", json("POST", { confirm })),
  backups: () => request<Backups>("/admin/backups"),
  backupNow: () => request<{ name: string; bytes: number }>("/admin/backups", { method: "POST" }),
  quality: (days = 30) => request<Quality>(`/admin/quality?days=${days}`),
  qualityLines: (days = 30, kind: QualityKind = "", limit = 50) =>
    request<QualityLine[]>(`/admin/quality/lines?days=${days}&kind=${kind}&limit=${limit}`),
  plans: () => request<{ plans: Plan[]; credit_price: number; credit_packs: number[]; card_bonus: number }>("/billing/plans"),
  wallet: () => request<Wallet>("/billing/wallet"),
  /** ประมาณเครดิตก่อนเริ่มงานจากความยาวคลิป (วินาที) */
  quoteJob: (seconds: number) =>
    request<{ seconds: number; credits: number; balance: number; remaining: number; enough: boolean }>(
      "/billing/quote", json("POST", { seconds })),
  /** ประมาณเครดิตจากลิงก์ (yt-dlp อ่านความยาว) */
  quoteUrl: (url: string) =>
    request<{ seconds: number; credits: number; balance: number; remaining: number; enough: boolean; title?: string }>(
      "/billing/quote-url", json("POST", { url })),
  /** ประมาณเครดิตพากย์ซ้ำ */
  quoteRedub: (edit_seconds: number, clip_seconds: number, free_flagged_seconds = 0) =>
    request<{ edit_seconds: number; credits: number; free: boolean; balance: number; remaining: number; enough: boolean }>(
      "/billing/quote-redub", json("POST", { edit_seconds, clip_seconds, free_flagged_seconds })),
  getShare: (token: string) => request<ShareInfo>(`/share/${encodeURIComponent(token)}`),
  listVoiceReports: (openOnly = true) =>
    request<VoiceReport[]>(`/admin/voice-reports?open_only=${openOnly ? "true" : "false"}`),
  resolveVoiceReport: (id: string, restore = true, note = "") =>
    request<{ id: string; status: string; restored: boolean }>(
      `/admin/voice-reports/${encodeURIComponent(id)}/resolve`, json("POST", { restore, note })),
  subscribe: (planId: string) => request<PaymentOrder>("/billing/subscribe", json("POST", { plan_id: planId })),
  /** รับแพ็กทดลองฟรี ครั้งเดียวต่อบัญชี */
  claimTrial: () => request<{ plan: Plan; subscription: Subscription | null; entitlements: Entitlements }>("/billing/trial", { method: "POST" }),
  cards: () => request<Cards>("/billing/cards"),
  /** token จากสคริปต์ของผู้ให้บริการชำระเงิน (เลขบัตรไม่ผ่านเซิร์ฟเวอร์เรา) */
  addCard: (token: string) => request<{ card: Card; bonus: number }>("/billing/cards", json("POST", { token })),
  removeCard: (id: string) => request<void>(`/billing/cards/${id}`, { method: "DELETE" }),
  buyCredits: (credits: number) => request<PaymentOrder>("/billing/topups", json("POST", { credits })),
  confirmPayment: (id: string) => request<PaymentOrder>(`/billing/topups/${encodeURIComponent(id)}/confirm`, { method: "POST" }),
  myPayments: () => request<PaymentOrder[]>("/billing/topups"),
  /** แนบรูปสลิป JPG/PNG ให้ Typhoon OCR อ่านยอด */
  uploadSlip: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request<PaymentOrder>(`/billing/topups/${id}/slip`, { method: "POST", body: form });
  },
  adminPayments: (status = "review") => request<PaymentOrder[]>(`/admin/payments?status=${encodeURIComponent(status)}`),
  adminApprovePayment: (id: string) => request<PaymentOrder>(`/admin/payments/${id}/approve`, { method: "POST" }),
  adminRejectPayment: (id: string, note: string) =>
    request<PaymentOrder>(`/admin/payments/${id}/reject`, json("POST", { note })),
  adminUsers: () => request<AdminUser[]>("/admin/users"),
  adminCredit: (userId: string, credits: number, note = "") =>
    request<void>(`/admin/users/${userId}/credit`, json("POST", { credits, note })),
  adminSetAdmin: (userId: string, admin: boolean) => request<void>(`/admin/users/${userId}/admin`, json("POST", { admin })),
  adminPlan: (userId: string, planId: string) => request<void>(`/admin/users/${userId}/plan`, json("POST", { plan_id: planId })),
  submitFeedback: (body: { category: string; subject: string; body: string; job_id?: string }) =>
    request<FeedbackItem>("/feedback", json("POST", body)),
  myFeedback: () => request<FeedbackItem[]>("/feedback"),
  adminFeedback: () => request<FeedbackItem[]>("/admin/feedback"),
  adminResolveFeedback: (id: string, status: "open" | "done", note = "") =>
    request<FeedbackItem>(`/admin/feedback/${encodeURIComponent(id)}`, json("POST", { status, note })),
  /** หนังสือยินยอมของนักพากย์ อ่านได้โดยไม่ต้องล็อกอิน items = ข้อที่ต้องติ๊กให้ครบ */
  actorConsent: () => request<ActorConsentDoc>("/legal/actor"),
  actorMe: () => request<ActorMe>("/actor/me"),
  actorApply: (body: { stage_name: string; gender: Gender; bio: string; contact: string; consent_version: string;
    consent_items: string[] }) =>
    request<Actor>("/actor/apply", json("POST", body)),
  actorAccept: (version: string, items: string[]) => request<void>("/actor/consent", json("POST", { version, items })),
  actorUsage: (month: string) => request<UsageRow[]>(`/actor/usage?month=${month}`),
  /** voiceId ว่าง = เสียงใหม่, มี voiceId = อัดแทนเสียงหลัก หรือเพิ่มเสียงอารมณ์ (mood) */
  actorRecord: (file: Blob, filename: string, opts: { voiceId?: string; mood?: Mood; denoise: boolean }) => {
    const form = new FormData();
    form.append("file", file, filename);
    if (opts.voiceId) form.append("voice_id", opts.voiceId);
    if (opts.mood) form.append("mood", opts.mood);
    form.append("denoise", String(opts.denoise));
    return request<LibraryVoice>("/actor/voices", { method: "POST", body: form });
  },
  actorSubmitReview: (id: string) => request<LibraryVoice>(`/actor/voices/${id}/submit-review`, { method: "POST" }),
  actorDeleteVoice: (id: string) => request<void>(`/actor/voices/${id}`, { method: "DELETE" }),
  actorWithdraw: () => request<void>("/actor/withdraw", { method: "POST" }),
  actorSavePayment: (body: ActorPayment) => request<ActorPayment>("/actor/payment", json("PUT", body)),
  adminActorPayment: (userId: string) => request<ActorPayment>(`/admin/actors/${userId}/payment`),
  adminActors: () => request<AdminActor[]>("/admin/actors"),
  adminActorConsents: (userId: string) => request<ActorConsentRecord[]>(`/admin/actors/${userId}/consents`),
  adminReviewActor: (userId: string, approve: boolean, note = "") =>
    request<void>(`/admin/actors/${userId}/review`, json("POST", { approve, note })),
  adminActorVoices: () => request<LibraryVoice[]>("/admin/actor-voices"),
  adminReviewMood: (voiceId: string, mood: Mood, approve: boolean, note = "") =>
    request<void>(`/admin/actor-voices/${voiceId}/moods/${mood}/review`, json("POST", { approve, note })),
  adminReviewVoice: (voiceId: string, approve: boolean, note = "") =>
    request<void>(`/admin/actor-voices/${voiceId}/review`, json("POST", { approve, note })),
  adminActorUsage: (month = "") =>
    request<{ rate: number; rows: UsageSummary[]; payouts: AdminActorPayout[]; wht: WhtRule }>(`/admin/actor-usage${month ? `?month=${month}` : ""}`),
  adminActorUsageRows: (userId: string, month: string) => request<UsageRow[]>(`/admin/actor-usage/${userId}?month=${month}`),
  adminPayout: (userId: string, month: string, note = "") =>
    request<{ amount: number; wht: number; net: number }>(`/admin/actor-payouts/${userId}`, json("POST", { month, note })),
  health: () => request<{ status: string; mock: boolean; queued: number }>("/health"),
  system: () => request<SystemInfo>("/system"),
  fonts: () => request<Fonts>("/fonts"),
  getSettings: () => request<RuntimeSettings>("/settings"),
  saveSettings: (patch: Partial<RuntimeSettings>) => request<RuntimeSettings>("/settings", json("PUT", patch)),

  listJobs: () => request<Job[]>("/jobs"),
  getJob: (id: string) => request<Job>(`/jobs/${id}`),
  deleteJob: (id: string) => request<void>(`/jobs/${id}`, { method: "DELETE" }),
  cancel: (id: string) => request<Job>(`/jobs/${id}/cancel`, { method: "POST" }),
  retry: (id: string) => request<{ id: string }>(`/jobs/${id}/retry`, { method: "POST" }),
  setOptions: (id: string, patch: { burn_subs?: boolean; sub_style?: SubtitleStyle | null }) =>
    request<Job>(`/jobs/${id}/options`, json("PATCH", patch)),
  render: (id: string) => request<{ id: string }>(`/jobs/${id}/render`, { method: "POST" }),

  getTranscript: (id: string) => request<Utterance[]>(`/jobs/${id}/transcript`),
  saveTranscript: (id: string, edits: UtteranceEdit[]) =>
    request<Utterance[]>(`/jobs/${id}/transcript`, json("PUT", edits)),
  splitLine: (id: string, lineId: number, at: { at?: number; pos?: number }) =>
    request<Utterance[]>(`/jobs/${id}/transcript/${lineId}/split`, json("POST", at)),
  duplicateLine: (id: string, lineId: number, body: { speaker?: string; start?: number }) =>
    request<Utterance[]>(`/jobs/${id}/transcript/${lineId}/duplicate`, json("POST", body)),
  /** เพิ่มท่อนว่างบนไทม์ไลน์ (เช่นเสียงถอดหลุด) แล้วพิมพ์บทพากย์ก่อนพากย์ใหม่ */
  addLine: (id: string, body: { speaker: string; start: number; end?: number; duration?: number; source?: string; target?: string }) =>
    request<Utterance[]>(`/jobs/${id}/transcript/lines`, json("POST", body)),
  deleteLine: (id: string, lineId: number) =>
    request<Utterance[]>(`/jobs/${id}/transcript/${lineId}`, { method: "DELETE" }),
  mergeLine: (id: string, lineId: number) =>
    request<Utterance[]>(`/jobs/${id}/transcript/${lineId}/merge`, { method: "POST" }),
  addSpeaker: (id: string) => request<Job>(`/jobs/${id}/speakers`, { method: "POST" }),
  renameSpeaker: (id: string, speaker: string, name: string) =>
    request<Job>(`/jobs/${id}/speakers/${speaker}`, json("PATCH", { name })),
  removeSpeaker: (id: string, speaker: string, into?: string) =>
    request<Job>(`/jobs/${id}/speakers/${speaker}${into ? `?into=${encodeURIComponent(into)}` : ""}`,
      { method: "DELETE" }),
  /** บันทึกเสียงของตัวละครนี้ลงคลัง (ต่อทุกประโยคที่ไม่มีคนอื่นพูดทับ แล้วเตรียมเสียงเหมือนอัปโหลดเอง) */
  speakerToLibrary: (id: string, speaker: string, body: SpeakerSave) =>
    request<LibraryVoice>(`/jobs/${id}/speakers/${speaker}/library`, json("POST", body)),
  /** id ประโยค → คะแนนความสะอาดเสียงต้นฉบับ (1–4.5) ที่วัดตอนวิเคราะห์ */
  lineQuality: (id: string) => request<Record<string, number | null>>(`/jobs/${id}/lines/quality`),
  retranslate: (id: string, body: { genre?: string; glossary?: string }) =>
    request<{ id: string }>(`/jobs/${id}/retranslate`, json("POST", body)),
  synthesize: (id: string, body?: { edit_seconds?: number; free_flagged_seconds?: number }) =>
    request<{ id: string }>(`/jobs/${id}/synthesize`, body ? json("POST", body) : { method: "POST" }),
  createShare: (id: string) =>
    request<{ token: string; url: string; watermark: boolean; expires_at: string | null }>(
      `/jobs/${id}/share`, { method: "POST" }),
  revokeShare: (id: string) => request<void>(`/jobs/${id}/share`, { method: "DELETE" }),
  listStems: (id: string) => request<string[]>(`/jobs/${id}/stems`),
  jobVoices: (id: string) => request<SpeakerVoice[]>(`/jobs/${id}/voices`),
  setJobVoices: (id: string, choice: Record<string, string | null>) =>
    request<Job>(`/jobs/${id}/voices`, json("PUT", choice)),

  listVoices: () => request<LibraryVoice[]>("/voices"),
  getVoice: (id: string) => request<LibraryVoice>(`/voices/${id}`),
  /** รายงานเสียงนักพากย์: stolen | inappropriate | quality | other */
  reportVoice: (id: string, reason: "stolen" | "inappropriate" | "quality" | "other", detail = "") =>
    request<{ id: string; hidden: boolean }>(`/voices/${id}/report`, json("POST", { reason, detail })),

  listProjects: () => request<Project[]>("/projects"),
  createProject: (body: ProjectInput) => request<Project>("/projects", json("POST", body)),
  getProject: (id: string) => request<Project & { jobs: Job[] }>(`/projects/${id}`),
  updateProject: (id: string, patch: Partial<ProjectInput>) => request<Project>(`/projects/${id}`, json("PATCH", patch)),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" }),
  updateCharacter: (id: string, charId: string, patch: Partial<Pick<ProjectCharacter, "name" | "gender" | "role" | "self" | "addresses" | "voice_id">>) =>
    request<Project>(`/projects/${id}/characters/${charId}`, json("PATCH", patch)),
  projectMemory: (id: string) => request<ProjectMemory>(`/projects/${id}/memory`),
  deleteMemoryLine: (id: string, memoryId: number) => request<void>(`/projects/${id}/memory/${memoryId}`, { method: "DELETE" }),
  clearMemory: (id: string) => request<void>(`/projects/${id}/memory`, { method: "DELETE" }),
  deleteCharacter: (id: string, charId: string) => request<Project>(`/projects/${id}/characters/${charId}`, { method: "DELETE" }),
  setJobProject: (jobId: string, projectId: string | null) => request<Job>(`/jobs/${jobId}/project`, json("PUT", { project_id: projectId })),
  /** mapping: ผู้พูด → id ตัวละคร / "new" / "skip" */
  syncProject: (jobId: string, mapping: Record<string, string>, settings: boolean) =>
    request<{ saved: number; project: Project; job: Job }>(`/jobs/${jobId}/project/sync`, json("POST", { mapping, settings })),

  getTimeline: (id: string) => request<TimelineState>(`/jobs/${id}/timeline`),
  setupTimeline: (id: string, tracks: TrackSetup[]) => request<TimelineState>(`/jobs/${id}/timeline`, json("PUT", { tracks })),
  startTimeline: (id: string) => request<{ id: string }>(`/jobs/${id}/timeline/start`, { method: "POST" }),
  /** เพิ่มเสียงจากลิงก์คลิป (ระบบดาวน์โหลดเองตอนเตรียมเสียง) */
  createVoiceFromUrl: (url: string, meta: VoiceMeta) => {
    const form = new FormData();
    form.append("url", url);
    form.append("name", meta.name);
    form.append("gender", meta.gender);
    form.append("tone", meta.tone);
    form.append("description", meta.description);
    meta.categories.forEach((c) => form.append("categories", c));
    if (meta.denoise) form.append("denoise", "true");
    return request<LibraryVoice>("/voices", { method: "POST", body: form });
  },
  updateVoice: (id: string, patch: Partial<Pick<LibraryVoice, "name" | "gender" | "tone" | "description" | "categories" | "text">>) =>
    request<LibraryVoice>(`/voices/${id}`, json("PATCH", patch)),
  deleteVoice: (id: string) => request<void>(`/voices/${id}`, { method: "DELETE" }),
  deleteVoiceImage: (id: string) => request<LibraryVoice>(`/voices/${id}/image`, { method: "DELETE" }),
  retryVoice: (id: string) => request<LibraryVoice>(`/voices/${id}/retry`, { method: "POST" }),
  updateVoiceMood: (id: string, mood: Mood, text: string) =>
    request<LibraryVoice>(`/voices/${id}/moods/${mood}`, json("PATCH", { text })),
  deleteVoiceMood: (id: string, mood: Mood) => request<LibraryVoice>(`/voices/${id}/moods/${mood}`, { method: "DELETE" }),
  retryVoiceMood: (id: string, mood: Mood) => request<LibraryVoice>(`/voices/${id}/moods/${mood}/retry`, { method: "POST" }),

  createFromUrl: (url: string, opts: CreateOptions) => {
    const form = buildForm(opts);
    form.append("url", url);
    return request<{ id: string }>("/jobs", { method: "POST", body: form });
  },
};

export type QualityStats = {
  jobs: number; lines: number; text_edited: number; speaker_changed: number; retimed: number;
  added: number; removed: number; edit_distance: number; synth_runs: number; translations: number;
};
export type Quality = {
  available: boolean; days: number; total: QualityStats;
  weeks: (QualityStats & { key: string })[]; langs: (QualityStats & { key: string })[];
};
export type QualityLine = {
  job_id: string; line_id: number; target_lang: string; source: string; ai_target: string; final_target: string;
  ai_speaker: string; final_speaker: string; kinds: string; updated_at: string;
};
export type QualityKind = "" | "text" | "speaker" | "time";

export type Backups = {
  dir: string; hours: number; keep: number;
  backups: { name: string; bytes: number; created_at: number }[];
};

export type ShareInfo = {
  token: string;
  filename: string;
  duration: number | null;
  target_lang: TargetLang | string;
  watermark: boolean;
  expires_at: string | null;
  video_url: string;
};

export type VoiceReport = {
  id: string;
  voice_id: string;
  reporter_id: string;
  reason: string;
  detail: string;
  status: string;
  created_at: number;
  resolved_at?: number | null;
  resolved_by?: string;
  admin_note?: string;
};

export const fileUrl = {
  myData: () => `${BASE}/auth/export`,
  slip: (id: string) => `${BASE}/billing/topups/${id}/slip`,
  timelineExport: (id: string, formats: TimelineFormat[], mediaDir = "") =>
    `${BASE}/jobs/${id}/timeline/export?formats=${formats.join(",")}${mediaDir ? `&media_dir=${encodeURIComponent(mediaDir)}` : ""}`,
  source: (id: string) => `${BASE}/jobs/${id}/source`,
  thumb: (id: string, version = "") => `${BASE}/jobs/${id}/thumb${version ? `?v=${encodeURIComponent(version)}` : ""}`,
  result: (id: string, subs = false) => `${BASE}/jobs/${id}/result${subs ? "?subs=true" : ""}`,
  export: (id: string, subs = false) => `${BASE}/jobs/${id}/export${subs ? "?subs=true" : ""}`,
  subtitles: (id: string) => `${BASE}/jobs/${id}/subtitles`,
  shareVideo: (token: string) => `${BASE}/share/${encodeURIComponent(token)}/video`,
  actorUsageCsv: (month: string) => `${BASE}/admin/actor-usage-csv?month=${month}`,
  actorWhtCsv: (month: string) => `${BASE}/admin/actor-wht-csv?month=${month}`,
  qualityCsv: (days: number, kind = "") => `${BASE}/admin/quality/lines.csv?days=${days}&kind=${kind}`,
  stem: (id: string, name: string) => `${BASE}/jobs/${id}/stems/${name}`,
  voice: (id: string, version = "") => `${BASE}/voices/${id}/audio${version ? `?v=${encodeURIComponent(version)}` : ""}`,
  voiceImage: (id: string, version = "") => `${BASE}/voices/${id}/image${version ? `?v=${encodeURIComponent(version)}` : ""}`,
  voiceMood: (id: string, mood: Mood, version = "") =>
    `${BASE}/voices/${id}/moods/${mood}/audio${version ? `?v=${encodeURIComponent(version)}` : ""}`,
};

/** เช็กว่าไฟล์พร้อมดาวน์โหลดไหม โดยอ่านแค่ header แล้วยกเลิก ไม่โหลดทั้งไฟล์ */
export async function checkFile(url: string): Promise<{ ok: boolean; status: number; message: string }> {
  const ctrl = new AbortController();
  try {
    const res = await fetch(url, { signal: ctrl.signal, cache: "no-store" });
    if (res.ok) {
      ctrl.abort();
      return { ok: true, status: res.status, message: "" };
    }
    const body = await res.json().catch(() => null);
    return { ok: false, status: res.status, message: errorMessage(res.status, body) };
  } catch {
    return { ok: false, status: 0, message: tx("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้") };
  }
}

function buildForm(opts: CreateOptions): FormData {
  const form = new FormData();
  if (opts.sourceLang) form.append("source_lang", opts.sourceLang);
  form.append("target_lang", opts.targetLang);
  if (opts.numSpeakers) form.append("num_speakers", String(opts.numSpeakers));
  form.append("review", String(opts.review));
  form.append("burn_subs", String(opts.burnSubs));
  if (opts.genre) form.append("genre", opts.genre);
  if (opts.glossary) form.append("glossary", opts.glossary);
  if (opts.library) form.append("library", "true");
  if (opts.projectId) form.append("project_id", opts.projectId);
  if (opts.clipStart != null && Number.isFinite(opts.clipStart)) form.append("clip_start", String(opts.clipStart));
  if (opts.clipEnd != null && Number.isFinite(opts.clipEnd)) form.append("clip_end", String(opts.clipEnd));
  return form;
}

type UploadPath = "jobs" | "timeline" | `jobs/${string}/timeline/media` | "voices" | `voices/${string}/moods`
  | `voices/${string}/image`;

/** ที่อัปโหลด: ตรงไปที่ API พร้อมตั๋ว (บน Vercel) หรือผ่าน proxy /api */
async function uploadTarget(path: UploadPath): Promise<{ url: string; token: string | null }> {
  try {
    const res = await fetch(`${BASE}/upload-ticket?path=${path}`, { cache: "no-store" });
    const ticket = (await res.json()) as { url: string | null; token: string | null };
    if (res.ok && ticket.url) return { url: ticket.url, token: ticket.token };
  } catch { /* ใช้ proxy แทน */ }
  return { url: `${BASE}/${path}`, token: null };
}

export function uploadJob(
  file: File,
  opts: CreateOptions,
  onProgress: (fraction: number) => void,
): { promise: Promise<{ id: string }>; abort: () => void } {
  const form = buildForm(opts);
  form.append("file", file);
  return upload<{ id: string }>("jobs", form, onProgress);
}

/** นำเข้าไทม์ไลน์ (.xml .fcpxml .edl .otio หรือ zip) พร้อมไฟล์สื่อที่อ้างถึง (ส่งทีหลังได้) */
export function uploadTimeline(
  file: File,
  media: File[],
  opts: TimelineImport,
  onProgress: (fraction: number) => void,
): { promise: Promise<TimelineState>; abort: () => void } {
  const form = new FormData();
  form.append("file", file);
  media.forEach((m) => form.append("media", m));
  if (opts.fps) form.append("fps", String(opts.fps));
  if (opts.dropFrame != null) form.append("drop_frame", String(opts.dropFrame));
  if (opts.sourceLang) form.append("source_lang", opts.sourceLang);
  form.append("target_lang", opts.targetLang);
  if (opts.genre) form.append("genre", opts.genre);
  if (opts.glossary) form.append("glossary", opts.glossary);
  // ไทม์ไลน์: หยุดที่หน้าตรวจบทเสมอ และเริ่มถอดเสียงเลยถ้าไฟล์สื่อครบ
  form.append("review", "true");
  form.append("start", "true");
  return upload<TimelineState>("timeline", form, onProgress);
}

/** อัปโหลดไฟล์สื่อที่ไทม์ไลน์ยังขาด (หรือ zip) คืนสถานะใหม่ที่จับคู่ไฟล์แล้ว */
export function uploadTimelineMedia(
  jobId: string,
  files: File[],
  onProgress: (fraction: number) => void,
): { promise: Promise<TimelineState>; abort: () => void } {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  return upload<TimelineState>(`jobs/${jobId}/timeline/media`, form, onProgress);
}

export function uploadVoice(
  file: File,
  meta: VoiceMeta,
  onProgress: (fraction: number) => void,
): { promise: Promise<LibraryVoice>; abort: () => void } {
  const form = new FormData();
  form.append("name", meta.name);
  form.append("gender", meta.gender);
  form.append("tone", meta.tone);
  form.append("description", meta.description);
  meta.categories.forEach((c) => form.append("categories", c));
  if (meta.denoise) form.append("denoise", "true");
  form.append("file", file);
  return upload<LibraryVoice>("voices", form, onProgress);
}

export function uploadVoiceMood(
  voiceId: string,
  file: File,
  mood: Mood,
  onProgress: (fraction: number) => void,
): { promise: Promise<LibraryVoice>; abort: () => void } {
  const form = new FormData();
  form.append("mood", mood);
  form.append("file", file);
  return upload<LibraryVoice>(`voices/${voiceId}/moods`, form, onProgress);
}

/** ตั้งรูปของเสียงในคลัง ย่อในเบราว์เซอร์ให้ด้านยาวไม่เกิน 512 px ก่อนส่ง ไฟล์จึงเล็กพอผ่าน proxy ได้ */
export async function uploadVoiceImage(voiceId: string, file: File): Promise<LibraryVoice> {
  const form = new FormData();
  form.append("file", await shrinkImage(file, 512), "image.jpg");
  return upload<LibraryVoice>(`voices/${voiceId}/image`, form, () => undefined).promise;
}

async function shrinkImage(file: File, max: number): Promise<Blob> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new ApiError(tx("เปิดรูปนี้ไม่ได้ ใช้ไฟล์ JPG, PNG หรือ WEBP"), 400);
  }
  const scale = Math.min(1, max / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return new Promise((resolve, reject) => canvas.toBlob(
    (b) => (b ? resolve(b) : reject(new ApiError(tx("ย่อรูปไม่สำเร็จ"), 400))), "image/jpeg", 0.86));
}

/** อัปโหลดด้วย XHR เพราะ fetch ยังรายงานความคืบหน้าการอัปโหลดไม่ได้ */
function upload<T>(
  path: UploadPath,
  form: FormData,
  onProgress: (fraction: number) => void,
): { promise: Promise<T>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  let aborted = false;

  const promise = new Promise<T>((resolve, reject) => {
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let body: unknown = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* ไม่ใช่ JSON */ }
      if (xhr.status === 401 && (body as { detail?: string } | null)?.detail === "กรุณาเข้าสู่ระบบ") {
        redirectToSignIn();
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else reject(new ApiError(errorMessage(xhr.status, body), xhr.status));
    };
    xhr.onerror = () => reject(new ApiError(tx("อัปโหลดไม่สำเร็จ ตรวจการเชื่อมต่ออินเทอร์เน็ต"), 0));
    xhr.onabort = () => reject(new ApiError(tx("ยกเลิกการอัปโหลดแล้ว"), 0));
    uploadTarget(path).then(({ url, token }) => {
      if (aborted) return reject(new ApiError(tx("ยกเลิกการอัปโหลดแล้ว"), 0));
      xhr.open("POST", url);
      if (token) xhr.setRequestHeader("X-Upload-Token", token);
      if (url !== `${BASE}/${path}`) xhr.setRequestHeader("ngrok-skip-browser-warning", "1");
      xhr.send(form);
    });
  });

  return { promise, abort: () => { aborted = true; xhr.abort(); } };
}
