"use client";

import { useState } from "react";
import { api, type ActorMe, type ActorPayment } from "@/lib/api";
import { fmtBaht } from "@/lib/format";
import { tx } from "@/lib/i18n";
import { accountNoError, normalizePaymentDigits, taxIdError } from "@/lib/payment-digits";

const EMPTY: ActorPayment = { payee_name: "", tax_id: "", address: "", bank: "", account_no: "", account_name: "" };

/** ข้อมูลรับค่าตอบแทนนักพากย์ — กรอกที่หน้าบัญชี (แก้ต้องกรอกเลขใหม่ทั้งหมด เห็นแค่ 4 ตัวท้าย) */
export default function ActorPaymentSection({ me, onSaved }: { me: ActorMe; onSaved: () => void }) {
  const [edit, setEdit] = useState(!me.payment);
  const [form, setForm] = useState<ActorPayment>(me.payment ? { ...me.payment, tax_id: "", account_no: "" } : EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [digitsError, setDigitsError] = useState({ tax_id: "", account_no: "" });
  const set = (k: keyof ActorPayment) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const setDigits = (k: "tax_id" | "account_no") => (e: { target: { value: string } }) => {
    setForm({ ...form, [k]: e.target.value });
    if (digitsError[k]) setDigitsError({ ...digitsError, [k]: "" });
  };
  const checkedDigits = (k: "tax_id" | "account_no", raw: string) => {
    const value = normalizePaymentDigits(raw);
    return { value, message: k === "tax_id" ? taxIdError(value) : accountNoError(value) };
  };
  const blurDigits = (k: "tax_id" | "account_no") => () => {
    const { value, message } = checkedDigits(k, form[k]);
    setForm({ ...form, [k]: value });
    setDigitsError({ ...digitsError, [k]: message });
  };
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    const tax = checkedDigits("tax_id", form.tax_id);
    const acc = checkedDigits("account_no", form.account_no);
    setForm({ ...form, tax_id: tax.value, account_no: acc.value });
    setDigitsError({ tax_id: tax.message, account_no: acc.message });
    if (tax.message || acc.message) return;
    setBusy(true); setError("");
    try {
      await api.actorSavePayment({ ...form, tax_id: tax.value, account_no: acc.value });
      setEdit(false);
      onSaved();
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  };
  const p = me.payment;
  const wht = me.wht.percent > 0
    ? tx("หักภาษี ณ ที่จ่ายร้อยละ {0} เมื่อจ่ายครั้งละตั้งแต่ {1} และออกหนังสือรับรองการหักภาษีให้", { 0: me.wht.percent, 1: fmtBaht(me.wht.min) })
    : "";
  return (
    <div className="actor-pay">
      <div className="set-head">
        <h2>{tx("ข้อมูลรับเงิน")}</h2>
        <p>{tx("ใช้โอนค่าตอบแทนนักพากย์และยื่นภาษี")} {wht} {tx("ข้อมูลนี้เห็นเฉพาะคุณและผู้ดูแล")}</p>
      </div>
      {!p && <div className="alert info">{tx("กรอกข้อมูลรับเงินก่อน ผู้ดูแลถึงจะจ่ายค่าตอบแทนให้ได้")}</div>}
      {p && !edit ? (
        <div className="set-group">
          <div className="set-row">
            <div><b>{tx("ผู้รับเงิน")}</b></div>
            <div className="v">{p.payee_name}</div>
          </div>
          <div className="set-row">
            <div><b>{tx("เลขผู้เสียภาษี")}</b></div>
            <div className="v">{p.tax_id}</div>
          </div>
          <div className="set-row">
            <div><b>{tx("ที่อยู่")}</b></div>
            <div className="v">{p.address}</div>
          </div>
          <div className="set-row">
            <div><b>{tx("บัญชี")}</b></div>
            <div className="v">{p.bank} {p.account_no} ({p.account_name})</div>
          </div>
          <div className="set-row">
            <div><b>{tx("แก้ไขข้อมูล")}</b><span className="d">{tx("แก้แล้วต้องกรอกเลขผู้เสียภาษีและเลขบัญชีใหม่ทั้งหมด")}</span></div>
            <div className="v"><button type="button" className="btn small" onClick={() => setEdit(true)}>{tx("แก้ไข")}</button></div>
          </div>
        </div>
      ) : (
        <form className="set-group" onSubmit={save} style={{ display: "grid", gap: 0 }}>
          <div className="set-row block">
            <div className="field" style={{ width: "100%" }}>
              <label htmlFor="pp-name">{tx("ชื่อ-นามสกุลผู้รับเงิน (ตามบัตรประชาชน)")}</label>
              <input id="pp-name" className="input" value={form.payee_name} onChange={set("payee_name")} required maxLength={100} />
            </div>
          </div>
          <div className="set-row block">
            <div className="field" style={{ width: "100%" }}>
              <label htmlFor="pp-tax">{tx("เลขประจำตัวผู้เสียภาษี / เลขบัตรประชาชน 13 หลัก")}</label>
              <input id="pp-tax" className="input" value={form.tax_id} onChange={setDigits("tax_id")} onBlur={blurDigits("tax_id")}
                required inputMode="numeric" autoComplete="off" aria-invalid={digitsError.tax_id ? true : undefined}
                aria-describedby={digitsError.tax_id ? "pp-tax-err" : undefined}
                placeholder={p ? tx("เดิม {0} (กรอกใหม่ทั้งหมด)", { 0: p.tax_id }) : ""} />
              {digitsError.tax_id && <span id="pp-tax-err" role="alert" style={{ color: "var(--danger)", fontSize: 13 }}>{tx(digitsError.tax_id)}</span>}
            </div>
          </div>
          <div className="set-row block">
            <div className="field" style={{ width: "100%" }}>
              <label htmlFor="pp-addr">{tx("ที่อยู่ตามบัตรประชาชน")}</label>
              <textarea id="pp-addr" className="textarea" rows={2} value={form.address} onChange={set("address")} required maxLength={300} />
            </div>
          </div>
          <div className="set-row block">
            <div className="field" style={{ width: "100%" }}>
              <label htmlFor="pp-bank">{tx("ธนาคาร")}</label>
              <select id="pp-bank" className="select" value={form.bank} onChange={set("bank")} required>
                <option value="">{tx("เลือกธนาคาร")}</option>
                {me.banks.map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
            </div>
          </div>
          <div className="set-row block">
            <div className="field" style={{ width: "100%" }}>
              <label htmlFor="pp-acc">{tx("เลขบัญชี")}{form.bank === "พร้อมเพย์" ? tx(" (เบอร์โทรหรือเลขบัตรประชาชน)") : ""}</label>
              <input id="pp-acc" className="input" value={form.account_no} onChange={setDigits("account_no")} onBlur={blurDigits("account_no")}
                required inputMode="numeric" autoComplete="off" aria-invalid={digitsError.account_no ? true : undefined}
                aria-describedby={digitsError.account_no ? "pp-acc-err" : undefined}
                placeholder={p ? tx("เดิม {0} (กรอกใหม่ทั้งหมด)", { 0: p.account_no }) : ""} />
              {digitsError.account_no && <span id="pp-acc-err" role="alert" style={{ color: "var(--danger)", fontSize: 13 }}>{tx(digitsError.account_no)}</span>}
            </div>
          </div>
          <div className="set-row block">
            <div className="field" style={{ width: "100%" }}>
              <label htmlFor="pp-accname">{tx("ชื่อบัญชี")}</label>
              <input id="pp-accname" className="input" value={form.account_name} onChange={set("account_name")} required maxLength={100} />
            </div>
          </div>
          {error && <div className="set-row block"><div className="alert error" role="alert">{error}</div></div>}
          <div className="set-row">
            <div className="row" style={{ gap: 10 }}>
              <button type="submit" className="btn primary small" disabled={busy}>{busy ? tx("กำลังบันทึก...") : tx("บันทึกข้อมูลรับเงิน")}</button>
              {p && <button type="button" className="btn small" onClick={() => { setEdit(false); setError(""); setDigitsError({ tax_id: "", account_no: "" }); }}>{tx("ยกเลิก")}</button>}
            </div>
          </div>
        </form>
      )}
    </div>
  );
}
