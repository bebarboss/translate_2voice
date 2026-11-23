import type { MetadataRoute } from "next";
import { siteUrl } from "@/lib/site";

/** /robots.txt: เปิดเฉพาะหน้าสาธารณะ ไม่ให้บอทเดินเข้า API หรือหน้าแชร์ผลงานของผู้ใช้ */
export default function robots(): MetadataRoute.Robots {
  const base = siteUrl();
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/api/", "/share/", "/unsubscribe"] },
    sitemap: `${base}/sitemap.xml`,
  };
}
