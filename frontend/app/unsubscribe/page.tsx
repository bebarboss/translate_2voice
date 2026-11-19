import { Suspense } from "react";
import type { Metadata } from "next";
import UnsubscribePanel from "./panel";

export const metadata: Metadata = {
  title: "ปิดการรับอีเมล",
  robots: "noindex, nofollow",
  referrer: "no-referrer",
};

/** หน้าสาธารณะ อ่านโทเคนครั้งเดียวแล้วเอา query ออกจากแถบที่อยู่ */
export default function UnsubscribePage() {
  return (
    <Suspense fallback={<main className="page narrow" role="status"><span className="sr-only">กำลังโหลด...</span></main>}>
      <UnsubscribePanel />
    </Suspense>
  );
}
