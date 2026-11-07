"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Job, type Wallet } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { tx } from "@/lib/i18n";
import { useAuth } from "@/lib/useAuth";
import AccountMenu from "./AccountMenu";
import { BrandLink } from "./Brand";
import { FolderIcon, GearIcon, GridIcon, ListIcon, MenuIcon, MicIcon, PlusIcon, ScissorsIcon, UserIcon, WaveIcon, XIcon } from "./Icons";

const LINKS = [
  { href: "/dashboard", label: "ภาพรวม", icon: <GridIcon size={16} /> },
  { href: "/", label: "งานใหม่", icon: <PlusIcon size={16} /> },
  { href: "/timeline", label: "นำเข้าไทม์ไลน์", icon: <ScissorsIcon size={16} /> },
  { href: "/jobs", label: "งานทั้งหมด", icon: <ListIcon /> },
  { href: "/projects", label: "โปรเจกต์", icon: <FolderIcon size={16} /> },
  { href: "/voices", label: "คลังเสียง", icon: <WaveIcon /> },
  { href: "/settings", label: "ตั้งค่า", icon: <GearIcon /> },
];
const RECENT = 6;
// หน้าที่ไม่มีเมนูซ้าย (มีโครงของตัวเอง)
const BARE = /^\/(welcome|login|onboarding|terms|privacy|actor-consent)/;

/** เครดิตคงเหลือท้ายเมนู (เมื่อเปิดระบบเครดิต) โหลดใหม่เมื่อเปลี่ยนหน้า ทุก 20 วินาที และตอนกลับมาที่แท็บ */
function CreditCard({ path }: { path: string }) {
  const [wallet, setWallet] = useState<Wallet | null>(null);
  useEffect(() => {
    const load = () => { if (!document.hidden) api.wallet().then(setWallet).catch(() => {}); };
    load();
    const timer = setInterval(load, 20_000);
    document.addEventListener("visibilitychange", load);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", load); };
  }, [path]);
  const total = (wallet?.credits ?? 0) + (wallet?.subscription?.minutes_left ?? 0);
  return (
    <Link href="/promotions" className="credit-card">
      <div>
        <b>{wallet ? tx("{0} เครดิต", { 0: fmtNum(total) }) : "..."}</b>
        <span>{tx("เติมเครดิตหรือซื้อแพ็กเกจ")}</span>
      </div>
      <i aria-hidden="true"><PlusIcon size={16} /></i>
    </Link>
  );
}

/** เมนูหลักด้านซ้าย: เมนู งานล่าสุด เครดิต และปุ่มบัญชี จอเล็กหุบเป็นแถบบนพร้อมปุ่มเปิดเมนู */
export default function Sidebar() {
  const path = usePathname();
  const isActive = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const { config, user, loaded } = useAuth();
  const [open, setOpen] = useState(false);
  const [recent, setRecent] = useState<Job[] | null>(null);
  const bare = BARE.test(path);
  const canLoad = loaded && !bare && (!config?.auth || !!user);
  useEffect(() => setOpen(false), [path]); // เปลี่ยนหน้าแล้วปิดเมนูบนจอเล็ก
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  useEffect(() => {
    if (!canLoad) return;
    // รอหลัง auth เสร็จเล็กน้อย ไม่แย่งคิวกับ /me ตอนเปิดหน้า
    const t = window.setTimeout(() => {
      api.listJobs().then((j) => setRecent(j.slice(0, RECENT))).catch(() => setRecent([]));
    }, 100);
    return () => clearTimeout(t);
  }, [canLoad, path]);
  if (bare) return null;

  const brand = <BrandLink href="/dashboard" />;
  const jobId = path.match(/^\/jobs\/([^/]+)/)?.[1];
  return (
    <>
      <div className="topbar">
        {brand}
        <button type="button" className="icon-only" aria-label={tx("เปิดเมนู")} aria-expanded={open} aria-controls="sidebar"
          onClick={() => setOpen(true)}><MenuIcon /></button>
      </div>
      {open && <div className="sidebar-backdrop" onClick={() => setOpen(false)} />}
      <aside id="sidebar" className={`sidebar${open ? " open" : ""}`}>
        <div className="sidebar-head">
          {brand}
          <button type="button" className="icon-only sidebar-close" aria-label={tx("ปิดเมนู")} onClick={() => setOpen(false)}>
            <XIcon size={18} />
          </button>
        </div>
        <div className="side-scroll">
          <nav className="side-nav" aria-label={tx("เมนูหลัก")}>
            {LINKS.map((l) => (
              <Link key={l.href} href={l.href} aria-current={isActive(l.href) && !(l.href === "/jobs" && jobId) ? "page" : undefined}>
                {l.icon}{tx(l.label)}
              </Link>
            ))}
            {config?.auth && user && (
              <Link href="/actor" aria-current={path === "/actor" ? "page" : undefined}><MicIcon size={16} />{tx("นักพากย์")}</Link>
            )}
            {config?.auth && user?.admin && (
              <Link href="/actors" aria-current={isActive("/actors") ? "page" : undefined}><UserIcon size={16} />{tx("ตรวจนักพากย์")}</Link>
            )}
          </nav>
          {(!config?.auth || user) && (
            <nav className="side-section side-recent" aria-label={tx("งานล่าสุด")}>
              <span className="side-label">{tx("งานล่าสุด")}</span>
              {recent === null ? null : recent.length === 0 ? <span className="side-empty">{tx("ยังไม่มีงาน")}</span> : (
                <>
                  {recent.map((j) => (
                    <Link key={j.id} href={`/jobs/${j.id}`} aria-current={jobId === j.id ? "page" : undefined} title={j.filename}>
                      <span className="sq" aria-hidden="true">{j.filename.slice(0, 1).toUpperCase()}</span>
                      <span className="nm">{j.filename}</span>
                    </Link>
                  ))}
                  <Link href="/jobs" className="side-more">{tx("ดูงานทั้งหมด")}</Link>
                </>
              )}
            </nav>
          )}
        </div>
        <div className="side-bottom">
          {config?.billing && user && !user.admin && <CreditCard path={path} />}
          {config?.auth && !user ? (
            <div className="row" style={{ justifyContent: "space-between" }}>
              <Link href="/login" className="btn small">{tx("เข้าสู่ระบบ")}</Link>
              <AccountMenu config={config} user={null} />
            </div>
          ) : <AccountMenu config={config} user={user} />}
        </div>
      </aside>
    </>
  );
}
