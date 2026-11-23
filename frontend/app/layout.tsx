import type { Metadata } from "next";
import { cookies } from "next/headers";
import "@fontsource/anuphan/400.css";
import "@fontsource/anuphan/500.css";
import "@fontsource/anuphan/600.css";
import "@fontsource/anuphan/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "./globals.css";
import CursorGlow from "@/components/CursorGlow";
import LangInit from "@/components/LangInit";
import ProfileGate from "@/components/ProfileGate";
import Sidebar from "@/components/Sidebar";
import { isLang, isTheme, LANG_COOKIE, THEME_COOKIE } from "@/lib/i18n";
import { siteUrl } from "@/lib/site";
import { AuthProvider } from "@/lib/useAuth";

const SHARE_TITLE = "พากย์ดี (Pakdee) · AI พากย์ไทย";
const SHARE_DESCRIPTION = "แยกตัวละคร แปล และพากย์คลิปต่างประเทศเป็นเสียงไทย ด้วยเสียงนักแสดงต้นฉบับหรือเสียงพากย์จากคลัง";
// รูปแชร์ 1200x630 ต้นฉบับอยู่ที่ scripts/og-image.html
const SHARE_IMAGE = { url: "/brand/og.png", width: 1200, height: 630, alt: "นกแก้วพากย์ดี · พากย์ดีด้วย AI" };

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl()),
  title: "Pakdee",
  description: "พากย์ดี · AI พากย์ไทย — พากย์คลิปต่างประเทศเป็นไทยหรืออังกฤษ ด้วยเสียงนักแสดงต้นฉบับ",
  openGraph: {
    type: "website",
    siteName: "Pakdee",
    locale: "th_TH",
    title: SHARE_TITLE,
    description: SHARE_DESCRIPTION,
    images: [SHARE_IMAGE],
  },
  twitter: {
    card: "summary_large_image",
    title: SHARE_TITLE,
    description: SHARE_DESCRIPTION,
    images: [SHARE_IMAGE],
  },
  icons: {
    icon: [
      { url: "/brand/icon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon.ico" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const jar = await cookies();
  const lang = jar.get(LANG_COOKIE)?.value;
  const theme = jar.get(THEME_COOKIE)?.value;
  return (
    <html lang={isLang(lang) ? lang : "th"} data-theme={isTheme(theme) && theme !== "system" ? theme : undefined}>
      <body>
        <LangInit lang={isLang(lang) ? lang : "th"} />
        <CursorGlow />
        <AuthProvider>
          <div className="shell">
            <ProfileGate />
            <Sidebar />
            <div className="shell-main">
              {children}
            </div>
          </div>
        </AuthProvider>
      </body>
    </html>
  );
}
