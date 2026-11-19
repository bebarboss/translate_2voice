"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { createPortal } from "react-dom";
import { api, type AppNotification } from "@/lib/api";
import { tx } from "@/lib/i18n";
import {
  badgeText,
  bellAriaLabel,
  internalNotifPath,
  notifIcon,
  relativeTime,
  type NotifIcon,
} from "@/lib/notifications";
import { AlertIcon, BellIcon, CheckIcon, CoinIcon, DocIcon, MicIcon, NeutralIcon, RetryIcon } from "./Icons";

const POLL_MS = 60_000;
const MOBILE_MQ = "(max-width: 900px)";
const SKELETON_ROWS = 4;
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])';

type Placement = "sidebar" | "topbar";

function focusable(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.hasAttribute("disabled"));
}

function KindGlyph({ kind }: { kind: string }) {
  const icon: NotifIcon = notifIcon(kind);
  const size = 18;
  switch (icon) {
    case "done": return <CheckIcon size={size} />;
    case "fail": return <AlertIcon size={size} />;
    case "credits": return <CoinIcon size={size} />;
    case "review": return <DocIcon size={size} />;
    case "actor": return <MicIcon size={size} />;
    default: return <NeutralIcon size={size} />;
  }
}

function Item({ n, onOpen }: { n: AppNotification; onOpen: (n: AppNotification) => void }) {
  const icon = notifIcon(n.kind);
  const when = relativeTime(n.created_at, Date.now() / 1000);
  const stamp = Number.isFinite(n.created_at) ? new Date(n.created_at * 1000).toISOString() : undefined;
  const inner = (
    <>
      {!n.read && <span className="sr-only">{tx("ยังไม่อ่าน")}</span>}
      <span className={`bell-ico ${icon}`} aria-hidden="true"><KindGlyph kind={n.kind} /></span>
      <span className="bell-txt">
        <span className="bell-title">{n.title}</span>
        {n.body ? <span className="bell-body">{n.body}</span> : null}
        <time dateTime={stamp}>{tx(when.template, "n" in when ? { n: when.n } : undefined)}</time>
      </span>
      <span className={`bell-dot${n.read ? " off" : ""}`} aria-hidden="true" />
    </>
  );
  const href = internalNotifPath(n.link);
  const activate = (e: ReactMouseEvent) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    onOpen(n);
  };
  if (href) {
    return (
      <Link href={href} className={`bell-item${n.read ? "" : " unread"}`} onClick={activate}>{inner}</Link>
    );
  }
  return (
    <button type="button" className={`bell-item${n.read ? "" : " unread"}`} onClick={() => onOpen(n)}>{inner}</button>
  );
}

