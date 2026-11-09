"use client";

import type { Fonts, SubtitleStyle, TargetLang } from "@/lib/api";

import { tx } from "@/lib/i18n";
export const SAMPLE_TEXT: Record<TargetLang, string> = {
  th: "ข้าสัญญาไว้แล้ว ยังไงก็ต้องมา",
  en: "I promised you, so I came.",
};

/** ฟอนต์ที่เลือกได้ งานไทยต้องใช้ฟอนต์ไทย (มีตัวอังกฤษในตัว) งานอังกฤษใช้ได้ทุกฟอนต์ */
export function fontOptions(fonts: Fonts | null, lang: TargetLang, current: string): { group: string; names: string[] }[] {
  const thai = fonts?.thai ?? [];
  const english = fonts?.english ?? [];
  const groups = lang === "th"
    ? [{ group: tx("ฟอนต์ไทย"), names: thai }]
    : [{ group: tx("ฟอนต์อังกฤษ"), names: english }, { group: tx("ฟอนต์ไทย"), names: thai }];
  if (current && !groups.some((g) => g.names.includes(current))) {
    groups.unshift({ group: tx("ที่ตั้งไว้ (ไม่พบในเครื่องเซิร์ฟเวอร์)"), names: [current] });
  }
  return groups;
}

export function SubtitlePreview({ style, lang, height = 140 }: { style: SubtitleStyle; lang: TargetLang; height?: number }) {
  const px = Math.max(10, Math.round(style.size * (height / 1080) * 2.2));
  const o = Math.max(1, Math.round(px / 12));
  const shadow = [-o, 0, o].flatMap((x) => [-o, 0, o].map((y) => `${x}px ${y}px 0 ${style.outline_color}`)).join(",");
  return (
    <div className="sub-preview" style={{ height, alignItems: style.position === "top" ? "flex-start" : "flex-end" }} aria-hidden="true">
      <span style={{ fontFamily: `"${style.font}", var(--font)`, fontSize: px, color: style.color, textShadow: shadow }}>
        {SAMPLE_TEXT[lang]}
      </span>
    </div>
  );
}

export default function SubtitleStylePanel({ style, lang, fonts, onChange, idPrefix = "sub" }: {
  style: SubtitleStyle;
  lang: TargetLang;
  fonts: Fonts | null;
  onChange: (patch: Partial<SubtitleStyle>) => void;
  idPrefix?: string;
}) {
  const groups = fontOptions(fonts, lang, style.font);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <SubtitlePreview style={style} lang={lang} />
      <div className="field">
        <label htmlFor={`${idPrefix}-font`}>{tx("ฟอนต์")}</label>
        <select id={`${idPrefix}-font`} className="select" value={style.font} onChange={(e) => onChange({ font: e.target.value })}>
          {groups.map((g) => (
            <optgroup key={g.group} label={g.group}>
              {g.names.map((n) => <option key={n} value={n}>{n}</option>)}
            </optgroup>
          ))}
        </select>
      </div>
      <div className="row" style={{ gap: 18 }}>
        <label className="row" style={{ gap: 8 }}>
          <input type="color" value={style.color} onChange={(e) => onChange({ color: e.target.value.toUpperCase() })} />
          <span className="label">{tx("สีตัวอักษร")}</span>
        </label>
        <label className="row" style={{ gap: 8 }}>
          <input type="color" value={style.outline_color} onChange={(e) => onChange({ outline_color: e.target.value.toUpperCase() })} />
          <span className="label">{tx("สีขอบ")}</span>
        </label>
      </div>
      <div className="field">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <label htmlFor={`${idPrefix}-size`}>{tx("ขนาด")}</label>
          <span className="mono">{style.size}</span>
        </div>
        <input id={`${idPrefix}-size`} type="range" min={16} max={120} step={2} value={style.size}
          onChange={(e) => onChange({ size: Number(e.target.value) })} />
        <span className="dim">{tx("อ้างอิงวิดีโอสูง 1080 px")}</span>
      </div>
      <div className="field">
        <span className="label">{tx("ตำแหน่ง")}</span>
        <div className="seg" role="group" aria-label={tx("ตำแหน่งซับ")} style={{ alignSelf: "flex-start" }}>
          <button type="button" aria-pressed={style.position === "bottom"} onClick={() => onChange({ position: "bottom" })}>{tx("ด้านล่าง")}</button>
          <button type="button" aria-pressed={style.position === "top"} onClick={() => onChange({ position: "top" })}>{tx("ด้านบน")}</button>
        </div>
      </div>
    </div>
  );
}
