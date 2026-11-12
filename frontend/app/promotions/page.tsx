"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Alert, CardsSection, fmtCredits, fmtDate, OpenPayments, SlipBox, useRunner, useWallet } from "@/components/Billing";
import { api, type PaymentOrder, type Plan } from "@/lib/api";
import { fmtBaht } from "@/lib/format";
import { tx } from "@/lib/i18n";
import { useAuth } from "@/lib/useAuth";

/** แพ็กเกจและโปรโมชัน: ทดลอง / เริ่มต้น / มือโปร + เครดิตเติม */
export default function PromotionsPage() {
  const { config, user, loaded } = useAuth();
  const { wallet, plans, packs, error, reload } = useWallet();
  const [pack, setPack] = useState(30);
  const [order, setOrder] = useState<PaymentOrder | null>(null);
  const [open, setOpen] = useState<PaymentOrder[]>([]);
  const [flash, setFlash] = useState("");
  const slip = config?.payment_provider === "slip";
  const stripe = config?.payment_provider === "stripe";
  const refresh = () => {
    reload();
    if (slip) api.myPayments().then(setOpen).catch(() => setOpen([]));
  };
  const { busy, message, run } = useRunner(refresh);
  useEffect(() => { if (slip) api.myPayments().then(setOpen).catch(() => setOpen([])); }, [slip]);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const q = new URLSearchParams(window.location.search);
    const paidId = q.get("paid");
    if (paidId) {
      window.history.replaceState({}, "", "/promotions");
      api.confirmPayment(paidId)
        .then((ord) => {
          setFlash(ord.status === "paid"
            ? tx("ชำระเงินสำเร็จ เครดิตเข้าแล้ว")
            : tx("รอการยืนยันจาก Stripe ลองรีเฟรชในอีกสักครู่"));
          reload();
        })
        .catch((e) => setFlash(e instanceof Error ? e.message : tx("ยืนยันการชำระเงินไม่สำเร็จ")));
    } else if (q.get("cancel")) {
      setFlash(tx("ยกเลิกการชำระเงินแล้ว"));
      window.history.replaceState({}, "", "/promotions");
    }
  }, [reload]);
  const beginSlip = (key: string, fn: () => Promise<PaymentOrder>) =>
    run(key, async () => {
      const created = await fn();
      if (created.status !== "paid") setOrder(created);
      return created;
    }, (created) => created.status === "paid" ? tx("ชำระแล้ว") : tx("สร้างรายการแล้ว โอนตามยอดด้านล่าง แล้วแนบรูปสลิป"));
  const beginStripe = (key: string, fn: () => Promise<PaymentOrder>) =>
    run(key, async () => {
      const created = await fn();
      if (created.checkout_url) {
        window.location.href = created.checkout_url;
        return created;
      }
      // แพ็กฟรี (ทดลอง) จ่าย 0 ไม่มี Checkout — รับ status=paid แล้วจบ
      if (created.status === "paid") return created;
      throw new Error(tx("ไม่ได้รับลิงก์ชำระเงินจาก Stripe"));
    }, (created) => created.status === "paid" ? tx("ชำระแล้ว") : tx("กำลังไปหน้าชำระเงิน..."));
  const sendSlip = (file: File) => {
    if (!order) return;
    run("slip", async () => {
      const updated = await api.uploadSlip(order.id, file);
      setOrder(updated.status === "paid" ? null : updated);
      return updated;
    }, (updated) => updated.note || tx("ส่งสลิปแล้ว"));
  };
  useEffect(() => {
    if (loaded && config?.auth && !user) window.location.href = "/welcome?next=/promotions";
  }, [loaded, config, user]);

  if (!loaded || (config?.auth && !user)) return <main className="page"><div className="empty">{tx("กำลังโหลด...")}</div></main>;
  if (!config?.billing || !user) {
    return <main className="page narrow"><div className="card"><span className="muted">{tx("เครดิตและแพ็กเกจยังไม่เปิดใช้งาน")}</span></div></main>;
  }
  const payments = config.payments;
  const sub = wallet?.subscription;
  const ent = wallet?.entitlements;
  const current = plans.find((p) => p.id === sub?.plan_id);
  const pay = (key: string, fn: () => Promise<PaymentOrder>, done: string) => {
    if (slip) return beginSlip(key, fn);
    if (stripe) return beginStripe(key, fn);
    return run(key, fn, done);
  };
  const paying = busy ? (slip ? tx("กำลังสร้างรายการ...") : stripe ? tx("กำลังไปหน้าชำระเงิน...") : tx("กำลังซื้อ...")) : null;

  const planAction = (p: Plan) => {
    if (p.available === false) {
      return <span className="badge awaiting_review">{tx("อยู่ระหว่างพัฒนา")}</span>;
    }
    if (p.free_once || p.price <= 0) {
      if (!ent?.trial_available && sub?.plan_id !== "trial") {
        return <span className="dim">{tx("รับไปแล้ว")}</span>;
      }
      if (sub?.plan_id === "trial") {
        return <span className="dim">{tx("กำลังใช้แพ็กนี้")}</span>;
      }
      return (
        <button type="button" className="btn primary small" disabled={!!busy}
          onClick={() => run("trial", () => api.claimTrial(), tx("เริ่มแพ็กทดลองแล้ว"))}>
          {busy === "trial" ? tx("กำลังเปิด...") : tx("เริ่มทดลองฟรี")}
        </button>
      );
    }
    const isCurrent = p.id === sub?.plan_id;
    return (
      <button type="button" className="btn small" disabled={!payments || !!busy}
        onClick={() => window.confirm(tx("ซื้อแพ็กเกจ{0} {1}? เครดิตแพ็กเกจที่เหลือทบไปได้ 1 รอบ", { 0: p.name, 1: fmtBaht(p.price) }))
          && pay(p.id, () => api.subscribe(p.id), tx("เริ่มแพ็กเกจ{0}แล้ว", { 0: p.name }))}>
        {busy === p.id ? paying : isCurrent ? tx("ต่ออายุ") : slip ? tx("โอน {0}", { 0: fmtBaht(p.price) }) : stripe ? tx("ชำระ {0}", { 0: fmtBaht(p.price) }) : tx("ซื้อแพ็กเกจนี้")}
      </button>
    );
  };

  return (
    <main className="page" style={{ maxWidth: 960 }}>
      <div className="page-head">
        <div>
          <h1>{tx("แพ็กเกจและโปรโมชัน")}</h1>
          <span className="muted">
            {tx("เครดิตคงเหลือ")} {wallet ? fmtCredits(wallet.credits + (sub?.minutes_left ?? 0)) : "..."}
            {sub && current && ` · ${tx("{0} · หมดอายุ {1}", { 0: current.name, 1: fmtDate(sub.expires_at) })}`}
          </span>
        </div>
        <Link href="/account" className="btn small">{tx("ดูประวัติเครดิต")}</Link>
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {flash && <div className="alert info" role="status">{flash}</div>}
      {user.admin && <div className="alert info">{tx("บัญชีผู้ดูแลระบบพากย์ได้ไม่จำกัด ไม่ถูกตัดเครดิต")}</div>}
      {ent?.trial_available && (
        <div className="alert info" role="status">
          {tx("ยังไม่มีแพ็กทดลอง — กดรับฟรี 2 เครดิตได้ครั้งเดียว (ปกติได้ตอนเข้าสู่ระบบแล้ว)")}
        </div>
      )}
      <span className="dim">{tx("1 เครดิต = คลิป 1 นาที คิดตามความยาวจริง ตัดตอนเริ่มวิเคราะห์ ใช้เครดิตแพ็กเกจก่อน แล้วค่อยใช้เครดิตเติม เครดิตแพ็กเกจที่เหลือทบไปได้ 1 รอบเมื่อต่ออายุหรืออัปเกรด พากย์ซ้ำคิด 0.1 เครดิตต่อวินาทีของประโยคที่แก้ (ฟรีไม่เกิน 10% ของคลิป และประโยคที่ AI ติดธงฟรี)")}</span>

      {!user.admin && !slip && !stripe && <CardsSection onChange={reload} />}
      {slip && <OpenPayments orders={open} onOpen={setOrder} />}
      {slip && order && <SlipBox order={order} busy={busy} onUpload={sendSlip} />}

      <section aria-labelledby="plans-title" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 id="plans-title" style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>{tx("แพ็กเกจ")}</h2>
        <div className="plans">
          {plans.map((p) => (
            <article key={p.id} className={`card plan${p.id === sub?.plan_id ? " current" : ""}${p.available === false ? " dim" : ""}`}>
              <span style={{ fontSize: 17, fontWeight: 600 }}>{tx(p.name)}</span>
              <span style={{ fontSize: 26, fontWeight: 600 }}>
                {p.price <= 0 ? tx("ฟรี") : fmtBaht(p.price)}
                {p.price > 0 && <span className="dim"> / {p.days}  {tx("วัน")}</span>}
              </span>
              <span className="muted">{fmtCredits(p.minutes)}{p.max_clip_minutes != null ? ` · ${tx("คลิปยาวสุด {0} นาที", { 0: p.max_clip_minutes })}` : ""}</span>
              {p.available === false && (
                <span className="muted" style={{ fontSize: 13 }}>{tx("แพ็กเกจนี้ยังไม่เปิดขาย — อยู่ระหว่างพัฒนา")}</span>
              )}
              <ul className="dim" style={{ margin: "8px 0", paddingLeft: 18, fontSize: 13, lineHeight: 1.45 }}>
                {(p.features?.length ? p.features : []).map((f) => <li key={f}>{tx(f)}</li>)}
                {!p.features?.length && (
                  <>
                    {p.watermark && <li>{tx("ดาวน์โหลดมีลายน้ำ")}</li>}
                    {p.voices === "standard" && <li>{tx("เสียง Standard เท่านั้น")}</li>}
                    {p.voices === "all" && <li>{tx("เลือกเสียงได้ทั้งหมด")}</li>}
                    {p.timeline ? <li>{tx("นำเข้าไทม์ไลน์ได้")}</li> : p.id !== "trial" && <li>{tx("นำเข้าไทม์ไลน์ล็อกไว้")}</li>}
                  </>
                )}
              </ul>
              {planAction(p)}
            </article>
          ))}
        </div>
      </section>

      {wallet && (
        <section className="card" aria-labelledby="topup-title">
          <h2 id="topup-title">{tx("ซื้อเครดิตเติม")}</h2>
          <span className="muted">{tx("เครดิตเติมไม่หมดอายุ · เครดิตละ")} {fmtBaht(wallet.credit_price)} · {tx("ซื้อได้เมื่อมีแพ็กเกจ")}</span>
          {!ent?.can_topup ? (
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
              <span className="dim">{tx("ยังไม่มีแพ็กเกจ — รับทดลองหรือซื้อแพ็กก่อนจึงเติมเครดิตได้")}</span>
              {ent?.trial_available && (
                <button type="button" className="btn primary small" disabled={!!busy}
                  onClick={() => run("trial", () => api.claimTrial(), tx("เริ่มแพ็กทดลองแล้ว"))}>
                  {tx("เริ่มทดลองฟรี")}
                </button>
              )}
            </div>
          ) : (
            <div className="row" style={{ gap: 8 }}>
              <div className="seg" role="group" aria-label={tx("จำนวนเครดิตที่จะซื้อ")}>
                {packs.map((n) => (
                  <button key={n} type="button" aria-pressed={pack === n} onClick={() => setPack(n)}>{n.toLocaleString()}</button>
                ))}
              </div>
              <button type="button" className="btn primary small" disabled={!payments || !!busy}
                onClick={() => pay("topup", () => api.buyCredits(pack), tx("ได้ {0} แล้ว", { 0: fmtCredits(pack) }))}>
                {busy === "topup" ? paying : slip
                  ? tx("โอน {0}", { 0: fmtBaht(pack * wallet.credit_price) })
                  : stripe
                    ? tx("ชำระ {0}", { 0: fmtBaht(pack * wallet.credit_price) })
                    : tx("ซื้อ {0}", { 0: fmtBaht(pack * wallet.credit_price) })}
              </button>
            </div>
          )}
          {!payments && ent?.can_topup && <span className="dim">{tx("ยังไม่ได้เชื่อมช่องทางชำระเงิน ติดต่อผู้ดูแลเพื่อเติมเครดิต")}</span>}
        </section>
      )}
      <Alert m={message} />
    </main>
  );
}
