"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/useAuth";
import { GearIcon, ListIcon, MenuIcon, MicIcon, UploadIcon, UserIcon, WaveIcon, XIcon } from "./Icons";

const LINKS = [
  { href: "/", label: "อัปโหลด", icon: <UploadIcon size={18} /> },
  { href: "/jobs", label: "งานทั้งหมด", icon: <ListIcon /> },
  { href: "/voices", label: "คลังเสียง", icon: <WaveIcon /> },
  { href: "/settings", label: "ตั้งค่า", icon: <GearIcon /> },
];

/** เมนูหลักด้านซ้าย จอเล็กหุบเป็นแถบบนพร้อมปุ่มเปิดเมนู */
export default function Sidebar() {
  const path = usePathname();
  const isActive = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const { config, user } = useAuth();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [path]); // เปลี่ยนหน้าแล้วปิดเมนูบนจอเล็ก
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  // หน้าแรกก่อนเข้าสู่ระบบมีเมนูของตัวเอง หน้าเข้าสู่ระบบเป็นหน้าเดี่ยว
  if (path.startsWith("/welcome") || path.startsWith("/login") || path.startsWith("/onboarding")
    || path.startsWith("/terms") || path.startsWith("/privacy")) return null;

  const brand = (
    <Link href="/" className="brand">
      <span className="brand-mark"><MicIcon size={18} color="#1A0E06" /></span>
      Dubbing Studio
    </Link>
  );
  return (
    <>
      <div className="topbar">
        {brand}
        <button type="button" className="icon-only" aria-label="เปิดเมนู" aria-expanded={open} aria-controls="sidebar"
          onClick={() => setOpen(true)}><MenuIcon /></button>
      </div>
      {open && <div className="sidebar-backdrop" onClick={() => setOpen(false)} />}
      <aside id="sidebar" className={`sidebar${open ? " open" : ""}`}>
        <div className="sidebar-head">
          {brand}
          <button type="button" className="icon-only sidebar-close" aria-label="ปิดเมนู" onClick={() => setOpen(false)}>
            <XIcon size={18} />
          </button>
        </div>
        <nav className="side-nav" aria-label="เมนูหลัก">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} aria-current={isActive(l.href) ? "page" : undefined}>
              {l.icon}{l.label}
            </Link>
          ))}
          {config?.auth && user && (
            <Link href="/actor" aria-current={path === "/actor" ? "page" : undefined}><MicIcon />นักพากย์</Link>
          )}
          {config?.auth && user?.admin && (
            <Link href="/actors" aria-current={isActive("/actors") ? "page" : undefined}><UserIcon />ตรวจนักพากย์</Link>
          )}
        </nav>
        {config?.auth && (
          <div className="side-foot">
            {user ? (
              <Link href="/account" className="side-user" aria-current={isActive("/account") ? "page" : undefined}>
                <span className="side-avatar">{user.name.slice(0, 1).toUpperCase()}</span>
                <span className="side-user-text">
                  <span>{user.name}</span>
                  <span className="dim">{user.admin ? "ผู้ดูแลระบบ" : user.email}</span>
                </span>
              </Link>
            ) : (
              <nav className="side-nav" aria-label="บัญชี">
                <Link href="/login" aria-current={isActive("/login") ? "page" : undefined}><UserIcon />เข้าสู่ระบบ</Link>
              </nav>
            )}
          </div>
        )}
      </aside>
    </>
  );
}
