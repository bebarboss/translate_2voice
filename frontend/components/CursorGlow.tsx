"use client";

import { useEffect } from "react";

/** แสงจาง ๆ บนพื้นหลังที่ขยับตามเมาส์ เปิดเฉพาะเครื่องที่มีเมาส์ และปิดเมื่อผู้ใช้ตั้งค่าลดการเคลื่อนไหว
 *  ตำแหน่งส่งผ่านตัวแปร CSS --glow-x / --glow-y บน <html> ส่วนหน้าตาอยู่ที่ .shell-main ใน globals.css */
export default function CursorGlow() {
  useEffect(() => {
    const ok = window.matchMedia("(hover: hover) and (pointer: fine)").matches
      && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!ok) return;
    const root = document.documentElement;
    let frame = 0;
    let x = 0;
    let y = 0;
    const paint = () => {
      frame = 0;
      root.style.setProperty("--glow-x", `${x}px`);
      root.style.setProperty("--glow-y", `${y}px`);
    };
    const move = (e: PointerEvent) => {
      x = e.clientX;
      y = e.clientY;
      root.dataset.glow = "on";
      if (!frame) frame = requestAnimationFrame(paint);
    };
    const leave = () => { delete root.dataset.glow; };
    window.addEventListener("pointermove", move, { passive: true });
    document.addEventListener("pointerleave", leave);
    return () => {
      window.removeEventListener("pointermove", move);
      document.removeEventListener("pointerleave", leave);
      if (frame) cancelAnimationFrame(frame);
      delete root.dataset.glow;
    };
  }, []);
  return null;
}
