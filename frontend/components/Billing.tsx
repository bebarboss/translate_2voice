"use client";

// ชิ้นส่วนที่หน้าโปรไฟล์ (/account) หน้าแพ็กเกจและโปรโมชัน (/promotions) และหน้าผู้ดูแล (/admin) ใช้ร่วมกัน
import { useEffect, useState } from "react";
import { api, type Cards, type PaymentOrder, type Plan, type Wallet } from "@/lib/api";
import { fmtBaht, fmtNum } from "@/lib/format";
import { locale, tx } from "@/lib/i18n";

export type Message = { kind: "error" | "info"; text: string } | null;

export const fmtDate = (unix: number) =>
  new Date(unix * 1000).toLocaleDateString(locale(), { day: "numeric", month: "short", year: "numeric" });
export const fmtCredits = (n: number) => tx("{0} เครดิต", { 0: fmtNum(n) });

export const Alert = ({ m }: { m: Message }) =>
  m && <div className={`alert ${m.kind}`} role={m.kind === "error" ? "alert" : "status"}>{m.text}</div>;

export function useRunner(load: () => void) {
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState<Message>(null);
  /** done: ข้อความเมื่อสำเร็จ หรือฟังก์ชันสร้างข้อความจากผลลัพธ์
   *  onError คืนข้อความที่เป็นมิตร (แสดงเป็น info) เมื่อไม่ต้องการกล่อง error ทั่วไป */
  const run = async <T,>(
    key: string,
    fn: () => Promise<T>,
    done: string | ((r: T) => string),
    onError?: (e: unknown) => string | null,
  ) => {
    setBusy(key);
    setMessage(null);
    try {
      const r = await fn();
      load();
      setMessage({ kind: "info", text: typeof done === "string" ? done : done(r) });
    } catch (e) {
      const friendly = onError?.(e);
      if (friendly) {
        load();
        setMessage({ kind: "info", text: friendly });
      } else {
        setMessage({ kind: "error", text: (e as Error).message });
      }
    } finally { setBusy(""); }
  };
  return { busy, message, setMessage, run };
}

/** ยอดเครดิตและแพ็กเกจของผู้ใช้ โหลดใหม่ได้ด้วย reload() */
export function useWallet() {
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [packs, setPacks] = useState<number[]>([]);
  const [error, setError] = useState("");
  const reload = () => {
    api.wallet().then(setWallet).catch((e) => setError(e.message));
    api.plans().then((p) => { setPlans(p.plans); setPacks(p.credit_packs); }).catch(() => setPlans([]));
  };
  useEffect(reload, []);
  return { wallet, plans, packs, error, reload };
}

/** บัตรที่ผูกไว้ ผูกบัตรครั้งแรกได้เครดิตฟรี ตอนนี้มีแค่ผู้ให้บริการจำลอง (PAYMENT_PROVIDER=mock)
 * ต่อผู้ให้บริการจริงเมื่อไหร่ ฟอร์มนี้เปลี่ยนเป็นสคริปต์เก็บบัตรของผู้ให้บริการ (ได้ token มา ไม่ส่งเลขบัตรให้เซิร์ฟเวอร์เรา) */
export function CardsSection({ onChange }: { onChange: () => void }) {
  const [data, setData] = useState<Cards | null>(null);
  const [last4, setLast4] = useState("4242");
  const load = () => {
    api.cards().then(setData).catch((e) => setMessage({ kind: "error", text: e.message }));
    onChange();
  };
  const { busy, message, setMessage, run } = useRunner(load);
  useEffect(() => { api.cards().then(setData).catch(() => setData(null)); }, []);

  if (!data) return null;
  const add = () => run("add", () => api.addCard(`tok_mock_${last4}`),
    (r) => (r.bonus ? tx("ผูกบัตรแล้ว ได้เครดิตฟรี {0}", { 0: fmtCredits(r.bonus) }) : tx("ผูกบัตรแล้ว")));
  return (
    <section className="card" aria-labelledby="cards-title">
      <h2 id="cards-title">{tx("บัตรที่ผูกไว้")}</h2>
      {data.bonus_available && (
        <div className="alert info">{tx("ผูกบัตรเครดิตหรือเดบิตครั้งแรก รับฟรี")} {fmtCredits(data.bonus)}  {tx("ยังไม่ตัดเงินตอนผูก")}</div>
      )}
      {data.cards.length > 0 && (
        <ul className="card-list">
          {data.cards.map((c) => (
            <li key={c.id}>
              <span>{c.brand} •••• {c.last4}</span>
              <span className="dim">{tx("หมดอายุ")} {String(c.exp_month).padStart(2, "0")}/{String(c.exp_year).slice(-2)}</span>
              <button type="button" className="btn small" disabled={!!busy}
                onClick={() => window.confirm(tx("ลบบัตร {0} ลงท้าย {1}?", { 0: c.brand, 1: c.last4 }))
                  && run(`rm-${c.id}`, () => api.removeCard(c.id), tx("ลบบัตรแล้ว"))}>
                {busy === `rm-${c.id}` ? "..." : tx("ลบ")}
              </button>
            </li>
          ))}
        </ul>
      )}
      {data.provider === "mock" ? (
        <div className="row" style={{ gap: 8 }}>
          <input className="input" style={{ width: 110 }} inputMode="numeric" maxLength={4} aria-label={tx("เลขท้าย 4 ตัวของบัตรทดสอบ")}
            value={last4} onChange={(e) => setLast4(e.target.value.replace(/\D/g, ""))} />
          <button type="button" className="btn primary small" disabled={!!busy || last4.length !== 4} onClick={add}>
            {busy === "add" ? tx("กำลังผูก...") : tx("ผูกบัตรทดสอบ")}
          </button>
          <span className="dim">{tx("โหมดทดสอบ ไม่มีการตัดเงินจริง")}</span>
        </div>
      ) : !data.provider ? (
        <span className="dim">{tx("ยังไม่ได้เชื่อมช่องทางชำระเงิน ผูกบัตรได้เร็ว ๆ นี้")}</span>
      ) : null}
      <Alert m={message} />
    </section>
  );
}

