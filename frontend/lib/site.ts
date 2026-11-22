// ที่อยู่สาธารณะของเว็บ ใช้กับ metadataBase (og:image / canonical), robots.txt และ sitemap.xml
// ตั้ง SITE_URL (หรือ WEB_URL ชื่อเดียวกับฝั่ง API) ได้ ไม่ตั้ง = โดเมนจริง
const DEFAULT_SITE_URL = "https://pakdee-app.cobie.online";

export function siteUrl(): string {
  // Bracket access so `next build` does not bake the value into the image.
  const raw = (process.env["SITE_URL"] || process.env["WEB_URL"] || DEFAULT_SITE_URL).trim();
  try {
    return new URL(raw).origin;
  } catch {
    return DEFAULT_SITE_URL;
  }
}

/** หน้าสาธารณะที่ให้บอทเก็บ (ที่เหลือต้องล็อกอิน) */
export const PUBLIC_PAGES = ["/welcome", "/privacy", "/terms"] as const;