/** กระดิ่งในหัวไซด์บาร์ (เดสก์ท็อป) หรือแถบบน (มือถือ) โพลล์จำนวนที่ยังไม่อ่านทุก 60 วินาทีเฉพาะแท็บที่มองเห็น */
export default function NotificationBell({ enabled, placement }: { enabled: boolean; placement: Placement }) {
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AppNotification[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [loadId, setLoadId] = useState(0);
  const [active, setActive] = useState(false);
  const [live, setLive] = useState("");
  const wrapRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef(false);
  const seenUnread = useRef<number | null>(null);
  const readingAll = useRef(false);
  const panelId = useId();
  const titleId = useId();
  const sheet = placement === "topbar";

  const refreshCount = useCallback(() => {
    api.notificationsUnread().then((r) => setUnread(r.unread)).catch(() => { /* ชั่วคราว ลองใหม่รอบหน้า */ });
  }, []);

  useEffect(() => {
    const mq = window.matchMedia(MOBILE_MQ);
    const sync = () => {
      const on = (placement === "topbar") === mq.matches;
      setActive(on);
      if (!on) setOpen(false);
    };
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, [placement]);

  useEffect(() => {
    if (!enabled || !active) return;
    refreshCount();
    const tick = () => { if (document.visibilityState === "visible") refreshCount(); };
    const id = window.setInterval(tick, POLL_MS);
    document.addEventListener("visibilitychange", tick);
    return () => { window.clearInterval(id); document.removeEventListener("visibilitychange", tick); };
  }, [enabled, active, refreshCount]);

  useEffect(() => {
    if (seenUnread.current !== null && unread > seenUnread.current) {
      const label = bellAriaLabel(unread);
      setLive(tx(label.template, "n" in label ? { n: label.n } : undefined));
    }
    seenUnread.current = unread;
  }, [unread]);

  useEffect(() => {
    if (!open) return;
    let cancel = false;
    setFailed(false);
    setItems(null);
    api.notifications().then((r) => {
      if (cancel) return;
      setItems(r.items);
      setUnread(r.unread);
    }).catch(() => { if (!cancel) setFailed(true); });
    return () => { cancel = true; };
  }, [open, loadId]);

  const close = useCallback((restore: boolean) => {
    restoreFocus.current = restore;
    setOpen(false);
  }, []);

  useEffect(() => {
    if (!open) {
      if (restoreFocus.current) {
        restoreFocus.current = false;
        btnRef.current?.focus();
      }
      return;
    }
    const panel = panelRef.current;
    if (!panel) return;
    let main: HTMLElement | null = null;
    let prevOverflow = "";
    if (sheet) {
      const bar = btnRef.current?.closest(".topbar");
      const height = bar instanceof HTMLElement ? bar.getBoundingClientRect().height : 61;
      panel.style.top = `${Math.max(0, Math.round(height))}px`;
      const found = document.querySelector(".shell-main");
      if (found instanceof HTMLElement) {
        main = found;
        prevOverflow = main.style.overflow;
        main.style.overflow = "hidden";
      }
    }
    panel.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        close(true);
        return;
      }
      if (!sheet || e.key !== "Tab") return;
      const list = focusable(panel);
      if (list.length === 0) {
        e.preventDefault();
        panel.focus();
        return;
      }
      const first = list[0];
      const last = list[list.length - 1];
      const current = document.activeElement;
      const inside = current instanceof HTMLElement && panel.contains(current) && list.includes(current);
      if (e.shiftKey) {
        if (!inside || current === first) {
          e.preventDefault();
          last.focus();
        }
      } else if (!inside || current === last) {
        e.preventDefault();
        first.focus();
      }
    };
    const onDown = (e: MouseEvent) => {
      const target = e.target;
      if (!(target instanceof Node)) return;
      if (wrapRef.current?.contains(target)) return;
      if (panel.contains(target)) return;
      close(true);
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("mousedown", onDown);
    return () => {
      if (main) main.style.overflow = prevOverflow;
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open, sheet, close]);

  const openItem = (n: AppNotification) => {
    close(false);
    if (n.read) return;
    setItems((cur) => cur && cur.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
    setUnread((u) => Math.max(0, u - 1));
    api.readNotification(n.id).then((r) => setUnread(r.unread)).catch(() => undefined);
  };

  const readAll = () => {
    if (readingAll.current) return;
    readingAll.current = true;
    const prevItems = items;
    const prevUnread = unread;
    setItems((cur) => cur && cur.map((x) => ({ ...x, read: true })));
    setUnread(0);
    panelRef.current?.focus();
    api.readAllNotifications().then((r) => setUnread(r.unread)).catch(() => {
      setItems(prevItems);
      setUnread(prevUnread);
      refreshCount();
    }).finally(() => { readingAll.current = false; });
  };

  if (!enabled) return null;

  const badge = badgeText(unread);
  const label = bellAriaLabel(unread);
  const aria = tx(label.template, "n" in label ? { n: label.n } : undefined);
  const showReadAll = items !== null && !failed && unread > 0;
  const showCount = items !== null && !failed && items.length > 0 && unread > 0;
  const showFoot = items !== null && !failed;
  const statusId = `${panelId}-status`;
  const describe = failed || (items !== null && items.length === 0);

  const panel = (
    <div
      ref={panelRef}
      id={panelId}
      className={sheet ? "bell-sheet" : "bell-pop"}
      role="dialog"
      aria-modal={sheet ? true : undefined}
      aria-labelledby={titleId}
      aria-describedby={describe ? statusId : undefined}
      aria-busy={items === null && !failed ? true : undefined}
      tabIndex={-1}
    >
      {sheet && <div className="bell-handle" aria-hidden="true" />}
      <div className="bell-head">
        <h2 id={titleId}>
          {tx("การแจ้งเตือน")}
          {showCount && <span className="bell-count"><span className="sr-only"> </span>{tx("{n} ที่ยังไม่อ่าน", { n: unread })}</span>}
        </h2>
        {showReadAll && (
          <button type="button" className="bell-readall" onClick={readAll}>{tx("อ่านทั้งหมด")}</button>
        )}
      </div>
      {failed ? (
        <div className="bell-state" id={statusId} role="alert">
          <div className="bell-illo fail" aria-hidden="true"><AlertIcon size={28} /></div>
          <b>{tx("โหลดการแจ้งเตือนไม่ได้")}</b>
          <p>{tx("ลองใหม่อีกครั้ง")}</p>
          <button type="button" className="bell-retry" onClick={() => setLoadId((n) => n + 1)}>
            <RetryIcon />{tx("ลองอีกครั้ง")}
          </button>
        </div>
      ) : items === null ? (
        <div className="bell-list" role="status" aria-busy="true" aria-label={tx("กำลังโหลดการแจ้งเตือน")}>
          <span className="sr-only">{tx("กำลังโหลด…")}</span>
          {Array.from({ length: SKELETON_ROWS }, (_, i) => (
            <div className="bell-skel" key={i} aria-hidden="true">
              <i className="c" />
              <span className="lines"><i className="l1" /><i className="l2" /><i className="l3" /></span>
            </div>
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="bell-state" id={statusId}>
          <div className="bell-illo" aria-hidden="true"><BellIcon size={28} /></div>
          <b>{tx("ยังไม่มีการแจ้งเตือน")}</b>
          <p>{tx("เมื่องานรอตรวจบท พากย์เสร็จ ไม่สำเร็จ หรือเครดิตใกล้หมด จะแสดงที่นี่")}</p>
        </div>
      ) : (
        <div className="bell-list">
          {items.map((n) => <Item key={n.id} n={n} onOpen={openItem} />)}
        </div>
      )}
      {showFoot && (
        <div className="bell-foot">
          <Link href="/account?tab=prefs" onClick={() => close(false)}>{tx("ไปตั้งค่าอีเมล")}</Link>
        </div>
      )}
    </div>
  );

  return (
    <div className="menu-wrap bell-wrap" ref={wrapRef}>
      <button
        ref={btnRef}
        type="button"
        className="icon-only bell-btn"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={aria}
        onClick={() => {
          if (open) close(true);
          else {
            setFailed(false);
            setItems(null);
            setOpen(true);
          }
        }}
      >
        <BellIcon />
        {badge && <span className="bell-badge" aria-hidden="true">{badge}</span>}
      </button>
      <span className="sr-only" aria-live="polite">{live}</span>
      {open && sheet && typeof document !== "undefined" ? createPortal(panel, document.body) : null}
      {open && !sheet ? panel : null}
    </div>
  );
}