const SLIP_STATUS: Record<string, string> = {
  pending: "รอโอน", review: "รอตรวจสลิป", rejected: "สลิปไม่ผ่าน", paid: "เติมแล้ว",
};

/** รายการโอนที่ยังไม่จบ กดเพื่อเปิดกล่องแนบสลิป */
export function OpenPayments({ orders, onOpen }: { orders: PaymentOrder[]; onOpen: (order: PaymentOrder) => void }) {
  const open = orders.filter((o) => o.status === "pending" || o.status === "review" || o.status === "rejected");
  if (!open.length) return null;
  return (
    <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
      {open.map((o) => (
        <button key={o.id} type="button" className="btn small" onClick={() => onOpen(o)}>
          {fmtBaht(o.amount)} · {tx(SLIP_STATUS[o.status] ?? o.status)}
        </button>
      ))}
    </div>
  );
}

/** ยอดที่ต้องโอน บัญชีรับเงิน และช่องแนบรูปสลิป */
export function SlipBox({ order, busy, onUpload }: { order: PaymentOrder; busy: string; onUpload: (file: File) => void }) {
  const [copied, setCopied] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const payee = order.payee;
  useEffect(() => { setFile(null); setCopied(false); }, [order.id]);
  const copy = async () => {
    if (!payee?.account) return;
    try {
      await navigator.clipboard.writeText(payee.account.replace(/\s/g, ""));
      setCopied(true);
    } catch { /* เบราว์เซอร์ไม่ให้คัดลอก ผู้ใช้ยังคัดจากข้อความบนจอได้ */ }
  };
  const canUpload = order.status === "pending" || order.status === "rejected";
  return (
    <section className="card" aria-labelledby="slip-title">
      <h2 id="slip-title">{tx("โอนเงินแล้วแนบสลิป")}</h2>
      <span className="muted">
        {tx("ระบบอ่านสลิปด้วย Typhoon OCR ถ้ายอดและเลขบัญชีปลายทางตรง จะเติมให้ทันที ถ้าไม่ตรงจะส่งให้ผู้ดูแลตรวจ")}
      </span>
      <div className="row" style={{ gap: 20, flexWrap: "wrap", alignItems: "flex-end" }}>
        <div>
          <div className="dim">{tx("ยอดที่ต้องโอน")}</div>
          <div style={{ fontSize: 26, fontWeight: 600 }}>{fmtBaht(order.amount)}</div>
        </div>
        {payee && (
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {payee.bank && <span>{tx("ธนาคาร")} {payee.bank}</span>}
            {payee.name && <span>{tx("ชื่อบัญชี")} {payee.name}</span>}
            <span className="mono">
              {payee.account}{" "}
              <button type="button" className="btn small" onClick={copy}>{copied ? tx("คัดลอกแล้ว") : tx("คัดลอก")}</button>
            </span>
          </div>
        )}
      </div>
      {order.note && order.status !== "pending" && <div className="alert info">{order.note}</div>}
      {order.status === "review" && <span className="dim">{tx("ส่งสลิปแล้ว รอผู้ดูแลตรวจ ส่งรูปใหม่ไม่ได้จนกว่าจะมีผลตรวจ")}</span>}
      {canUpload && (
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <input key={order.id} type="file" accept="image/jpeg,image/png,.jpg,.jpeg,.png" aria-label={tx("รูปสลิป (JPG หรือ PNG)")}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <button type="button" className="btn primary small" disabled={!file || !!busy} onClick={() => file && onUpload(file)}>
            {busy === "slip" ? tx("กำลังอ่านสลิป...") : order.status === "rejected" ? tx("ส่งสลิปใหม่") : tx("ส่งสลิป")}
          </button>
        </div>
      )}
    </section>
  );
}
