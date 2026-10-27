"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MicIcon } from "./Icons";

const LINKS = [
  { href: "/", label: "อัปโหลด" },
  { href: "/jobs", label: "งานทั้งหมด" },
  { href: "/settings", label: "ตั้งค่า" },
];

export default function Header() {
  const path = usePathname();
  const isActive = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
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
      </nav>
    </header>
  );
}
