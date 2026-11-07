"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { FlagIcon } from "@/components/Icons";
import { api, type FeedbackItem } from "@/lib/api";
import { locale, tx } from "@/lib/i18n";
import { useAuth } from "@/lib/useAuth";

const CATEGORIES: { id: FeedbackItem["category"]; label: string; hint: string }[] = [
  { id: "bug", label: "บั๊กหรือข้อผิดพลาด", hint: "หน้าเว็บพัง งานค้าง ระบบตอบผิด" },
  { id: "billing", label: "เครดิตและการชำระเงิน", hint: "เติมเครดิต แพ็กเกจ สลิป สิทธิ์" },
  { id: "quality", label: "คุณภาพพากย์", hint: "เสียง บทแปล จังหวะปาก" },
  { id: "feature", label: "ขอฟีเจอร์", hint: "อยากให้มีอะไรเพิ่ม" },
  { id: "other", label: "อื่น ๆ", hint: "คำถามหรือเรื่องอื่น" },
];

const CAT_LABEL = Object.fromEntries(CATEGORIES.map((c) => [c.id, c.label])) as Record<string, string>;

/** แจ้งปัญหาหรือข้อเสนอแนะถึงทีม Pakdee */
export default function SupportPage() {
  const { config, user, loaded } = useAuth();
  const [category, setCategory] = useState<FeedbackItem["category"]>("bug");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [jobId, setJobId] = useState("");
  const [mine, setMine] = useState<FeedbackItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (loaded && config?.auth && !user) window.location.href = "/welcome?next=/support";
  }, [loaded, config, user]);

  const reload = () => api.myFeedback().then(setMine).catch(() => setMine([]));
  useEffect(() => { if (user) reload(); }, [user]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(""); setFlash("");
    try {
      await api.submitFeedback({ category, subject, body, job_id: jobId.trim() });
      setSubject(""); setBody(""); setJobId("");
      setFlash(tx("ส่งแล้ว ทีมงานจะดูและติดต่อกลับทางอีเมลบัญชีของคุณ"));
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : tx("ส่งไม่สำเร็จ"));
    } finally {
      setBusy(false);
    }
  };

  if (!loaded || (config?.auth && !user)) {
    return <main className="page"><div className="empty">{tx("กำลังโหลด...")}</div></main>;
  }
  if (config?.auth && !user) return null;

  return (
    <main className="page narrow">
      <div className="page-head">
        <div>
          <h1>{tx("แจ้งปัญหา")}</h1>
          <span className="muted">{tx("บอกบั๊ก คุณภาพพากย์ หรือข้อเสนอแนะ — เราอ่านทุกข้อความ")}</span>
        </div>
      </div>

      <form className="card" onSubmit={send} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <label className="field">
          <span>{tx("ประเภท")}</span>
          <select className="select" value={category} onChange={(e) => setCategory(e.target.value as FeedbackItem["category"])}>
            {CATEGORIES.map((c) => (
              <option key={c.id} value={c.id}>{tx(c.label)} — {tx(c.hint)}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>{tx("หัวข้อ")}</span>
          <input className="input" value={subject} maxLength={120} required
            placeholder={tx("สรุปสั้น ๆ เช่น หน้าโปรโมชันกดแล้วขึ้น 500")}
            onChange={(e) => setSubject(e.target.value)} />
        </label>
        <label className="field">
          <span>{tx("รายละเอียด")}</span>
          <textarea className="input" rows={6} value={body} maxLength={4000} required
            placeholder={tx("เกิดอะไรขึ้น ต้องการให้อย่างไร ถ้าเป็นงานพากย์ บอกชื่อคลิปหรือรหัสงานด้วย")}
            onChange={(e) => setBody(e.target.value)} />
        </label>
        <label className="field">
          <span>{tx("รหัสงาน (ถ้ามี)")}</span>
          <input className="input" value={jobId} maxLength={80}
            placeholder={tx("คัดลอกจาก URL หน้างาน เช่น จาก /jobs/...")}
            onChange={(e) => setJobId(e.target.value)} />
        </label>
        {error && <div className="alert error" role="alert">{error}</div>}
        {flash && <div className="alert info" role="status">{flash}</div>}
        <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
          <span className="dim" style={{ fontSize: 13 }}>
            {user ? tx("จะติดต่อกลับที่ {0}", { 0: user.email }) : null}
          </span>
          <button type="submit" className="btn primary" disabled={busy}>
            <FlagIcon size={16} /> {busy ? tx("กำลังส่ง...") : tx("ส่งรายงาน")}
          </button>
        </div>
      </form>

      {mine.length > 0 && (
        <section style={{ marginTop: 28 }} aria-labelledby="mine-title">
          <h2 id="mine-title" style={{ fontSize: 18, margin: "0 0 12px" }}>{tx("ที่เคยแจ้ง")}</h2>
          <ul className="card" style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column" }}>
            {mine.map((f) => (
              <li key={f.id} style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                <div className="row" style={{ justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                  <b>{f.subject}</b>
                  <span className={`badge ${f.status === "done" ? "done" : "warn"}`}>
                    {f.status === "done" ? tx("ปิดแล้ว") : tx("รอดู")}
                  </span>
                </div>
                <div className="dim" style={{ fontSize: 13, marginTop: 4 }}>
                  {tx(CAT_LABEL[f.category] || f.category)}
                  {" · "}
                  {new Date(f.created_at * 1000).toLocaleString(locale())}
                  {f.job_id ? ` · ${f.job_id}` : ""}
                </div>
                {f.admin_note && <p style={{ margin: "8px 0 0", fontSize: 14 }}>{tx("หมายเหตุผู้ดูแล")}: {f.admin_note}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="dim" style={{ marginTop: 24, fontSize: 13 }}>
        {tx("เรื่องด่วนเรื่องบัญชีหรือการชำระเงิน ดูที่")}{" "}
        <Link href="/account">{tx("หน้าบัญชี")}</Link>
        {config?.billing ? <>{" · "}<Link href="/promotions">{tx("แพ็กเกจและโปรโมชัน")}</Link></> : null}
      </p>
    </main>
  );
}
