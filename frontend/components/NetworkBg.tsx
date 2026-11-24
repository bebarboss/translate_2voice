"use client";

import { useEffect, useRef } from "react";

/** พื้นหลังขยับของ /welcome และ /login: จุดลอยช้า ๆ โยงเส้นหากันเมื่ออยู่ใกล้ ขนาดและการจางขอบกำหนดด้วย CSS ของ className
 *  หยุดวาดเมื่อเลื่อนพ้นจอหรือสลับแท็บ ผู้ใช้ที่ตั้งลดการเคลื่อนไหวได้ภาพนิ่งเฟรมเดียว */
const LINK = 150; // ระยะ (px) ที่จุดสองจุดจะโยงเส้นหากัน
const SPEED = 0.18; // px ต่อเฟรมที่ 60fps (คิดตามเวลาจริง จอ 120Hz จึงไม่เร็วขึ้น)
const RGB = "61, 214, 140"; // เขียวแบรนด์ธีมมืด (--lp-accent)

type Dot = { x: number; y: number; vx: number; vy: number; r: number };

export default function NetworkBg({ className = "lp-net" }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0;
    let h = 0;
    let dots: Dot[] = [];
    let frame = 0;
    let visible = true;
    let last = 0;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const count = Math.min(160, Math.round((w * h) / 8000));
      dots = Array.from({ length: count }, () => {
        const a = Math.random() * Math.PI * 2;
        const s = SPEED * (0.4 + Math.random() * 0.8);
        return { x: Math.random() * w, y: Math.random() * h, vx: Math.cos(a) * s, vy: Math.sin(a) * s, r: 0.8 + Math.random() * 1.4 };
      });
    };

    const draw = () => {
      ctx.clearRect(0, 0, w, h);
      for (let i = 0; i < dots.length; i++) {
        const a = dots[i];
        for (let j = i + 1; j < dots.length; j++) {
          const b = dots[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d2 = dx * dx + dy * dy;
          if (d2 > LINK * LINK) continue;
          ctx.strokeStyle = `rgba(${RGB}, ${0.32 * (1 - Math.sqrt(d2) / LINK)})`;
          ctx.lineWidth = 0.7;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
      for (const p of dots) {
        ctx.fillStyle = `rgba(${RGB}, .75)`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const step = (now: number) => {
      frame = 0;
      const k = last ? Math.min((now - last) / (1000 / 60), 3) : 1; // ข้ามช่วงที่หยุดไว้ ไม่ให้จุดกระโดด
      last = now;
      for (const p of dots) {
        p.x += p.vx * k;
        p.y += p.vy * k;
        if (p.x < -20) p.x = w + 20; else if (p.x > w + 20) p.x = -20;
        if (p.y < -20) p.y = h + 20; else if (p.y > h + 20) p.y = -20;
      }
      draw();
      loop();
    };
    const loop = () => {
      if (!visible || document.hidden) last = 0;
      if (!still && visible && !document.hidden && !frame) frame = requestAnimationFrame(step);
    };

    resize();
    draw();
    loop();
    const ro = new ResizeObserver(() => { resize(); draw(); });
    ro.observe(canvas);
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; loop(); });
    io.observe(canvas);
    document.addEventListener("visibilitychange", loop);
    return () => {
      ro.disconnect();
      io.disconnect();
      document.removeEventListener("visibilitychange", loop);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);
  return <canvas ref={ref} className={className} aria-hidden="true" />;
}
