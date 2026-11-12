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
