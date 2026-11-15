"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { FlagIcon } from "@/components/Icons";
import { ACCOUNT_LOAD_ERROR, LoadError } from "@/components/LoadState";
import { api, type FeedbackItem } from "@/lib/api";
import { locale, tx } from "@/lib/i18n";
import { redirectToSignIn } from "@/lib/auth-routes";
import { isSignedOut, useAuth } from "@/lib/useAuth";

const CATEGORIES: { id: FeedbackItem["category"]; label: string }[] = [
  { id: "bug", label: "บั๊กหรือข้อผิดพลาด" },
  { id: "billing", label: "เครดิตและการชำระเงิน" },
  { id: "quality", label: "คุณภาพพากย์" },
  { id: "feature", label: "ขอฟีเจอร์" },
  { id: "other", label: "อื่น ๆ" },
];

const CAT_LABEL = Object.fromEntries(CATEGORIES.map((c) => [c.id, c.label])) as Record<string, string>;

/** แจ้งปัญหาหรือข้อเสนอแนะถึงทีม Pakdee */
export default function SupportPage() {
  const auth = useAuth();
  const { config, user, loaded, unavailable, reload: reloadAuth } = auth;
  const signedOut = isSignedOut(auth);
  const [category, setCategory] = useState<FeedbackItem["category"]>("bug");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [jobId, setJobId] = useState("");
  const [mine, setMine] = useState<FeedbackItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (loaded && signedOut) redirectToSignIn();
  }, [loaded, signedOut]);

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

  if (!loaded || signedOut) {
    return <main className="page"><div className="empty">{tx("กำลังโหลด...")}</div></main>;
  }
  if (unavailable && !user) {
    return (
      <main className="page">
        <LoadError title={ACCOUNT_LOAD_ERROR.title} description={ACCOUNT_LOAD_ERROR.description} onRetry={() => { void reloadAuth(); }} />
      </main>
    );
  }

  return (
    <main className="page support-page">
      <div className="page-head">
        <div>
          <h1>{tx("แจ้งปัญหา")}</h1>
          <span className="muted">{tx("บอกบั๊ก คุณภาพพากย์ หรือข้อเสนอแนะ — เราอ่านทุกข้อความ")}</span>
        </div>
      </div>

      <form className="card support-form" onSubmit={send}>
        <div className="field">
          <span className="label">{tx("ประเภท")}</span>
          <div className="seg support-cats" role="group" aria-label={tx("ประเภท")}>
            {CATEGORIES.map((c) => (
              <button key={c.id} type="button" aria-pressed={category === c.id}
                onClick={() => setCategory(c.id)}>{tx(c.label)}</button>
            ))}
          </div>
        </div>
        <div className="field">
          <label className="label" htmlFor="fb-subject">{tx("หัวข้อ")}</label>
          <input id="fb-subject" className="input" value={subject} maxLength={120} required
            placeholder={tx("สรุปสั้น ๆ เช่น หน้าโปรโมชันกดแล้วขึ้น 500")}
            onChange={(e) => setSubject(e.target.value)} />
        </div>
        <div className="field">
          <label className="label" htmlFor="fb-body">{tx("รายละเอียด")}</label>
          <textarea id="fb-body" className="input" rows={4} value={body} maxLength={4000} required
            placeholder={tx("เกิดอะไรขึ้น ต้องการให้อย่างไร ถ้าเป็นงานพากย์ บอกชื่อคลิปหรือรหัสงานด้วย")}
            onChange={(e) => setBody(e.target.value)} />
        </div>
        <div className="field">
          <label className="label" htmlFor="fb-job">{tx("รหัสงาน (ถ้ามี)")}</label>
          <input id="fb-job" className="input" value={jobId} maxLength={80}
            placeholder={tx("คัดลอกจาก URL หน้างาน เช่น จาก /jobs/...")}
            onChange={(e) => setJobId(e.target.value)} />
        </div>
        {error && <div className="alert error" role="alert">{error}</div>}
        {flash && <div className="alert info" role="status">{flash}</div>}
        <div className="support-actions">
          <span className="dim">
            {user ? tx("จะติดต่อกลับที่ {0}", { 0: user.email }) : null}
          </span>
          <button type="submit" className="btn primary" disabled={busy}>
            <FlagIcon size={16} /> {busy ? tx("กำลังส่ง...") : tx("ส่งรายงาน")}
          </button>
        </div>
      </form>

      {mine.length > 0 && (
        <section className="support-history" aria-labelledby="mine-title">
          <h2 id="mine-title">{tx("ที่เคยแจ้ง")}</h2>
          <ul className="card support-history-list">
            {mine.map((f) => (
              <li key={f.id}>
                <div className="support-history-head">
                  <b>{f.subject}</b>
                  <span className={`badge ${f.status === "done" ? "done" : "warn"}`}>
                    {f.status === "done" ? tx("ปิดแล้ว") : tx("รอดู")}
                  </span>
                </div>
                <div className="dim">
                  {tx(CAT_LABEL[f.category] || f.category)}
                  {" · "}
                  {new Date(f.created_at * 1000).toLocaleString(locale())}
                  {f.job_id ? ` · ${f.job_id}` : ""}
                </div>
                {f.admin_note && <p>{tx("หมายเหตุผู้ดูแล")}: {f.admin_note}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="support-foot dim">
        {tx("เรื่องด่วนเรื่องบัญชีหรือการชำระเงิน ดูที่")}{" "}
        <Link href="/account">{tx("หน้าบัญชี")}</Link>
        {config?.billing ? <>{" · "}<Link href="/promotions">{tx("แพ็กเกจและโปรโมชัน")}</Link></> : null}
      </p>
    </main>
  );
}
