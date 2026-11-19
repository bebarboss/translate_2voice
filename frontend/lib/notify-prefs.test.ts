import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  EMAIL_PREF_DEFAULTS,
  EMAIL_PREF_KINDS,
  EMAIL_PREF_LABEL,
  PREF_SAVE_ERROR,
  PREF_SAVE_INVALID,
  PREF_SAVED,
  alwaysOnLabel,
  emailPrefPatch,
  loadNotifyPrefs,
  lockedRows,
  optimisticEmailPrefs,
  parseNotifyPrefs,
  prefSaveNotice,
  settlePrefToggle,
} from "./notify-prefs.ts";

const full = {
  email: { job_review: true, job_done: false, job_failed: true, credits_low: false },
  always_on: ["actor_paid", "voice_approved"],
};

describe("parseNotifyPrefs", () => {
  it("keeps the four switches and lists locked kinds separately", () => {
    const prefs = parseNotifyPrefs(full);
    assert.ok(prefs);
    assert.equal(prefs.email.job_done, false);
    assert.equal(prefs.email.credits_low, false);
    assert.deepEqual(prefs.locked, ["actor_paid", "voice_approved"]);
    assert.deepEqual(lockedRows(prefs.always_on).map((row) => row.label), [
      "ผลใบสมัครและผลตรวจเสียงนักพากย์",
      "ค่าตอบแทนนักพากย์",
    ]);
    assert.equal(lockedRows(["actor_approved", "voice_rejected", "payment"]).length, 2);
    assert.equal(alwaysOnLabel("actor_paid"), "ค่าตอบแทนนักพากย์");
    assert.equal(alwaysOnLabel("mystery_kind"), "อีเมลที่ปิดไม่ได้");
  });

  it("drops unknown email keys, blanks, and duplicate always-on kinds", () => {
    const prefs = parseNotifyPrefs({
      email: { ...full.email, newsletter: true },
      always_on: [" actor_paid ", "actor_paid", "", "เงินเดือน"],
    });
    assert.ok(prefs);
    assert.equal("newsletter" in prefs.email, false);
    assert.deepEqual(prefs.always_on, ["actor_paid", "เงินเดือน"]);
    assert.deepEqual(prefs.locked, ["actor_paid", "เงินเดือน"]);
    assert.equal(alwaysOnLabel("เงินเดือน"), "เงินเดือน");
    assert.equal(lockedRows(["เงินเดือน"])[0]?.note, "ส่งเสมอ");
  });

  it("fills missing kinds with the on-by-default values", () => {
    const prefs = parseNotifyPrefs({ email: { job_done: false }, always_on: [] });
    assert.ok(prefs);
    assert.deepEqual(prefs.email, { ...EMAIL_PREF_DEFAULTS, job_done: false });
  });

  it("locks a toggleable kind that the server also marks always-on", () => {
    const prefs = parseNotifyPrefs({
      email: { job_review: false, job_done: false, job_failed: true, credits_low: true },
      always_on: ["job_done", "actor_paid", "job_done"],
    });
    assert.ok(prefs);
    assert.equal(prefs.email.job_done, true);
    assert.equal(prefs.email.job_review, false);
    assert.deepEqual(prefs.locked, ["actor_paid"]);
    assert.equal(prefs.always_on.includes("job_done"), true);
  });

  it("rejects a body that is not the contract", () => {
    assert.equal(parseNotifyPrefs(null), null);
    assert.equal(parseNotifyPrefs({ email: full.email }), null);
    assert.equal(parseNotifyPrefs({ email: { job_done: "no" }, always_on: [] }), null);
    assert.equal(parseNotifyPrefs({ email: full.email, always_on: [1] }), null);
  });
});

describe("loadNotifyPrefs", () => {
  it("uses the granular switches on 200 and the legacy switch on 404", () => {
    const ready = loadNotifyPrefs(200, full);
    assert.equal(ready.mode, "granular");
    assert.equal(loadNotifyPrefs(404, { detail: "not found" }).mode, "legacy");
    assert.equal(loadNotifyPrefs(500, null).mode, "error");
    assert.equal(loadNotifyPrefs(422, { email: full.email }).mode, "error");
    assert.equal(loadNotifyPrefs(200, { email: "nope" }).mode, "error");
  });
});

describe("toggle merge", () => {
  it("sends one known key and rolls back when the reply cannot be read", () => {
    const snapshot = { ...full.email };
    assert.deepEqual(emailPrefPatch("job_done", false), { job_done: false });
    const optimistic = optimisticEmailPrefs(snapshot, "job_done", true);
    assert.equal(optimistic.job_done, true);
    assert.equal(optimistic.job_review, snapshot.job_review);
    assert.equal(snapshot.job_done, false);

    const saved = settlePrefToggle(snapshot, {
      email: optimistic,
      always_on: ["money"],
    });
    assert.equal(saved.ok, true);
    if (saved.ok) {
      assert.equal(saved.prefs.email.job_done, true);
      assert.deepEqual(saved.prefs.locked, ["money"]);
    }

    const failed = settlePrefToggle(snapshot, { email: { job_done: 1 } });
    assert.deepEqual(failed, { ok: false, email: snapshot, error: PREF_SAVE_ERROR });
  });

  it("has a Thai label for every switch", () => {
    for (const kind of EMAIL_PREF_KINDS) assert.equal(typeof EMAIL_PREF_LABEL[kind], "string");
    assert.equal(EMAIL_PREF_LABEL.job_review, "รอตรวจบท");
    assert.equal(EMAIL_PREF_LABEL.job_done, "พากย์เสร็จ");
    assert.equal(EMAIL_PREF_LABEL.job_failed, "งานไม่สำเร็จ");
    assert.equal(EMAIL_PREF_LABEL.credits_low, "เครดิตใกล้หมด");
    assert.deepEqual(prefSaveNotice(200), { role: "status", text: PREF_SAVED });
    assert.deepEqual(prefSaveNotice(422), { role: "alert", text: PREF_SAVE_INVALID });
    assert.equal(prefSaveNotice(500).text, PREF_SAVE_ERROR);
    assert.equal(prefSaveNotice(0).role, "alert");
  });
});
