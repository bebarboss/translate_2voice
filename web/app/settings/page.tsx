"use client";

import { useEffect, useState } from "react";
import { api, type Fonts, type RuntimeSettings, type SubtitleStyle, type TargetLang } from "@/lib/api";
import { TARGET_LABEL } from "@/lib/format";
import { SubtitlePreview, fontOptions } from "@/components/SubtitleStylePanel";

import { tx } from "@/lib/i18n";
const QUALITY = [
  { steps: 16, label: "เร็ว (16 steps)" },
  { steps: 32, label: "มาตรฐาน (32 steps)" },
  { steps: 48, label: "ดี (48 steps)" },
  { steps: 64, label: "ละเอียด (64 steps)" },
];

export default function SettingsPage() {
  const [saved, setSaved] = useState<RuntimeSettings | null>(null);
  const [form, setForm] = useState<RuntimeSettings | null>(null);
  const [fonts, setFonts] = useState<Fonts | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [previewLang, setPreviewLang] = useState<TargetLang>("th");

  useEffect(() => {
    api.getSettings().then((s) => { setSaved(s); setForm(s); }).catch((e) => setMessage({ kind: "error", text: e.message }));
    api.fonts().then(setFonts).catch(() => setFonts({ thai: [], english: [] }));
  }, []);

  const set = <K extends keyof RuntimeSettings>(key: K, value: RuntimeSettings[K]) =>
    setForm((f) => (f ? { ...f, [key]: value } : f));

  const changed = form && saved
    ? (Object.keys(form) as (keyof RuntimeSettings)[]).filter((k) => form[k] !== saved[k])
    : [];
  const redubAll = changed.some((k) => k === "max_speedup" || k === "f5_steps");

  const save = async () => {
    if (!form || !changed.length) return;
    setBusy(true);
    setMessage(null);
    try {
      const patch = Object.fromEntries(changed.map((k) => [k, form[k]])) as Partial<RuntimeSettings>;
      const s = await api.saveSettings(patch);
      setSaved(s);
      setForm(s);
      setMessage({ kind: "info", text: tx("บันทึกการตั้งค่าแล้ว มีผลกับงานที่พากย์รอบถัดไป") });
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const previewStyle: SubtitleStyle | null = form && {
    font: previewLang === "en" ? form.sub_font_en : form.sub_font_th,
    color: form.sub_color,
    outline_color: form.sub_outline_color,
    size: form.sub_size,
    position: form.sub_position,
  };

  return (
    <main className="page" style={{ maxWidth: 1100 }}>
      <div className="page-head">
        <h1>{tx("ตั้งค่า")}</h1>
        <button type="button" className="btn primary" onClick={save} disabled={busy || !changed.length}>
          {busy ? tx("กำลังบันทึก...") : tx("บันทึกการตั้งค่า{0}", { 0: changed.length ? ` (${changed.length})` : "" })}
        </button>
      </div>

      {message && <div className={`alert ${message.kind}`} role="alert">{message.text}</div>}
      {redubAll && <div className="alert info">{tx("เปลี่ยนความเร็วหรือคุณภาพเสียงแล้ว งานที่สั่งพากย์ใหม่ครั้งถัดไปจะพากย์ใหม่ทุกประโยค")}</div>}

      <div className="grid-2">
        {form && (
          <>
            <section className="card" aria-labelledby="def">
              <h2 id="def">{tx("ค่าเริ่มต้นตอนส่งงาน")}</h2>
              <div className="field">
                <span className="label">{tx("ภาษาพากย์")}</span>
                <div className="seg" role="group" aria-label={tx("ภาษาพากย์เริ่มต้น")} style={{ alignSelf: "flex-start" }}>
                  {(["th", "en"] as TargetLang[]).map((t) => (
                    <button key={t} type="button" aria-pressed={form.default_target_lang === t} onClick={() => set("default_target_lang", t)}>
                      {tx(TARGET_LABEL[t])}
                    </button>
                  ))}
                </div>
              </div>
              <label className="check">
                <span className="t"><span>{tx("ตรวจบทก่อนพากย์")}</span><small>{tx("หยุดรอให้แก้บทหลังแปลเสร็จ")}</small></span>
                <input type="checkbox" checked={form.default_review} onChange={(e) => set("default_review", e.target.checked)} />
              </label>
              <label className="check">
                <span className="t"><span>{tx("ฝังซับในวิดีโอ")}</span><small>{tx("เปลี่ยนได้อีกครั้งตอนดาวน์โหลด")}</small></span>
                <input type="checkbox" checked={form.default_burn_subs} onChange={(e) => set("default_burn_subs", e.target.checked)} />
              </label>
            </section>

            <section className="card" aria-labelledby="voice">
              <h2 id="voice">{tx("เสียงพากย์")}</h2>
              <div className="field">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <label htmlFor="speed">{tx("เร่งเสียงได้สูงสุด")}</label><span className="mono">{form.max_speedup.toFixed(2)}×</span>
                </div>
                <input id="speed" type="range" min={1} max={2} step={0.05} value={form.max_speedup}
                  onChange={(e) => set("max_speedup", Number(e.target.value))} />
                <span className="dim">{tx("บทที่ยาวเกินฉากจะถูกเร่งได้ไม่เกินค่านี้ ที่เหลือระบบจะย่อบทให้")}</span>
              </div>
              <div className="field">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <label htmlFor="vg">{tx("ความดังเสียงพากย์")}</label><span className="mono">{Math.round(form.voice_gain * 100)}%</span>
                </div>
                <input id="vg" type="range" min={0} max={2} step={0.05} value={form.voice_gain}
                  onChange={(e) => set("voice_gain", Number(e.target.value))} />
              </div>
              <div className="field">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <label htmlFor="bg">{tx("ความดังเพลงประกอบ")}</label><span className="mono">{Math.round(form.bgm_gain * 100)}%</span>
                </div>
                <input id="bg" type="range" min={0} max={2} step={0.05} value={form.bgm_gain}
                  onChange={(e) => set("bgm_gain", Number(e.target.value))} />
              </div>
              <div className="field">
                <label htmlFor="q">{tx("คุณภาพเสียง")}</label>
                <select id="q" className="select" value={form.f5_steps} onChange={(e) => set("f5_steps", Number(e.target.value))}>
                  {QUALITY.some((q) => q.steps === form.f5_steps) ? null : <option value={form.f5_steps}>{form.f5_steps} steps</option>}
                  {QUALITY.map((q) => <option key={q.steps} value={q.steps}>{tx(q.label)}</option>)}
                </select>
                <span className="dim">{tx("ยิ่งละเอียดยิ่งช้า การ์ดจอเล็กแนะนำ 16")}</span>
              </div>
            </section>

            <section className="card" aria-labelledby="subs" style={{ gridColumn: "1 / -1" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h2 id="subs">{tx("ซับไตเติลเริ่มต้น")}</h2>
                <div className="seg" role="group" aria-label={tx("ดูตัวอย่างภาษา")}>
                  {(["th", "en"] as TargetLang[]).map((t) => (
                    <button key={t} type="button" aria-pressed={previewLang === t} onClick={() => setPreviewLang(t)}>{tx("ตัวอย่าง")}{tx(TARGET_LABEL[t])}</button>
                  ))}
                </div>
              </div>
              <div className="grid-2">
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <div className="field">
                    <label htmlFor="fth">{tx("ฟอนต์งานไทย")}</label>
                    <select id="fth" className="select" value={form.sub_font_th} onChange={(e) => set("sub_font_th", e.target.value)}>
                      {fontOptions(fonts, "th", form.sub_font_th).map((g) => (
                        <optgroup key={g.group} label={g.group}>{g.names.map((n) => <option key={n} value={n}>{n}</option>)}</optgroup>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="fen">{tx("ฟอนต์งานอังกฤษ")}</label>
                    <select id="fen" className="select" value={form.sub_font_en} onChange={(e) => set("sub_font_en", e.target.value)}>
                      {fontOptions(fonts, "en", form.sub_font_en).map((g) => (
                        <optgroup key={g.group} label={g.group}>{g.names.map((n) => <option key={n} value={n}>{n}</option>)}</optgroup>
                      ))}
                    </select>
                  </div>
                  <div className="row" style={{ gap: 18 }}>
                    <label className="row" style={{ gap: 8 }}>
                      <input type="color" value={form.sub_color} onChange={(e) => set("sub_color", e.target.value.toUpperCase())} />
                      <span className="label">{tx("สีตัวอักษร")}</span>
                    </label>
                    <label className="row" style={{ gap: 8 }}>
                      <input type="color" value={form.sub_outline_color} onChange={(e) => set("sub_outline_color", e.target.value.toUpperCase())} />
                      <span className="label">{tx("สีขอบ")}</span>
                    </label>
                  </div>
                  <div className="field">
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <label htmlFor="ss">{tx("ขนาด")}</label><span className="mono">{form.sub_size}</span>
                    </div>
                    <input id="ss" type="range" min={16} max={120} step={2} value={form.sub_size}
                      onChange={(e) => set("sub_size", Number(e.target.value))} />
                  </div>
                  <div className="field">
                    <span className="label">{tx("ตำแหน่ง")}</span>
                    <div className="seg" role="group" aria-label={tx("ตำแหน่งซับเริ่มต้น")} style={{ alignSelf: "flex-start" }}>
                      <button type="button" aria-pressed={form.sub_position === "bottom"} onClick={() => set("sub_position", "bottom")}>{tx("ด้านล่าง")}</button>
                      <button type="button" aria-pressed={form.sub_position === "top"} onClick={() => set("sub_position", "top")}>{tx("ด้านบน")}</button>
                    </div>
                  </div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {previewStyle && <SubtitlePreview style={previewStyle} lang={previewLang} height={220} />}
                  <span className="dim">
                    
                    {tx("รายชื่อฟอนต์มาจากเครื่องที่รัน API ถ้าอยากใช้ฟอนต์อื่น เช่น Sarabun หรือ Kanit ต้องติดตั้งลงเครื่องนั้นก่อน ภาพตัวอย่างใช้ฟอนต์ในเครื่องของคุณ จึงอาจต่างจากวิดีโอจริงเล็กน้อย")}
                  </span>
                </div>
              </div>
            </section>
          </>
        )}
      </div>
    </main>
  );
}
