"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { BrandLockup } from "@/components/Brand";
import { Skel } from "@/components/LoadState";
import { ApiError, api } from "@/lib/api";
import { emailSettingsHref } from "@/lib/auth-routes";
import { tx } from "@/lib/i18n";
import { EMAIL_PREF_DESC, isEmailPrefKind } from "@/lib/notify-prefs";
import { isSignedOut, useAuth } from "@/lib/useAuth";
import {
  CONFIRM_BODY,
  CONFIRM_BUTTON,
  CONFIRM_TITLE,
  ERROR_BODY,
  ERROR_TITLE,
  EXPIRED_BODY,
  EXPIRED_BUTTON,
  EXPIRED_TITLE,
  GENERIC_HINT,
  INVALID_BODY,
  INVALID_BUTTON,
  INVALID_TITLE,
  SUBMITTING_TITLE,
  SUCCESS_TITLE,
  categoryLabel,
  confirmCategoryLine,
  mapUnsubscribePreview,
  mapUnsubscribeResponse,
  readUnsubscribeToken,
} from "@/lib/unsubscribe";

type Phase =
  | { name: "loading" }
  | { name: "confirm"; category: string | null }
  | { name: "submitting"; category: string | null }
  | { name: "success"; category: string }
  | { name: "invalid" }
  | { name: "expired" }
  | { name: "error"; category: string | null };

/** อ่านโทเคนจาก URL ฝั่งเบราว์เซอร์ แล้วเรียก GET เพื่อแสดงชื่อชนิด ยกเลิกจริงเมื่อกดปุ่มเท่านั้น */
export default function UnsubscribePanel() {
  const auth = useAuth();
  const [phase, setPhase] = useState<Phase>({ name: "loading" });
  const tokenRef = useRef("");
  const busyRef = useRef(false);
  const settingsHref = emailSettingsHref(!(auth.loaded && isSignedOut(auth)));

  useEffect(() => {
    const token = readUnsubscribeToken(new URLSearchParams(window.location.search).get("token"));
    tokenRef.current = token;
    if (!token) {
      setPhase({ name: "invalid" });
      return;
    }
    let cancel = false;
    api.previewUnsubscribe(token).then((body) => {
      if (cancel) return;
      setPhase(phaseFromPreview(mapUnsubscribePreview(200, body)));
    }).catch((err) => {
      if (cancel) return;
      const status = err instanceof ApiError ? err.status : 0;
      setPhase(phaseFromPreview(mapUnsubscribePreview(status, null)));
    });
    return () => { cancel = true; };
  }, []);

  const confirm = () => {
    const token = tokenRef.current;
    if (!token || busyRef.current) return;
    const category = phase.name === "confirm" || phase.name === "error" ? phase.category : null;
    busyRef.current = true;
    setPhase({ name: "submitting", category });
    api.unsubscribeNotifications(token).then((body) => {
      const outcome = mapUnsubscribeResponse(200, body);
      setPhase(phaseFromPost(outcome, category));
    }).catch((err) => {
      const status = err instanceof ApiError ? err.status : 0;
      setPhase(phaseFromPost(mapUnsubscribeResponse(status, null), category));
    }).finally(() => { busyRef.current = false; });
  };

  return (
    <main className="page narrow">
      <BrandLockup />
      <section className="card unsub-card" aria-busy={phase.name === "loading" || phase.name === "submitting"}>
        {phase.name === "loading" ? (
          <div role="status">
            <span className="sr-only">{tx("กำลังโหลด...")}</span>
            <Skel width="14em" />
          </div>
        ) : phase.name === "confirm" || phase.name === "submitting" ? (
          <Confirm
            category={phase.category}
            busy={phase.name === "submitting"}
            settingsHref={settingsHref}
            onConfirm={confirm}
          />
        ) : phase.name === "success" ? (
          <Success category={phase.category} settingsHref={settingsHref} />
        ) : phase.name === "expired" ? (
          <Expired settingsHref={settingsHref} />
        ) : phase.name === "error" ? (
          <Failed category={phase.category} settingsHref={settingsHref} onRetry={confirm} />
        ) : (
          <Invalid settingsHref={settingsHref} />
        )}
      </section>
    </main>
  );
}

function phaseFromPreview(view: ReturnType<typeof mapUnsubscribePreview>): Phase {
  if (view.state === "confirm") return { name: "confirm", category: view.category };
  if (view.state === "expired") return { name: "expired" };
  return { name: "invalid" };
}

