"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { BrandLink } from "@/components/Brand";
import { api, fileUrl, type ShareInfo } from "@/lib/api";
import { TARGET_LABEL, fmtDuration } from "@/lib/format";
import { tx } from "@/lib/i18n";

/** หน้าสาธารณะเล่นคลิปจากลิงก์แชร์ (คลิปฟรีมีลายน้ำนกแก้ว) */
export default function SharePage() {
  const params = useParams<{ token: string }>();
  const token = params?.token ?? "";
  const [info, setInfo] = useState<ShareInfo | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    api.getShare(token)
      .then((r) => { if (!cancelled) setInfo(r); })
      .catch((e) => { if (!cancelled) setError((e as Error).message || tx("ไม่พบลิงก์นี้")); });
    return () => { cancelled = true; };
  }, [token]);

  return (
    <main className="page" style={{ maxWidth: 880, gap: 20, paddingTop: 28 }}>
      <div className="row" style={{ justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <BrandLink />
        <Link href="/" className="btn small">{tx("ลองพากย์คลิปของคุณ")}</Link>
      </div>

      {error && <div className="alert error" role="alert">{error}</div>}
      {!error && !info && <div className="empty">{tx("กำลังโหลด...")}</div>}

      {info && (
        <section className="card" style={{ gap: 14, padding: 0, overflow: "hidden" }}>
          <video
            controls
            playsInline
            preload="metadata"
            style={{ width: "100%", display: "block", background: "#0b0f14", aspectRatio: "16 / 9" }}
            src={fileUrl.shareVideo(info.token)}
          />
          <div style={{ padding: "4px 18px 18px", display: "flex", flexDirection: "column", gap: 8 }}>
            <h1 style={{ margin: 0, fontSize: 20, lineHeight: 1.35 }}>{info.filename}</h1>
            <span className="dim">
              {tx(TARGET_LABEL[info.target_lang] || info.target_lang)}
              {info.duration ? ` · ${fmtDuration(info.duration)}` : ""}
              {info.watermark ? ` · ${tx("มีลายน้ำ")}` : ""}
            </span>
            {info.watermark && (
              <div className="alert info">{tx("คลิปแพ็กฟรีมีลายน้ำนกแก้ว · อัปเกรดเพื่อเอาลายน้ำออก")}</div>
            )}
            {info.expires_at && (
              <div className="alert warn">
                {tx("ไฟล์นี้อาจถูกลบหลัง {0}", { 0: new Date(info.expires_at).toLocaleString() })}
              </div>
            )}
          </div>
        </section>
      )}
    </main>
  );
}
