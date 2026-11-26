/** ตรรกะล้วนของการแก้บนเส้นเวลา (ไม่ผูกกับ React) แยกไว้เพื่อทดสอบ */

/** ปัดเวลา sec เข้าหาจุดใกล้สุดใน points ถ้าห่างไม่เกิน threshold (วินาที) */
export function snapSec(sec: number, points: number[], threshold: number): { sec: number; hit: number | null } {
  let best: number | null = null;
  for (const p of points) if (Math.abs(p - sec) <= threshold && (best === null || Math.abs(p - sec) < Math.abs(best - sec))) best = p;
  return best === null ? { sec, hit: null } : { sec: best, hit: best };
}

/** ปัดบล็อกที่เลื่อน (เริ่ม start ยาว len) ให้ขอบหัวหรือขอบท้ายชนจุดใกล้สุด คืนเวลาเริ่มใหม่ */
export function snapMove(start: number, len: number, points: number[], threshold: number): { start: number; hit: number | null } {
  const a = snapSec(start, points, threshold);
  const b = snapSec(start + len, points, threshold);
  if (a.hit === null && b.hit === null) return { start, hit: null };
  if (a.hit !== null && (b.hit === null || Math.abs(a.hit - start) <= Math.abs(b.hit - (start + len)))) return { start: a.hit, hit: a.hit };
  return { start: b.hit! - len, hit: b.hit };
}

/** ประวัติย้อนกลับ/ทำซ้ำ ของสแนปช็อต: การแก้ถี่ ๆ ที่คีย์เดียวกันภายใน window มิลลิวินาที (ลากเมาส์ พิมพ์ต่อเนื่อง) รวมเป็นหนึ่งขั้น */
export class History<T> {
  private past: T[] = [];
  private future: T[] = [];
  private lastKey: string | null = null;
  private lastAt = -Infinity;
  private limit: number;
  private window: number;
  constructor(limit = 100, window = 700) { this.limit = limit; this.window = window; }

  /** เรียกก่อนแก้: before = สถานะก่อนแก้ */
  record(before: T, key: string, now: number) {
    const merge = this.lastKey === key && now - this.lastAt < this.window && this.past.length > 0;
    this.lastAt = now;
    this.lastKey = key;
    if (merge) return;
    this.past.push(before);
    if (this.past.length > this.limit) this.past.shift();
    this.future = [];
  }
  undo(current: T): T | null {
    const prev = this.past.pop();
    if (prev === undefined) return null;
    this.future.push(current);
    this.lastKey = null;
    return prev;
  }
  redo(current: T): T | null {
    const next = this.future.pop();
    if (next === undefined) return null;
    this.past.push(current);
    this.lastKey = null;
    return next;
  }
  clear() { this.past = []; this.future = []; this.lastKey = null; }
  get canUndo() { return this.past.length > 0; }
  get canRedo() { return this.future.length > 0; }
}
