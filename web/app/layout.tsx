import type { Metadata } from "next";
import "@fontsource/ibm-plex-sans-thai/400.css";
import "@fontsource/ibm-plex-sans-thai/500.css";
import "@fontsource/ibm-plex-sans-thai/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./globals.css";
import AccountBar from "@/components/AccountBar";
import ProfileGate from "@/components/ProfileGate";
import Sidebar from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Dubbing Studio",
  description: "พากย์คลิปต่างประเทศเป็นไทยหรืออังกฤษ ด้วยเสียงนักแสดงต้นฉบับ",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="th">
      <body>
        <div className="shell">
          <ProfileGate />
          <Sidebar />
          <div className="shell-main">
            <AccountBar />
            {children}
          </div>
        </div>
      </body>
    </html>
  );
}
