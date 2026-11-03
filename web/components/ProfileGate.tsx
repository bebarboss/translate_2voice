"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/useAuth";

const FREE = /^\/(onboarding|login|welcome)/;

/** ล็อกอินแล้วแต่ยังไม่ได้กรอกข้อมูลเบื้องต้น → ไปหน้ากรอกข้อมูลก่อน (ผู้ดูแลไม่ต้อง API ก็ไม่บังคับ) */
export default function ProfileGate() {
  const path = usePathname();
  const { config, user } = useAuth();
  useEffect(() => {
    if (config?.auth && user && !user.admin && !user.profile_complete && !FREE.test(path)) {
      window.location.href = `/onboarding?next=${encodeURIComponent(path + window.location.search)}`;
    }
  }, [config, user, path]);
  return null;
}