function phaseFromPost(view: ReturnType<typeof mapUnsubscribeResponse>, fallback: string | null): Phase {
  if (view.state === "success") return { name: "success", category: view.category };
  if (view.state === "expired") return { name: "expired" };
  if (view.state === "invalid") return { name: "invalid" };
  return { name: "error", category: fallback };
}

function CategoryBox({ category, done }: { category: string | null; done?: boolean }) {
  const label = category ? categoryLabel(category) : null;
  const desc = category && isEmailPrefKind(category) ? EMAIL_PREF_DESC[category] : null;
  const title = label
    ? (done ? tx(label) : tx("ยกเลิกอีเมล {kind}", { kind: tx(label) }))
    : tx(confirmCategoryLine(null));
  return (
    <div className="unsub-cat">
      <b>{title}</b>
      <span>
        {desc
          ? (done ? `${tx("ปิดแล้ว")} · ${tx(desc)}` : tx(desc))
          : tx(GENERIC_HINT)}
      </span>
    </div>
  );
}

function Confirm({
  category, busy, settingsHref, onConfirm,
}: {
  category: string | null;
  busy: boolean;
  settingsHref: string;
  onConfirm: () => void;
}) {
  return (
    <>
      <h1>{busy ? tx(SUBMITTING_TITLE) : tx(CONFIRM_TITLE)}</h1>
      <p className="muted">{busy ? tx("กรุณารอสักครู่ อย่าปิดหน้านี้") : tx(CONFIRM_BODY)}</p>
      <CategoryBox category={category} />
      <div className="unsub-actions">
        <button type="button" className="btn primary" onClick={onConfirm} disabled={busy} aria-busy={busy}>
          {busy ? tx("กำลังบันทึก") : tx(CONFIRM_BUTTON)}
        </button>
        {!busy && <Link href={settingsHref} className="btn">{tx("ไปหน้าตั้งค่า")}</Link>}
      </div>
    </>
  );
}

function Success({ category, settingsHref }: { category: string; settingsHref: string }) {
  const label = categoryLabel(category);
  return (
    <>
      <h1>{tx(SUCCESS_TITLE)}</h1>
      <p className="muted">
        {label
          ? tx("จะไม่ส่งอีเมล «{kind}» ไปที่บัญชีนี้อีก การแจ้งเตือนในแอปยังแสดงที่กระดิ่งตามเดิม", { kind: tx(label) })
          : tx("จะไม่ส่งอีเมลแจ้งเตือนนี้ไปที่บัญชีนี้อีก การแจ้งเตือนในแอปยังแสดงที่กระดิ่งตามเดิม")}
      </p>
      <CategoryBox category={category} done />
      <div className="unsub-actions">
        <Link href={settingsHref} className="btn primary">{tx("ไปหน้าตั้งค่าอีเมล")}</Link>
      </div>
      {label && (
        <p className="muted">
          {tx("ถ้าต้องการรับอีกครั้ง เข้าสู่ระบบแล้วเปิดสวิตช์ «{kind}» ที่หน้าตั้งค่าบัญชี", { kind: tx(label) })}
        </p>
      )}
    </>
  );
}

function Expired({ settingsHref }: { settingsHref: string }) {
  return (
    <div className="unsub-expired" role="status">
      <h1>{tx(EXPIRED_TITLE)}</h1>
      <p className="muted">{tx(EXPIRED_BODY)}</p>
      <div className="unsub-actions">
        <Link href={settingsHref} className="btn primary">{tx(EXPIRED_BUTTON)}</Link>
      </div>
    </div>
  );
}

function Invalid({ settingsHref }: { settingsHref: string }) {
  return (
    <>
      <h1>{tx(INVALID_TITLE)}</h1>
      <p className="muted">{tx(INVALID_BODY)}</p>
      <div className="unsub-actions">
        <Link href={settingsHref} className="btn primary">{tx(INVALID_BUTTON)}</Link>
      </div>
    </>
  );
}

function Failed({
  category, settingsHref, onRetry,
}: {
  category: string | null;
  settingsHref: string;
  onRetry: () => void;
}) {
  return (
    <>
      <h1>{tx(ERROR_TITLE)}</h1>
      <div className="alert error" role="alert">{tx(ERROR_BODY)}</div>
      {category && <CategoryBox category={category} />}
      <div className="unsub-actions">
        <button type="button" className="btn primary" onClick={onRetry}>{tx("ลองอีกครั้ง")}</button>
        <Link href={settingsHref} className="btn">{tx("ไปหน้าตั้งค่า")}</Link>
      </div>
    </>
  );
}
