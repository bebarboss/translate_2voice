"use client";

import { useEffect, useState } from "react";
import { chooseLang, chooseTheme, currentTheme, getLang, tx, type Lang, type Theme } from "@/lib/i18n";

const LANGS: [Lang, string][] = [["th", "ไทย"], ["en", "English"]];
const THEMES: [Theme, string][] = [["system", "อัตโนมัติ"], ["dark", "มืด"], ["light", "สว่าง"]];

/** เลือกภาษาและธีมของหน้าเว็บ (ท้ายเมนูซ้าย และหน้าที่ไม่มีเมนู) */
export default function Prefs({ compact = false }: { compact?: boolean }) {
  const [theme, setTheme] = useState<Theme>("system");
  useEffect(() => setTheme(currentTheme()), []);
  const lang = getLang();
  const pick = (th: Theme) => { chooseTheme(th); setTheme(th); };
  return (
    <div className={`prefs${compact ? " compact" : ""}`}>
      {!compact && <span className="prefs-label">{tx("ภาษา")}</span>}
      <div className="seg" role="group" aria-label={tx("ภาษา")}>
        {LANGS.map(([k, label]) => (
          <button key={k} type="button" lang={k} aria-pressed={lang === k} onClick={() => chooseLang(k)}>{label}</button>
        ))}
      </div>
      {!compact && <span className="prefs-label">{tx("ธีม")}</span>}
      <div className="seg" role="group" aria-label={tx("ธีม")}>
        {THEMES.map(([k, label]) => (
          <button key={k} type="button" aria-pressed={theme === k} onClick={() => pick(k)}>{tx(label)}</button>
        ))}
      </div>
    </div>
  );
}
