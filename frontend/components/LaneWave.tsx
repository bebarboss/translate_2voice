"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

const BUCKETS = 3000;
const cache = new Map<string, Promise<number[] | null>>();

/** รูปคลื่นเสียงต้นฉบับของตัวละครหนึ่งตัว วาดเป็นพื้นหลังของเลเยอร์ (เซิร์ฟเวอร์ส่งเฉพาะยอดคลื่น ไม่ต้องโหลดไฟล์ wav)
 *  โหลดไม่ได้ (ไม่มีไฟล์/อ่านไม่ได้) = ไม่แสดงอะไร เลเยอร์ใช้งานได้ตามปกติ */
export default function LaneWave({ jobId, name, color, view, span, total }: {
  jobId: string; name: string; color: string; view: number; span: number; total: number;
}) {
  const [peaks, setPeaks] = useState<{ peaks: number[]; duration: number } | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let live = true;
    const key = `${jobId}/${name}`;
    let p = cache.get(key);
    if (!p) {
      p = api.stemPeaks(jobId, name, BUCKETS).then((r) => r.peaks).catch(() => null);
      cache.set(key, p);
    }
    p.then((x) => { if (live && x) setPeaks({ peaks: x, duration: x.length ? Math.max(total, 1e-3) : 0 }); });
    return () => { live = false; };
    // total ไม่ทำให้ดึงใหม่ แค่ใช้ตอนวาด
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, name]);

  useEffect(() => {
    const c = canvas.current;
    if (!c || !peaks) return;
    const w = c.clientWidth, h = c.clientHeight;
    if (!w || !h) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
    const g = c.getContext("2d");
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    g.fillStyle = color;
    const n = peaks.peaks.length;
    const dur = Math.max(total, 1e-3);
    // แต่ละพิกเซลเลือกยอดสูงสุดของช่วงที่ครอบคลุม (ซูมออกแล้วไม่หลุดยอด)
    for (let x = 0; x < w; x++) {
      const a = Math.floor(((view + (x / w) * span) / dur) * n);
      const b = Math.max(a + 1, Math.ceil(((view + ((x + 1) / w) * span) / dur) * n));
      let m = 0;
      for (let i = Math.max(0, a); i < Math.min(n, b); i++) if (peaks.peaks[i] > m) m = peaks.peaks[i];
      const bar = Math.max(m > 2 ? 1 : 0, (Math.sqrt(m / 100)) * h);
      if (bar > 0) g.fillRect(x, (h - bar) / 2, 1, bar);
    }
  }, [peaks, view, span, total, color]);

  if (!peaks) return null;
  return <canvas ref={canvas} className="lane-wave" aria-hidden="true" />;
}
