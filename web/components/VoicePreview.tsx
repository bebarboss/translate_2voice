"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { PauseIcon, PlayIcon } from "./Icons";

/** เล่นเสียงตัวอย่างได้ทีละเสียง กดอีกเสียงจะหยุดเสียงเดิม */
export function usePreview() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);

  useEffect(() => () => { audioRef.current?.pause(); }, []);

  const toggle = useCallback((url: string) => {
    let a = audioRef.current;
    if (!a) {
      a = new Audio();
      a.onended = () => setPlaying(null);
      a.onerror = () => setPlaying(null);
      audioRef.current = a;
    }
    if (playing === url) {
      a.pause();
      setPlaying(null);
      return;
    }
    a.pause();
    a.src = url;
    a.currentTime = 0;
    a.play().then(() => setPlaying(url)).catch(() => setPlaying(null));
  }, [playing]);

  return { playing, toggle };
}

export function PreviewButton({ url, playing, onToggle, label = "ฟังตัวอย่าง", disabled }: {
  url: string;
  playing: string | null;
  onToggle: (url: string) => void;
  label?: string;
  disabled?: boolean;
}) {
  const on = playing === url;
  return (
    <button type="button" className="btn small" onClick={() => onToggle(url)} disabled={disabled}
      aria-pressed={on} aria-label={on ? "หยุดเล่น" : label}>
      {on ? <PauseIcon /> : <PlayIcon />}{on ? "หยุด" : label}
    </button>
  );
}
