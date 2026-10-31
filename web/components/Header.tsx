"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/useAuth";
import { MicIcon } from "./Icons";

const LINKS = [
  { href: "/", label: "อัปโหลด" },
  { href: "/jobs", label: "งานทั้งหมด" },
  { href: "/voices", label: "คลังเสียง" },
  { href: "/settings", label: "ตั้งค่า" },
];

export default function Header() {
  const path = usePathname();
  const isActive = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const { config, user } = useAuth();
  return (
    <header className="header">
      <Link href="/" className="brand">
        <span className="brand-mark"><MicIcon size={18} color="#1A0E06" /></span>
        Dubbing Studio
      </Link>
      <nav className="nav" aria-label="เมนูหลัก">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} aria-current={isActive(l.href) ? "page" : undefined}>
            {l.label}
          </Link>
        ))}
        {config?.auth && (user ? (
          <Link href="/account" aria-current={isActive("/account") ? "page" : undefined}>{user.name}</Link>
        ) : (
          <Link href="/login" aria-current={isActive("/login") ? "page" : undefined}>เข้าสู่ระบบ</Link>
        ))}
      </nav>
    </header>
  );
}
