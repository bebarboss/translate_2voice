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
  synth_stats: { redubbed: number; reused: number } | null;
  voice_map: Record<string, string>;
  queue_position?: number | null; // ลำดับคิว (เฉพาะตอนรอคิว)
  speaker_names?: Record<string, string>; // ชื่อที่ผู้ใช้ตั้งให้ตัวละคร
  library?: boolean; // งานเก็บเสียงเข้าคลัง: แยกผู้พูดและถอดเสียงอย่างเดียว
  saved_voices?: Record<string, string>; // ตัวละคร → id เสียงในคลังที่บันทึกจากงานนี้
  error: string | null;
  created_at: string;
  updated_at: string;
}

export type Gender = "male" | "female" | "";

// ---- บัญชีผู้ใช้ เครดิต แพ็กเกจ (เปิดหรือไม่ ดู AuthConfig) 1 เครดิต = คลิป 1 นาที (ทศนิยมได้ 2 ตำแหน่ง) เงินเป็นสตางค์
/** google_client_id ว่าง = ยังไม่ได้ตั้งปุ่มเข้าสู่ระบบด้วย Google ที่ API */
export interface AuthConfig { auth: boolean; billing: boolean; payments: boolean; google_client_id: string }
/** owner = ผู้ดูแลหลักจาก ADMIN_EMAILS (ถอดสิทธิ์ไม่ได้) */
export type AccountType = "personal" | "creator" | "business";
/** ข้อมูลเบื้องต้นที่ผู้ใช้กรอกหลังล็อกอินครั้งแรก (account_type ว่าง = ยังไม่กรอก) */
export interface Profile { full_name: string; phone: string; account_type: AccountType | ""; company: string; use_case: string }
export interface User {
  id: string; email: string; name: string; admin: boolean; owner: boolean; credits: number;
  profile_complete: boolean; profile: Profile;
}
/** minutes = เครดิตแพ็กเกจต่อรอบ */
export interface Plan { id: string; name: string; price: number; minutes: number; days: number }
/** minutes_left = เครดิตแพ็กเกจที่เหลือ หมดอายุพร้อมแพ็กเกจ */
export interface Subscription { plan_id: string; minutes_left: number; started_at: number; expires_at: number }
/** credits = เครดิตเติมที่เปลี่ยน, minutes = เครดิตแพ็กเกจที่เปลี่ยน, amount = เงินที่จ่าย */
export interface LedgerEntry { kind: string; credits: number; minutes: number; amount: number; ref: string | null; note: string; created_at: number }
export interface Wallet { credits: number; subscription: Subscription | null; credit_price: number; ledger: LedgerEntry[] }
export interface Card { id: string; brand: string; last4: string; exp_month: number; exp_year: number; created_at: number }
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
  review?: "pending" | "approved" | "rejected" | null; // ผู้ดูแลตรวจฟังแล้วหรือยัง ผู้ใช้ทั่วไปเห็นเฉพาะ approved
  review_note?: string;
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
}
export interface UsageRow {
  job_id: string; voice_id: string; user_id: string; job_name: string; seconds: number; lines: number;
  month: string; created_at: number; updated_at: number; payable: boolean; amount: number;
}
export interface ActorPayout { id: number; actor_id: string; month: string; amount: number; note: string; paid_by: string; paid_at: number }
export interface ActorMe {
  actor: Actor | null;
  consent: { version: string; accepted_at: number } | null;
  consent_current: boolean;
  consent_version: string;
  rate: number; // สตางค์ต่อนาที
  voices: LibraryVoice[];
  usage: UsageSummary[];
  payouts: ActorPayout[];
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
  numSpeakers: number | null;
  review: boolean;
  burnSubs: boolean;
  genre: string;
  glossary: string;
  library?: boolean;
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
  if (Array.isArray(detail) && detail[0]?.msg) return `ข้อมูลไม่ถูกต้อง: ${detail[0].msg}`;
  return `คำขอล้มเหลว (รหัส ${status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, { cache: "no-store", ...init });
  } catch {
    throw new ApiError("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้", 0);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    // ระบบบัญชีเปิดอยู่แต่ยังไม่ล็อกอิน (หรือหมดอายุ) → ไปหน้าเข้าสู่ระบบ แล้วกลับมาหน้าเดิม
    if (res.status === 401 && (body as { detail?: string } | null)?.detail === "กรุณาเข้าสู่ระบบ"
      && typeof window !== "undefined" && !/^\/(login|welcome)/.test(window.location.pathname)) {
      // ยังไม่ได้เข้าสู่ระบบ → หน้าแรก (มีปุ่มสมัครและเข้าสู่ระบบ) แล้วกลับมาหน้านี้หลังเข้าสู่ระบบ
      window.location.href = `/welcome?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
    }
    // ล็อกอินแล้วแต่ยังไม่ได้กรอกข้อมูลเบื้องต้น → หน้ากรอกข้อมูล แล้วกลับมาหน้านี้
    if (res.status === 428 && typeof window !== "undefined" && !/^\/(onboarding|login|welcome)/.test(window.location.pathname)) {
      window.location.href = `/onboarding?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
    }
    throw new ApiError(errorMessage(res.status, body), res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
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
  saveProfile: (body: Profile & { name?: string }) => request<User>("/auth/profile", json("PUT", body)),
  plans: () => request<{ plans: Plan[]; credit_price: number; credit_packs: number[]; card_bonus: number }>("/billing/plans"),
  wallet: () => request<Wallet>("/billing/wallet"),
  subscribe: (planId: string) => request<{ id: string; status: string }>("/billing/subscribe", json("POST", { plan_id: planId })),
  cards: () => request<Cards>("/billing/cards"),
  /** token จากสคริปต์ของผู้ให้บริการชำระเงิน (เลขบัตรไม่ผ่านเซิร์ฟเวอร์เรา) */
  addCard: (token: string) => request<{ card: Card; bonus: number }>("/billing/cards", json("POST", { token })),
  removeCard: (id: string) => request<void>(`/billing/cards/${id}`, { method: "DELETE" }),
  buyCredits: (credits: number) => request<{ id: string; status: string }>("/billing/topups", json("POST", { credits })),
  adminUsers: () => request<AdminUser[]>("/admin/users"),
  adminCredit: (userId: string, credits: number, note = "") =>
    request<void>(`/admin/users/${userId}/credit`, json("POST", { credits, note })),
  adminSetAdmin: (userId: string, admin: boolean) => request<void>(`/admin/users/${userId}/admin`, json("POST", { admin })),
  adminPlan: (userId: string, planId: string) => request<void>(`/admin/users/${userId}/plan`, json("POST", { plan_id: planId })),
  actorConsent: () => request<{ version: string; text: string; rate: number }>("/actor/consent"),
  actorMe: () => request<ActorMe>("/actor/me"),
  actorApply: (body: { stage_name: string; gender: Gender; bio: string; contact: string; consent_version: string }) =>
    request<Actor>("/actor/apply", json("POST", body)),
  actorAccept: (version: string) => request<void>("/actor/consent", json("POST", { version })),
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
  actorDeleteVoice: (id: string) => request<void>(`/actor/voices/${id}`, { method: "DELETE" }),
  actorWithdraw: () => request<void>("/actor/withdraw", { method: "POST" }),
  adminActors: () => request<AdminActor[]>("/admin/actors"),
  adminReviewActor: (userId: string, approve: boolean, note = "") =>
    request<void>(`/admin/actors/${userId}/review`, json("POST", { approve, note })),
  adminActorVoices: () => request<LibraryVoice[]>("/admin/actor-voices"),
  adminReviewVoice: (voiceId: string, approve: boolean, note = "") =>
    request<void>(`/admin/actor-voices/${voiceId}/review`, json("POST", { approve, note })),
  adminActorUsage: (month = "") =>
    request<{ rate: number; rows: UsageSummary[]; payouts: ActorPayout[] }>(`/admin/actor-usage${month ? `?month=${month}` : ""}`),
  adminActorUsageRows: (userId: string, month: string) => request<UsageRow[]>(`/admin/actor-usage/${userId}?month=${month}`),
  adminPayout: (userId: string, month: string, note = "") =>
    request<{ amount: number }>(`/admin/actor-payouts/${userId}`, json("POST", { month, note })),
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
  synthesize: (id: string) => request<{ id: string }>(`/jobs/${id}/synthesize`, { method: "POST" }),
  listStems: (id: string) => request<string[]>(`/jobs/${id}/stems`),
  jobVoices: (id: string) => request<SpeakerVoice[]>(`/jobs/${id}/voices`),
  setJobVoices: (id: string, choice: Record<string, string | null>) =>
    request<Job>(`/jobs/${id}/voices`, json("PUT", choice)),

  listVoices: () => request<LibraryVoice[]>("/voices"),
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

export const fileUrl = {
  source: (id: string) => `${BASE}/jobs/${id}/source`,
  result: (id: string, subs = false) => `${BASE}/jobs/${id}/result${subs ? "?subs=true" : ""}`,
  export: (id: string, subs = false) => `${BASE}/jobs/${id}/export${subs ? "?subs=true" : ""}`,
  subtitles: (id: string) => `${BASE}/jobs/${id}/subtitles`,
  actorUsageCsv: (month: string) => `${BASE}/admin/actor-usage-csv?month=${month}`,
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
    return { ok: false, status: 0, message: "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้" };
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
  return form;
}

type UploadPath = "jobs" | "voices" | `voices/${string}/moods` | `voices/${string}/image`;

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
    throw new ApiError("เปิดรูปนี้ไม่ได้ ใช้ไฟล์ JPG, PNG หรือ WEBP", 400);
  }
  const scale = Math.min(1, max / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return new Promise((resolve, reject) => canvas.toBlob(
    (b) => (b ? resolve(b) : reject(new ApiError("ย่อรูปไม่สำเร็จ", 400))), "image/jpeg", 0.86));
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
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else reject(new ApiError(errorMessage(xhr.status, body), xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("อัปโหลดไม่สำเร็จ ตรวจการเชื่อมต่ออินเทอร์เน็ต", 0));
    xhr.onabort = () => reject(new ApiError("ยกเลิกการอัปโหลดแล้ว", 0));
    uploadTarget(path).then(({ url, token }) => {
      if (aborted) return reject(new ApiError("ยกเลิกการอัปโหลดแล้ว", 0));
      xhr.open("POST", url);
      if (token) xhr.setRequestHeader("X-Upload-Token", token);
      if (url !== `${BASE}/${path}`) xhr.setRequestHeader("ngrok-skip-browser-warning", "1");
      xhr.send(form);
    });
  });

  return { promise, abort: () => { aborted = true; xhr.abort(); } };
}
