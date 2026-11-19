import type { Metadata } from "next";
import UnsubscribePanel from "./panel";

export const metadata: Metadata = {
  title: "ปิดการรับอีเมล",
  robots: "noindex, nofollow",
  referrer: "no-referrer",
};

/** หน้าสาธารณะ โทเคนอยู่ใน query ของเบราว์เซอร์และถูกส่งเมื่อกดยืนยันเท่านั้น */
export default function UnsubscribePage() {
  return <UnsubscribePanel />;
}
