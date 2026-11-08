"use client";

import Link from "next/link";
import { tx } from "@/lib/i18n";

/** นำเข้าไทม์ไลน์ — ปิดชั่วคราว (อยู่ระหว่างพัฒนา) */
export default function TimelineImportPage() {
  return (
    <main className="page narrow">
      <h1 style={{ margin: 0, fontSize: 28, fontWeight: 600 }}>{tx("นำเข้าไทม์ไลน์")}</h1>
      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <p className="muted" style={{ margin: 0 }}>
          {tx("ฟีเจอร์นี้อยู่ระหว่างพัฒนา ยังไม่เปิดให้ใช้")}
        </p>
        <p className="dim" style={{ margin: 0 }}>
          {tx("แพ็กเกจมือโปรและนำเข้าไทม์ไลน์จากโปรแกรมตัดต่อจะกลับมาเมื่อพร้อม")}
        </p>
        <div className="row" style={{ gap: 10 }}>
          <Link href="/" className="btn primary">{tx("งานใหม่")}</Link>
          <Link href="/promotions" className="btn">{tx("ดูแพ็กเกจ")}</Link>
        </div>
      </div>
    </main>
  );
}
