"use client";

// สถานะโหลดที่ใช้ร่วมกัน: โครงระหว่างโหลด, ข้อความเมื่อเซิร์ฟเวอร์ล่ม, และตัวเลขที่ยังไม่มีข้อมูล
// ว่าง (empty) ใช้ได้เฉพาะหลังคำขอสำเร็จแล้วรายการว่างจริง ไม่ใช้สถานะเริ่มต้นหรือ 5xx แทน
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { tx } from "@/lib/i18n";

export type LoadPhase = "loading" | "ready" | "error";

/** ขีด en dash เมื่อโหลดไม่สำเร็จ — ไม่ใช่เลข 0 */
export const COUNT_MISSING = "–";

export const JOBS_LOAD_ERROR = {
  title: "โหลดรายการงานไม่สำเร็จ",
  description: "เซิร์ฟเวอร์ขัดข้องชั่วคราว งานของคุณยังอยู่ครบ ลองใหม่อีกครั้งในอีกสักครู่",
} as const;

export const DASH_LOAD_ERROR = {
  title: "โหลดภาพรวมไม่สำเร็จ",
  description: "เซิร์ฟเวอร์ขัดข้องชั่วคราว ข้อมูลของคุณยังอยู่ครบ ลองใหม่อีกครั้งในอีกสักครู่",
} as const;

export const CREDITS_LOAD_ERROR = {
  title: "โหลดเครดิตไม่สำเร็จ",
  description: "เซิร์ฟเวอร์ขัดข้องชั่วคราว เครดิตของคุณยังอยู่ครบ ลองใหม่อีกครั้งในอีกสักครู่",
} as const;

export const PROJECTS_LOAD_ERROR = {
  title: "โหลดโปรเจกต์ไม่สำเร็จ",
  description: "เซิร์ฟเวอร์ขัดข้องชั่วคราว ข้อมูลของคุณยังอยู่ครบ ลองใหม่อีกครั้งในอีกสักครู่",
} as const;

export const ACCOUNT_LOAD_ERROR = {
  title: "โหลดบัญชีไม่สำเร็จ",
  description: "เซิร์ฟเวอร์ขัดข้องชั่วคราว ข้อมูลของคุณยังอยู่ครบ ลองใหม่อีกครั้งในอีกสักครู่",
} as const;

export function Skel({ width, className }: { width?: string; className?: string }) {
  return <span className={`skel${className ? ` ${className}` : ""}`} style={width ? { width } : undefined} aria-hidden="true" />;
}

/** แถบแทนรายการระหว่างโหลด */
export function SkelLines({ rows = 3 }: { rows?: number }) {
  return (
    <div className="skel-stack" role="status" aria-busy="true">
      <span className="sr-only">{tx("กำลังโหลด...")}</span>
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} className={`skel skel-line${i === rows - 1 ? " short" : ""}`} />
      ))}
    </div>
  );
}

/** ตัวนับในแท็บกรองหรือการ์ดสรุป: โครงตอนโหลด, en dash เมื่อล้มเหลว, เลขจริงเมื่อสำเร็จ (รวม 0) */
export function LoadCount({ phase, value }: { phase: LoadPhase; value?: number }) {
  if (phase === "error") return <span aria-label={tx("โหลดไม่สำเร็จ")}>{COUNT_MISSING}</span>;
  if (phase !== "ready" || value == null) {
    return (
      <span className="skel skel-count" role="status">
        <span className="sr-only">{tx("กำลังโหลด...")}</span>
      </span>
    );
  }
  return <>{value}</>;
}

/** ค่าในการ์ดสรุปที่อาจไม่ใช่ตัวเลขล้วน เช่น เครดิตที่จัดรูปแบบแล้ว */
export function LoadValue({ phase, children, width }: { phase: LoadPhase; children: ReactNode; width?: string }) {
  if (phase === "error") return <span aria-label={tx("โหลดไม่สำเร็จ")}>{COUNT_MISSING}</span>;
  if (phase !== "ready") {
    return (
      <span className="skel" style={width ? { width } : undefined} role="status">
        <span className="sr-only">{tx("กำลังโหลด...")}</span>
      </span>
    );
  }
  return <>{children}</>;
}

export function LoadError({ title, description, onRetry }: { title: string; description: string; onRetry: () => void }) {
  return (
    <div className="load-error" role="alert">
      <h2>{tx(title)}</h2>
      <p>{tx(description)}</p>
      <button type="button" className="btn primary" onClick={onRetry}>{tx("ลองอีกครั้ง")}</button>
    </div>
  );
}

/**
 * โหลดข้อมูลหนึ่งชุด.
 * phase เป็น error เฉพาะเมื่อยังไม่เคยได้ข้อมูล — คำขอถัดไปที่ล้มเหลวจะคงข้อมูลเดิมไว้
 * ไม่ให้ตัวนับตกเป็น 0. reload() ใช้กับปุ่มลองอีกครั้ง, refresh() ใช้กับโพลล์พื้นหลัง
 */
export function useLoad<T>(load: () => Promise<T>, enabled = true) {
  const loadRef = useRef(load);
  loadRef.current = load;
  const dataRef = useRef<T | null>(null);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const seq = useRef(0);
  const [data, setData] = useState<T | null>(null);
  const [phase, setPhase] = useState<LoadPhase>("loading");

  const run = useCallback((mode: "reset" | "soft") => {
    if (!enabledRef.current) return;
    const id = ++seq.current;
    if (mode === "reset" && dataRef.current == null) setPhase("loading");
    loadRef.current().then(
      (value) => {
        if (seq.current !== id) return;
        dataRef.current = value;
        setData(value);
        setPhase("ready");
      },
      () => {
        if (seq.current !== id) return;
        if (dataRef.current == null) setPhase("error");
      },
    );
  }, []);

  useEffect(() => {
    if (!enabled) return;
    run("reset");
  }, [enabled, run]);

  const reload = useCallback(() => run("reset"), [run]);
  const refresh = useCallback(() => run("soft"), [run]);
  return { data, phase: enabled ? phase : "loading" as const, reload, refresh };
}
