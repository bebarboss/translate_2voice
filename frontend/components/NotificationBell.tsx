"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AppNotification } from "@/lib/api";
import { tx } from "@/lib/i18n";
import { BellIcon } from "./Icons";

const POLL_MS = 60_000;

/** เวลาแบบสั้น (เมื่อกี้ / x นาทีที่แล้ว / x ชั่วโมงที่แล้ว / x วันที่แล้ว) */
function ago(ts: number): string {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return tx("เมื่อกี้");
  if (s < 3600) return tx("{n} นาทีที่แล้ว", { n: Math.floor(s / 60) });
  if (s < 86400) return tx("{n} ชั่วโมงที่แล้ว", { n: Math.floor(s / 3600) });
  return tx("{n} วันที่แล้ว", { n: Math.floor(s / 86400) });
}

/** กระดิ่งแจ้งเตือนในแอป โพลล์เฉพาะจำนวนที่ยังไม่อ่านทุก 60 วินาที (เฉพาะตอนแท็บเปิดอยู่) เปิดแล้วค่อยโหลดรายการ */
export default function NotificationBell({ enabled }: { enabled: boolean }) {
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AppNotification[] | null>(null);
  const [failed, setFailed] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const refreshCount = useCallback(() => {
    api.notificationsUnread().then((r) => setUnread(r.unread)).catch(() => { /* ชั่วคราว ลองใหม่รอบหน้า */ });
  }, []);

  useEffect(() => {
    if (!enabled) return;
    refreshCount();
    const tick = () => { if (document.visibilityState === "visible") refreshCount(); };
    const id = window.setInterval(tick, POLL_MS);
    document.addEventListener("visibilitychange", tick);
    return () => { window.clearInterval(id); document.removeEventListener("visibilitychange", tick); };
  }, [enabled, refreshCount]);

  useEffect(() => {
    if (!open) return;
    setFailed(false);
    api.notifications().then((r) => { setItems(r.items); setUnread(r.unread); }).catch(() => setFailed(true));
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  if (!enabled) return null;

  const readOne = (n: AppNotification) => {
    setOpen(false);
    if (n.read) return;
    setItems((cur) => cur && cur.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
    setUnread((u) => Math.max(0, u - 1));
    api.readNotification(n.id).then((r) => setUnread(r.unread)).catch(() => undefined);
  };
  const readAll = () => {
    setItems((cur) => cur && cur.map((x) => ({ ...x, read: true })));
    setUnread(0);
    api.readAllNotifications().catch(() => refreshCount());
  };

  const label = unread > 0 ? tx("การแจ้งเตือน ({n} ยังไม่อ่าน)", { n: unread }) : tx("การแจ้งเตือน");
  return (
    <div className="menu-wrap bell-wrap" ref={ref}>
      <button type="button" className="icon-only bell-btn" aria-haspopup="dialog" aria-expanded={open} aria-label={label}
        onClick={() => setOpen(!open)}>
        <BellIcon />
        {unread > 0 && <span className="bell-badge" aria-hidden="true">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div className="bell-pop" role="dialog" aria-label={tx("การแจ้งเตือน")}>
          <div className="bell-head">
            <b>{tx("การแจ้งเตือน")}</b>
            {unread > 0 && <button type="button" className="bell-readall" onClick={readAll}>{tx("อ่านทั้งหมด")}</button>}
          </div>
          <div className="bell-list">
            {failed ? <p className="bell-empty">{tx("โหลดการแจ้งเตือนไม่ได้ ลองใหม่อีกครั้ง")}</p>
              : items === null ? <p className="bell-empty">{tx("กำลังโหลด…")}</p>
              : items.length === 0 ? <p className="bell-empty">{tx("ยังไม่มีการแจ้งเตือน")}</p>
              : items.map((n) => {
                const inner = (
                  <>
                    <span className={`bell-dot${n.read ? " read" : ""}`} aria-hidden="true" />
                    <span className="bell-txt">
                      <b>{n.title}</b>
                      {n.body && <span>{n.body}</span>}
                      <time dateTime={new Date(n.created_at * 1000).toISOString()}>{ago(n.created_at)}</time>
                    </span>
                  </>
                );
                return n.link ? (
                  <Link key={n.id} href={n.link} className={`bell-item${n.read ? "" : " unread"}`} onClick={() => readOne(n)}>{inner}</Link>
                ) : (
                  <button key={n.id} type="button" className={`bell-item${n.read ? "" : " unread"}`} onClick={() => readOne(n)}>{inner}</button>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}
