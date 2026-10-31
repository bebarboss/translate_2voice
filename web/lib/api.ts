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
  burn_subs: boolean;
  sub_style: SubtitleStyle | null;
  speakers: string[];
  duration: number | null;
  synth_stats: { redubbed: number; reused: number } | null;
  voice_map: Record<string, string>;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export type Gender = "male" | "female" | "";

export interface LibraryVoice {
  id: string;
  name: string;
  gender: Gender;
  tone: string;
  status: "processing" | "ready" | "failed";
  stage: string;
  error: string | null;
  filename: string;
  text: string;
  duration: number | null;
  pitch_hz: number | null;
  quality: number | null;
  created_at: string;
  updated_at: string;
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
}

export interface Utterance {
  id: number;
  speaker: string;
  start: number;
  end: number;
  source: string;
  target: string;
  ref_reading: string;
}

export interface UtteranceEdit {
  id: number;
  target?: string;
  speaker?: string;
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
  queue: { running: string | null; queued: number };
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
  mergeLine: (id: string, lineId: number) =>
    request<Utterance[]>(`/jobs/${id}/transcript/${lineId}/merge`, { method: "POST" }),
  addSpeaker: (id: string) => request<Job>(`/jobs/${id}/speakers`, { method: "POST" }),
  removeSpeaker: (id: string, speaker: string, into?: string) =>
    request<Job>(`/jobs/${id}/speakers/${speaker}${into ? `?into=${encodeURIComponent(into)}` : ""}`,
      { method: "DELETE" }),
  synthesize: (id: string) => request<{ id: string }>(`/jobs/${id}/synthesize`, { method: "POST" }),
  listStems: (id: string) => request<string[]>(`/jobs/${id}/stems`),
  jobVoices: (id: string) => request<SpeakerVoice[]>(`/jobs/${id}/voices`),
  setJobVoices: (id: string, choice: Record<string, string | null>) =>
    request<Job>(`/jobs/${id}/voices`, json("PUT", choice)),

  listVoices: () => request<LibraryVoice[]>("/voices"),
  updateVoice: (id: string, patch: Partial<Pick<LibraryVoice, "name" | "gender" | "tone" | "text">>) =>
    request<LibraryVoice>(`/voices/${id}`, json("PATCH", patch)),
  deleteVoice: (id: string) => request<void>(`/voices/${id}`, { method: "DELETE" }),
  retryVoice: (id: string) => request<LibraryVoice>(`/voices/${id}/retry`, { method: "POST" }),

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
  stem: (id: string, name: string) => `${BASE}/jobs/${id}/stems/${name}`,
  voice: (id: string, version = "") => `${BASE}/voices/${id}/audio${version ? `?v=${encodeURIComponent(version)}` : ""}`,
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
  return form;
}

type UploadPath = "jobs" | "voices";

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
  form.append("file", file);
  return upload<LibraryVoice>("voices", form, onProgress);
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
