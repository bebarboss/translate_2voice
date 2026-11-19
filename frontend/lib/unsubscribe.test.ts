import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { EMAIL_PREF_KINDS, EMAIL_PREF_LABEL } from "./notify-prefs.ts";
import {
  CONFIRM_BUTTON,
  EXPIRED_BUTTON,
  EXPIRED_TITLE,
  GENERIC_CATEGORY,
  UNSUBSCRIBE_PATH,
  categoryLabel,
  confirmCategoryLine,
  mapUnsubscribePreview,
  mapUnsubscribeResponse,
  readUnsubscribeToken,
} from "./unsubscribe.ts";

const planted = "secret-unsubscribe-token";

describe("unsubscribe token", () => {
  it("treats a blank token as absent and does not keep surrounding spaces", () => {
    assert.equal(UNSUBSCRIBE_PATH, "/notifications/unsubscribe");
    assert.equal(readUnsubscribeToken(null), "");
    assert.equal(readUnsubscribeToken("   "), "");
    assert.equal(readUnsubscribeToken("  abc  "), "abc");
  });
});

describe("mapUnsubscribePreview", () => {
  it("shows the Thai label on the confirm screen when GET returns a known category", () => {
    for (const kind of EMAIL_PREF_KINDS) {
      const view = mapUnsubscribePreview(200, { category: kind, token: planted });
      assert.deepEqual(view, { state: "confirm", category: kind });
      assert.equal(categoryLabel(kind), EMAIL_PREF_LABEL[kind]);
      assert.equal(confirmCategoryLine(kind), `ยกเลิกอีเมล ${EMAIL_PREF_LABEL[kind]}`);
    }
    assert.equal(confirmCategoryLine("job_done"), "ยกเลิกอีเมล พากย์เสร็จ");
    assert.equal(CONFIRM_BUTTON, "ยืนยันว่าไม่รับอีเมลนี้แล้ว");
  });

  it("falls back to the generic confirm text when the category is unknown or GET is not deployed", () => {
    assert.deepEqual(mapUnsubscribePreview(200, { category: "actor_paid" }), { state: "confirm", category: "actor_paid" });
    assert.equal(confirmCategoryLine("actor_paid"), GENERIC_CATEGORY);
    assert.equal(confirmCategoryLine(null), GENERIC_CATEGORY);
    assert.equal(confirmCategoryLine(""), GENERIC_CATEGORY);
    for (const status of [0, 404, 401, 422, 500, 502]) {
      assert.deepEqual(mapUnsubscribePreview(status, { category: "job_done", token: planted }), {
        state: "confirm",
        category: null,
      });
    }
    assert.deepEqual(mapUnsubscribePreview(200, {}), { state: "confirm", category: null });
    assert.deepEqual(mapUnsubscribePreview(200, null), { state: "confirm", category: null });
  });

  it("sends 400 to the invalid state and 410 to the expired state without unsubscribing", () => {
    assert.deepEqual(mapUnsubscribePreview(400, { detail: planted }), { state: "invalid" });
    assert.deepEqual(mapUnsubscribePreview(410, { detail: planted }), { state: "expired" });
    assert.equal(EXPIRED_TITLE, "ลิงก์นี้หมดอายุแล้ว");
    assert.equal(EXPIRED_BUTTON, "ไปที่การตั้งค่าอีเมล");
  });

  it("does not copy a token from the GET body into the view", () => {
    const view = mapUnsubscribePreview(200, { category: "job_failed", token: planted });
    assert.equal(JSON.stringify(view).includes(planted), false);
    assert.equal(JSON.stringify(mapUnsubscribePreview(410, { token: planted })).includes(planted), false);
  });
});

describe("mapUnsubscribeResponse", () => {
  it("keeps success, invalid, and expired apart", () => {
    assert.deepEqual(mapUnsubscribeResponse(200, { ok: true, category: "job_done", token: planted }), {
      state: "success",
      category: "job_done",
    });
    assert.equal(mapUnsubscribeResponse(400, { detail: planted }).state, "invalid");
    assert.equal(mapUnsubscribeResponse(401, null).state, "invalid");
    assert.equal(mapUnsubscribeResponse(410, null).state, "expired");
    for (const status of [0, 404, 422, 500, 502]) {
      assert.equal(mapUnsubscribeResponse(status, { ok: true, category: "job_done" }).state, "retry");
    }
    assert.equal(mapUnsubscribeResponse(200, { ok: false, category: "job_done" }).state, "retry");
    assert.equal(mapUnsubscribeResponse(200, { ok: true }).state, "retry");
    assert.equal(JSON.stringify(mapUnsubscribeResponse(200, { ok: true, category: "credits_low", token: planted })).includes(planted), false);
  });
});
