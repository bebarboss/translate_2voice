"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, type AuthConfig, type User } from "@/lib/api";
import { chooseLang, chooseTheme, currentTheme, getLang, tx, type Lang, type Theme } from "@/lib/i18n";
import { FlagIcon, GearIcon, ShieldIcon, TagIcon, UserIcon } from "./Icons";

const LANGS: [Lang, string][] = [["th", "ไทย"], ["en", "English"]];
const THEMES: [Theme, string][] = [["system", "อัตโนมัติ"], ["dark", "มืด"], ["light", "สว่าง"]];

const Chevron = () => <span aria-hidden="true" style={{ color: "var(--dim)" }}>›</span>;
const GlobeIcon = () => (
  <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z" />
  </svg>
);
const ThemeIcon = () => (
  <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
    <circle cx="12" cy="12" r="9" /><path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor" />
  </svg>
);
const LogoutIcon = () => (
  <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3" /><path d="M10 17l-5-5 5-5" /><path d="M5 12h11" />
  </svg>
);

/** ปุ่มรูปโปรไฟล์ท้ายเมนูซ้าย กดแล้วเปิดเมนู: โปรไฟล์ แพ็กเกจ ผู้ดูแล ภาษา ธีม ออกจากระบบ
 * ปิดระบบบัญชีอยู่ (ไม่มีผู้ใช้) เหลือแค่ภาษาและธีม */
export default function AccountMenu({ config, user }: { config: AuthConfig | null; user: User | null }) {
  const [open, setOpen] = useState(false);
  const [sub, setSub] = useState<"" | "lang" | "theme">("");
  const [theme, setTheme] = useState<Theme>("system");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => setTheme(currentTheme()), []);
  useEffect(() => {
    if (!open) { setSub(""); return; }
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const logout = async () => {
    await api.logout().catch(() => undefined);
    window.location.href = "/login";
  };
  const lang = getLang();
  const initial = user ? user.name.slice(0, 1).toUpperCase() : "";
  return (
    <div className="menu-wrap" ref={ref}>
      <button type="button" className="me-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}
        aria-label={user ? tx("เมนูบัญชีของ {0}", { 0: user.name }) : tx("ภาษาและธีม")}>
        {user ? <span className="avatar-dot">{initial}</span> : <span className="avatar-dot plain"><GearIcon /></span>}
      </button>
      {open && (
        <div className="menu" role="menu">
          {user && (
            <>
              <div className="menu-head">
                <span className="avatar-dot lg">{initial}</span>
                <div style={{ minWidth: 0 }}>
                  <b>{user.name}</b>
                  <span>{user.email}</span>
                </div>
              </div>
              <hr />
              <Link role="menuitem" href="/account" className="menu-item" onClick={() => setOpen(false)}><UserIcon />{tx("โปรไฟล์และการตั้งค่า")}</Link>
              {config?.billing && !user.admin && (
                <Link role="menuitem" href="/promotions" className="menu-item" onClick={() => setOpen(false)}><TagIcon />{tx("แพ็กเกจและโปรโมชัน")}</Link>
              )}
              <Link role="menuitem" href="/support" className="menu-item" onClick={() => setOpen(false)}><FlagIcon />{tx("แจ้งปัญหา")}</Link>
              {user.admin && (
                <Link role="menuitem" href="/admin" className="menu-item" onClick={() => setOpen(false)}><ShieldIcon />{tx("ผู้ดูแลระบบ")}</Link>
              )}
              <hr />
            </>
          )}
          <div style={{ position: "relative" }} onMouseEnter={() => setSub("lang")}>
            <button type="button" role="menuitem" className="menu-item" aria-haspopup="menu" aria-expanded={sub === "lang"}
              onClick={() => setSub(sub === "lang" ? "" : "lang")}>
              <GlobeIcon /><span className="grow">{tx("ภาษา")}</span><span className="hint">{lang === "en" ? "English" : "ไทย"}</span><Chevron />
            </button>
            {sub === "lang" && (
              <div className="submenu" role="menu">
                {LANGS.map(([k, label]) => (
                  <span key={k} role="menuitemradio" aria-checked={lang === k} tabIndex={0} lang={k} className="menu-item"
                    onClick={() => chooseLang(k)} onKeyDown={(e) => e.key === "Enter" && chooseLang(k)}>{label}</span>
                ))}
              </div>
            )}
          </div>
          <div style={{ position: "relative" }} onMouseEnter={() => setSub("theme")}>
            <button type="button" role="menuitem" className="menu-item" aria-haspopup="menu" aria-expanded={sub === "theme"}
              onClick={() => setSub(sub === "theme" ? "" : "theme")}>
              <ThemeIcon /><span className="grow">{tx("ธีม")}</span><span className="hint">{tx(THEMES.find(([k]) => k === theme)![1])}</span><Chevron />
            </button>
            {sub === "theme" && (
              <div className="submenu" role="menu">
                {THEMES.map(([k, label]) => (
                  <span key={k} role="menuitemradio" aria-checked={theme === k} tabIndex={0} className="menu-item"
                    onClick={() => { chooseTheme(k); setTheme(k); }}
                    onKeyDown={(e) => { if (e.key === "Enter") { chooseTheme(k); setTheme(k); } }}>{tx(label)}</span>
                ))}
              </div>
            )}
          </div>
          {user && (
            <>
              <hr />
              <button type="button" role="menuitem" className="menu-item" onClick={logout} onMouseEnter={() => setSub("")}><LogoutIcon />{tx("ออกจากระบบ")}</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
