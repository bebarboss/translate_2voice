import type { MetadataRoute } from "next";
import { PUBLIC_PAGES, siteUrl } from "@/lib/site";

/** /sitemap.xml: เฉพาะหน้าที่เปิดได้โดยไม่ต้องล็อกอิน */
export default function sitemap(): MetadataRoute.Sitemap {
  const base = siteUrl();
  return PUBLIC_PAGES.map((path) => ({
    url: `${base}${path}`,
    changeFrequency: path === "/welcome" ? "weekly" : "yearly",
    priority: path === "/welcome" ? 1 : 0.3,
  }));
}
