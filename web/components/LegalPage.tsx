"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type LegalDoc } from "@/lib/api";

/** ข้อกำหนดการใช้งาน / นโยบายความเป็นส่วนตัวฉบับปัจจุบัน (ข้อความมาจาก API อ่านได้โดยไม่ต้องล็อกอิน) */
export default function LegalPage({ kind }: { kind: "terms" | "privacy" }) {
  const [doc, setDoc] = useState<LegalDoc | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.legal().then((d) => setDoc(d[kind])).catch((e) => setError(e.message)); }, [kind]);
  const [title, ...body] = (doc?.text ?? "").split("\n");
  return (
    <main className="page" style={{ maxWidth: 760 }}>
      <div className="row" style={{ gap: 10 }}>
        <Link href={kind === "terms" ? "/privacy" : "/terms"} className="btn small">
          {kind === "terms" ? "นโยบายความเป็นส่วนตัว" : "ข้อกำหนดการใช้งาน"}
        </Link>
        <Link href="/" className="btn small">กลับหน้าหลัก</Link>
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {!doc ? <div className="empty">กำลังโหลด...</div> : (
        <article className="card legal">
          <h1>{title}</h1>
          {body.join("\n").trim().split(/\n(?=\d+\. )/).map((sec) => {
            const [head, ...rest] = sec.split("\n");
            return /^\d+\. /.test(head)
              ? <section key={head}><h2>{head}</h2><p>{rest.join("\n")}</p></section>
              : <p key={head}>{sec}</p>;
          })}
        </article>
      )}
    </main>
  );
}
