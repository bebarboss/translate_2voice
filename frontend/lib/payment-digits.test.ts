import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { accountNoError, normalizePaymentDigits, taxIdError } from "./payment-digits.ts";

describe("normalizePaymentDigits", () => {
  it("maps Thai and fullwidth digits and strips spaces and hyphens", () => {
    assert.equal(normalizePaymentDigits("๑๑๐-๑๗๐ ๐๒๐๓๔๕๐"), "1101700203450");
    assert.equal(normalizePaymentDigits("１１０１７００２０３４５０"), "1101700203450");
    assert.equal(normalizePaymentDigits("123-456 7890"), "1234567890");
    assert.equal(normalizePaymentDigits(" ๑๒๓-４５６ "), "123456");
    assert.equal(normalizePaymentDigits("12\u00a034-56"), "123456");
  });

  it("leaves other characters so the field can still be rejected", () => {
    assert.equal(normalizePaymentDigits("12a3"), "12a3");
    assert.equal(normalizePaymentDigits("abc"), "abc");
  });

  it("maps every fullwidth digit U+FF10..U+FF19, including 8, to ASCII", () => {
    const fullwidth = "\uFF10\uFF11\uFF12\uFF13\uFF14\uFF15\uFF16\uFF17\uFF18\uFF19";
    assert.equal(fullwidth, "０１２３４５６７８９");
    for (let i = 0; i < 10; i++) {
      assert.equal(fullwidth.codePointAt(i), 0xff10 + i);
      assert.equal(normalizePaymentDigits(fullwidth[i]), String(i));
    }
    assert.equal(normalizePaymentDigits(fullwidth), "0123456789");
  });

  it("maps ten fullwidth 8s to an account number", () => {
    const eights = "\uFF18\uFF18\uFF18\uFF18\uFF18\uFF18\uFF18\uFF18\uFF18\uFF18";
    assert.equal(eights, "８８８８８８８８８８");
    for (const ch of eights) assert.equal(ch.codePointAt(0), 0xff18);
    const normalized = normalizePaymentDigits(eights);
    assert.equal(normalized, "8888888888");
    assert.equal(accountNoError(normalized), "");
  });

  it("maps every Thai digit U+0E50..U+0E59, including ๘, to ASCII", () => {
    const thai = "\u0E50\u0E51\u0E52\u0E53\u0E54\u0E55\u0E56\u0E57\u0E58\u0E59";
    assert.equal(thai, "๐๑๒๓๔๕๖๗๘๙");
    assert.equal("๘".codePointAt(0), 0x0e58);
    assert.equal(normalizePaymentDigits("๘"), "8");
    for (let i = 0; i < 10; i++) {
      assert.equal(thai.codePointAt(i), 0x0e50 + i);
      assert.equal(normalizePaymentDigits(thai[i]), String(i));
    }
  });
});

describe("taxIdError", () => {
  it("accepts a checksum-valid 13 digit id", () => {
    assert.equal(taxIdError("1101700203450"), "");
  });

  it("rejects the wrong length and a bad checksum", () => {
    assert.equal(taxIdError("110170020345"), "เลขประจำตัวผู้เสียภาษีต้องมี 13 หลัก");
    assert.equal(taxIdError(""), "เลขประจำตัวผู้เสียภาษีต้องมี 13 หลัก");
    assert.equal(taxIdError("1101700203451"), "เลขประจำตัวผู้เสียภาษีไม่ถูกต้อง");
  });
});

describe("accountNoError", () => {
  it("accepts 10 to 15 digits and rejects the rest", () => {
    assert.equal(accountNoError("1234567890"), "");
    assert.equal(accountNoError("123456789012345"), "");
    assert.equal(accountNoError("123456789"), "เลขบัญชีต้องเป็นตัวเลข 10–15 หลัก");
    assert.equal(accountNoError("1234567890123456"), "เลขบัญชีต้องเป็นตัวเลข 10–15 หลัก");
    assert.equal(accountNoError(""), "เลขบัญชีต้องเป็นตัวเลข 10–15 หลัก");
  });
});
