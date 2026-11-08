"use client";

/** สร้างแถบ waveform คงที่จาก id (ไม่ต้องถอดไฟล์เสียง — เบาและเหมือนแนว Pixabay) */
export function barsFromSeed(seed: string, count = 72): number[] {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
  const out: number[] = [];
  for (let i = 0; i < count; i++) {
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    const a = ((h >>> 0) % 1000) / 1000;
    h = Math.imul(h ^ (h >>> 11), 2246822519);
    const b = ((h >>> 0) % 1000) / 1000;
    // โค้งนุ่มกลางคลื่นสูงกว่าขอบ เหมือนคลิปพูดสั้น
    const envelope = 0.35 + 0.65 * Math.sin((i / (count - 1)) * Math.PI);
    out.push(Math.min(1, (0.2 + a * 0.55 + b * 0.25) * envelope));
  }
  return out;
}

export function fmtClock(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return "0:00";
  const s = Math.round(sec);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** แถบ waveform กดเล่นได้ — progress = สัดส่วนที่เล่นแล้ว 0–1 */
export default function WaveBars({
  seed,
  progress = 0,
  active = false,
  bars = 64,
  className = "",
  onClick,
}: {
  seed: string;
  progress?: number;
  active?: boolean;
  bars?: number;
  className?: string;
  onClick?: () => void;
}) {
  const heights = barsFromSeed(seed, bars);
  const p = Math.min(1, Math.max(0, progress));
  return (
    <div
      className={`wave-bars${active ? " is-active" : ""}${onClick ? " is-clickable" : ""}${className ? ` ${className}` : ""}`}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } } : undefined}
      aria-hidden={!onClick}
    >
      {heights.map((h, i) => {
        const filled = i / heights.length < p;
        return (
          <span
            key={i}
            className={`wave-bar${filled ? " is-filled" : ""}`}
            style={{ height: `${Math.round(h * 100)}%` }}
          />
        );
      })}
    </div>
  );
}
