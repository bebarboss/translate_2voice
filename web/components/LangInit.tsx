"use client";

import { setCurrentLang, type Lang } from "@/lib/i18n";

/** ตั้งภาษาก่อนเรนเดอร์ส่วนอื่นของหน้า (วางเป็นลูกตัวแรกของ body) ฝั่งเบราว์เซอร์อ่านจาก <html lang> อยู่แล้ว */
export default function LangInit({ lang }: { lang: Lang }) {
  setCurrentLang(lang);
  return null;
}
