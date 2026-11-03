"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type LegalDoc } from "@/lib/api";

import Prefs from "@/components/Prefs";
import { tx } from "@/lib/i18n";
type Kind = "terms" | "privacy" | "actor";
const OTHER: Record<Kind, [string, string]> = {
  terms: ["/privacy", "นโยบายความเป็นส่วนตัว"], privacy: ["/terms", "ข้อกำหนดการใช้งาน"], actor: ["/actor", "สมัครเป็นนักพากย์"],
};

/** ข้อกำหนดการใช้งาน / นโยบายความเป็นส่วนตัว / หนังสือยินยอมของนักพากย์ ฉบับปัจจุบัน
 * (ข้อความมาจาก API อ่านได้โดยไม่ต้องล็อกอิน) */
export default function LegalPage({ kind }: { kind: Kind }) {
  const [doc, setDoc] = useState<LegalDoc | null>(null);
  const [items, setItems] = useState<string[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (kind === "actor") {
      api.actorConsent().then((d) => { setDoc(d); setItems(d.items.map((i) => i.text)); }).catch((e) => setError(e.message));
    } else {
      api.legal().then((d) => setDoc(d[kind])).catch((e) => setError(e.message));
    }
  }, [kind]);
  const [title, ...body] = (doc?.text ?? "").split("\n");
  return (
    <main className="page" style={{ maxWidth: 760 }}>
      <div className="row" style={{ gap: 10 }}>
        <span style={{ marginLeft: "auto", order: 2 }}><Prefs compact /></span>
        <Link href={OTHER[kind][0]} className="btn small">{tx(OTHER[kind][1])}</Link>
        <Link href="/" className="btn small">{tx("กลับหน้าหลัก")}</Link>
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {!doc ? <div className="empty">{tx("กำลังโหลด...")}</div> : (
        <article className="card legal">
          <h1>{title}</h1>
          {body.join("\n").trim().split(/\n(?=\d+\. )/).map((sec) => {
            const [head, ...rest] = sec.split("\n");
            return /^\d+\. /.test(head)
              ? <section key={head}><h2>{head}</h2><p>{rest.join("\n")}</p></section>
              : <p key={head}>{sec}</p>;
          })}
          {items.length > 0 && (
            <section>
              <h2>{tx("ข้อที่ต้องยืนยันตอนสมัคร")}</h2>
              <ul style={{ margin: 0, paddingLeft: 20, color: "var(--text-2)" }}>{items.map((t) => <li key={t}>{t}</li>)}</ul>
            </section>
          )}
        </article>
      )}
    </main>
  );
}
