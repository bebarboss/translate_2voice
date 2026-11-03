"use client";

import { useState } from "react";
import { VOICE_CATEGORIES } from "@/lib/format";

import { tx } from "@/lib/i18n";
/** เลือกหมวดหมู่ได้หลายหมวด: หมวดตั้งต้น หมวดที่ใช้อยู่ในคลัง และพิมพ์หมวดใหม่เองได้ */
export default function CategoryPicker({ value, onChange, known, id }: {
  value: string[];
  onChange: (v: string[]) => void;
  known: string[];
  id: string;
}) {
  const [custom, setCustom] = useState("");
  const options = [...new Set([...VOICE_CATEGORIES, ...known, ...value])];
  const toggle = (c: string) => onChange(value.includes(c) ? value.filter((x) => x !== c) : [...value, c]);
  const addCustom = () => {
    const c = custom.trim().replace(/\s+/g, " ").slice(0, 30);
    if (c && !value.includes(c) && value.length < 10) onChange([...value, c]);
    setCustom("");
  };
  return (
    <div className="chips" role="group" aria-labelledby={id}>
      {options.map((c) => (
        <button key={c} type="button" className="chip" aria-pressed={value.includes(c)} onClick={() => toggle(c)}>{tx(c)}</button>
      ))}
      <input className="chip-input" maxLength={30} placeholder={tx("+ หมวดใหม่")} aria-label={tx("เพิ่มหมวดหมู่ใหม่")} value={custom}
        onChange={(e) => setCustom(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCustom(); } }}
        onBlur={addCustom} />
    </div>
  );
}
