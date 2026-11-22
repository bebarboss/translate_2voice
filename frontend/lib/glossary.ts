// glossary ของโปรเจกต์: เก็บเป็นข้อความบรรทัดละคำ "ต้นฉบับ = คำที่ต้องใช้ # หมายเหตุ" (รูปแบบเดียวกับฝั่งเซิร์ฟเวอร์
// translate_quality.parse_glossary) หน้าเว็บแก้เป็นรายการ แล้วแปลงกลับเป็นข้อความก่อนบันทึก

export interface GlossaryTerm {
  source: string;
  target: string;
  note: string;
}

const NOTE = /\s+#(?:\s(.*))?$/;

/** ข้อความ → รายการ บรรทัดที่ไม่มี "=" หรือว่างข้างใดข้างหนึ่ง เก็บไว้เป็นแถวที่ยังไม่ครบ (ไม่ทิ้งของที่ผู้ใช้พิมพ์) */
export function parseGlossary(text: string): GlossaryTerm[] {
  const out: GlossaryTerm[] = [];
  for (const raw of (text || "").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const eq = line.indexOf("=");
    if (eq < 0) {
      out.push({ source: line, target: "", note: "" });
      continue;
    }
    const rest = line.slice(eq + 1);
    const m = rest.match(NOTE);
    out.push({
      source: line.slice(0, eq).trim(),
      target: (m ? rest.slice(0, m.index) : rest).trim(),
      note: (m?.[1] ?? "").trim(),
    });
  }
  return out;
}

/** รายการ → ข้อความ ตัดแถวว่าง ช่องว่าง/ขึ้นบรรทัดในช่องเดียวกันรวมเป็นช่องว่างเดียว */
export function serializeGlossary(terms: GlossaryTerm[]): string {
  const clean = (s: string) => s.replace(/\s+/g, " ").trim();
  return terms
    .map((t) => ({ source: clean(t.source).replace(/=/g, ""), target: clean(t.target).replace(/\s#(\s|$)/g, " "), note: clean(t.note) }))
    .filter((t) => t.source || t.target)
    .map((t) => `${t.source} = ${t.target}${t.note ? ` # ${t.note}` : ""}`)
    .join("\n");
}
