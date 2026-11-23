"use client";

import { useState } from "react";
import { PlusIcon, TrashIcon } from "./Icons";
import { parseGlossary, serializeGlossary, type GlossaryTerm } from "@/lib/glossary";
import { tx } from "@/lib/i18n";

/** แก้ glossary เป็นรายการ: ต้นฉบับ → คำที่ต้องใช้ (ไทยหรือละติน) + หมายเหตุ ผู้แปลและตัวตรวจชื่อใช้ทุกตอนของโปรเจกต์ */
export default function GlossaryEditor({ value, onChange, id }: {
  value: string;
  onChange: (text: string) => void;
  id: string;
}) {
  // เก็บแถวที่ยังพิมพ์ไม่ครบไว้ในหน้า (ข้อความที่ส่งออกตัดแถวว่างทิ้ง)
  const [rows, setRows] = useState<GlossaryTerm[]>(() => parseGlossary(value));
  const [seen, setSeen] = useState(value);
  if (value !== seen && value !== serializeGlossary(rows)) {
    setSeen(value);
    setRows(parseGlossary(value));
  }
  const update = (next: GlossaryTerm[]) => {
    setRows(next);
    const text = serializeGlossary(next);
    setSeen(text);
    onChange(text);
  };
  const set = (i: number, patch: Partial<GlossaryTerm>) => update(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  return (
    <div className="gloss" id={id}>
      {rows.length > 0 && (
        <div className="gloss-row gloss-head" aria-hidden="true">
          <span>{tx("ต้นฉบับ")}</span><span>{tx("ต้องเขียนว่า")}</span><span>{tx("หมายเหตุ")}</span><span />
        </div>
      )}
      {rows.map((r, i) => (
        <div className="gloss-row" key={i}>
          <input className="input" value={r.source} maxLength={80} placeholder="DE Practice"
            aria-label={tx("ต้นฉบับ แถวที่ {0}", { 0: i + 1 })} onChange={(e) => set(i, { source: e.target.value })} />
          <input className="input" value={r.target} maxLength={80} placeholder={tx("DE Practice หรือ ดีอี แพรคทิส")}
            aria-label={tx("คำที่ต้องใช้ แถวที่ {0}", { 0: i + 1 })} onChange={(e) => set(i, { target: e.target.value })} />
          <input className="input" value={r.note} maxLength={120} placeholder={tx("เช่น ชื่อแอป คงอักษรละติน")}
            aria-label={tx("หมายเหตุ แถวที่ {0}", { 0: i + 1 })} onChange={(e) => set(i, { note: e.target.value })} />
          <button type="button" className="icon-only" aria-label={tx("ลบแถวที่ {0}", { 0: i + 1 })}
            onClick={() => update(rows.filter((_, j) => j !== i))}><TrashIcon /></button>
        </div>
      ))}
      <button type="button" className="btn small" style={{ alignSelf: "flex-start" }}
        onClick={() => setRows([...rows, { source: "", target: "", note: "" }])}><PlusIcon />{tx("เพิ่มคำ")}</button>
    </div>
  );
}
