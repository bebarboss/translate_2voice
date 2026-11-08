"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { PauseIcon, PlayIcon } from "./Icons";
import { tx } from "@/lib/i18n";

/** เล่นเสียงตัวอย่างได้ทีละเสียง กดอีกเสียงจะหยุดเสียงเดิม พร้อม progress สำหรับ waveform */
export function usePreview() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    const a = audioRef.current;
    return () => { a?.pause(); };
  }, []);

  const bind = useCallback((a: HTMLAudioElement) => {
    a.ontimeupdate = () => {
      const d = a.duration;
      setCurrentTime(a.currentTime || 0);
      setDuration(Number.isFinite(d) ? d : 0);
      setProgress(Number.isFinite(d) && d > 0 ? a.currentTime / d : 0);
    };
    a.onended = () => {
      setPlaying(null);
      setProgress(0);
      setCurrentTime(0);
    };
    a.onerror = () => {
      setPlaying(null);
      setProgress(0);
    };
  }, []);

  const toggle = useCallback((url: string) => {
    let a = audioRef.current;
    if (!a) {
      a = new Audio();
      audioRef.current = a;
      bind(a);
    }
    if (playing === url) {
      a.pause();
      setPlaying(null);
      return;
    }
    a.pause();
    a.src = url;
    a.currentTime = 0;
    setProgress(0);
    setCurrentTime(0);
    setDuration(0);
    a.play().then(() => setPlaying(url)).catch(() => setPlaying(null));
  }, [bind, playing]);

  const seek = useCallback((url: string, ratio: number) => {
    const a = audioRef.current;
    if (!a || playing !== url || !Number.isFinite(a.duration) || a.duration <= 0) return;
    a.currentTime = Math.min(1, Math.max(0, ratio)) * a.duration;
  }, [playing]);

  return { playing, toggle, seek, progress, currentTime, duration };
}

export function PreviewButton({ url, playing, onToggle, label = tx("ฟังตัวอย่าง"), disabled, className = "btn small" }: {
  url: string;
  playing: string | null;
  onToggle: (url: string) => void;
  label?: string;
  disabled?: boolean;
  className?: string;
}) {
  const on = playing === url;
  const showLabel = Boolean(label);
  return (
    <button type="button" className={className} onClick={() => onToggle(url)} disabled={disabled}
      aria-pressed={on} aria-label={on ? tx("หยุดเล่น") : (label || tx("ฟังตัวอย่าง"))}>
      {on ? <PauseIcon /> : <PlayIcon />}
      {showLabel ? (on ? tx("หยุด") : label) : null}
    </button>
  );
}

/** ปุ่มเล่นกลมแบบหน้ารายละเอียด Pixabay */
export function PlayRoundButton({ url, playing, onToggle, disabled }: {
  url: string;
  playing: string | null;
  onToggle: (url: string) => void;
  disabled?: boolean;
}) {
  const on = playing === url;
  return (
    <button type="button" className="play-round" onClick={() => onToggle(url)} disabled={disabled}
      aria-pressed={on} aria-label={on ? tx("หยุดเล่น") : tx("ฟังตัวอย่าง")}>
      {on ? <PauseIcon size={22} /> : <PlayIcon size={22} />}
    </button>
  );
}
