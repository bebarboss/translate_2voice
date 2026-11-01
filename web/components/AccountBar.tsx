"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Plan, type Wallet } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";

const fmtDate = (unix: number) =>
  new Date(unix * 1000).toLocaleDateString("th-TH", { day: "numeric", month: "short" });

/** แถบบนของเนื้อหา: แพ็กเกจปัจจุบันและเครดิตคงเหลือ (เฉพาะตอนเปิดระบบเครดิตและล็อกอินแล้ว)
 * โหลดใหม่ทุกครั้งที่เปลี่ยนหน้า ยอดจะตามทันหลังส่งงานหรือซื้อเครดิต */
export default function AccountBar() {
  const path = usePathname();
  const { config, user } = useAuth();
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const show = !!config?.billing && !!user && !/^\/(welcome|login)/.test(path);

  useEffect(() => {
    if (!show) return;
    api.wallet().then(setWallet).catch(() => setWallet(null));
  }, [show, path]);
  useEffect(() => {
    if (show) api.plans().then((p) => setPlans(p.plans)).catch(() => setPlans([]));
  }, [show]);

  if (!show || !user) return null;
  const sub = wallet?.subscription;
  const plan = plans.find((p) => p.id === sub?.plan_id);
  const total = (wallet?.credits ?? 0) + (sub?.minutes_left ?? 0);
  return (
    <div className="account-bar" role="region" aria-label="แพ็กเกจและเครดิต">
      <Link href="/account" className="account-chip account-plan">
        <span className="dim">แพ็กเกจ</span>
        <span className="account-plan-name">{user.admin ? "ผู้ดูแลระบบ" : sub && plan ? `${plan.name} · ถึง ${fmtDate(sub.expires_at)}` : "ยังไม่มี"}</span>
      </Link>
      <Link href="/account" className="account-chip">
        <span className="account-credits">{user.admin ? "ไม่จำกัด" : wallet ? total.toLocaleString() : "..."}</span>
        <span className="dim">เครดิต</span>
      </Link>
      {!user.admin && <Link href="/account" className="btn primary small">เติมเครดิต</Link>}
    </div>
  );
}
