/** Thai digits U+0E50..U+0E59 and fullwidth digits U+FF10..U+FF19.
 *  Built from codepoints so a lookalike cannot be pasted in (Thai 8 is U+0E58, fullwidth 8 is U+FF18). */
const THAI_DIGITS = Array.from({ length: 10 }, (_, i) => String.fromCharCode(0x0e50 + i)).join("");
const FULLWIDTH_DIGITS = Array.from({ length: 10 }, (_, i) => String.fromCharCode(0xff10 + i)).join("");

/** แปลงเลขไทยและเลขเต็มความกว้างเป็น 0-9 แล้วตัดช่องว่างกับขีด
 *  เซิร์ฟเวอร์ไม่แปลงเลขยูนิโค้ด จึงต้องทำก่อนส่ง */
export function normalizePaymentDigits(raw: string): string {
  let out = "";
  for (const ch of raw) {
    const thai = THAI_DIGITS.indexOf(ch);
    if (thai >= 0) {
      out += String(thai);
      continue;
    }
    const wide = FULLWIDTH_DIGITS.indexOf(ch);
    if (wide >= 0) {
      out += String(wide);
      continue;
    }
    if (/\s/u.test(ch) || ch === "-") continue;
    out += ch;
  }
  return out;
}

/** ว่างเมื่อถูก ไม่งั้นเป็นข้อความไทยสำหรับแสดงใต้ช่อง */
export function taxIdError(value: string): string {
  if (!/^[0-9]{13}$/.test(value)) return "เลขประจำตัวผู้เสียภาษีต้องมี 13 หลัก";
  let sum = 0;
  for (let i = 0; i < 12; i++) sum += Number(value[i]) * (13 - i);
  if ((11 - (sum % 11)) % 10 !== Number(value[12])) return "เลขประจำตัวผู้เสียภาษีไม่ถูกต้อง";
  return "";
}

export function accountNoError(value: string): string {
  if (!/^[0-9]{10,15}$/.test(value)) return "เลขบัญชีต้องเป็นตัวเลข 10–15 หลัก";
  return "";
}
