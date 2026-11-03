import type { Metadata } from "next";
import { cookies } from "next/headers";
import "@fontsource/ibm-plex-sans-thai/400.css";
import "@fontsource/ibm-plex-sans-thai/500.css";
import "@fontsource/ibm-plex-sans-thai/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./globals.css";
import LangInit from "@/components/LangInit";
import ProfileGate from "@/components/ProfileGate";
import Sidebar from "@/components/Sidebar";
import { isLang, isTheme, LANG_COOKIE, THEME_COOKIE } from "@/lib/i18n";

export const metadata: Metadata = {
  title: "Dubbing Studio",
  description: "พากย์คลิปต่างประเทศเป็นไทยหรืออังกฤษ ด้วยเสียงนักแสดงต้นฉบับ",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const jar = await cookies();
  const lang = jar.get(LANG_COOKIE)?.value;
  const theme = jar.get(THEME_COOKIE)?.value;
  return (
    <html lang={isLang(lang) ? lang : "th"} data-theme={isTheme(theme) && theme !== "system" ? theme : undefined}>
      <body>
        <LangInit lang={isLang(lang) ? lang : "th"} />
        <div className="shell">
          <ProfileGate />
          <Sidebar />
          <div className="shell-main">
            {children}
          </div>
        </div>
      </body>
    </html>
  );
}
