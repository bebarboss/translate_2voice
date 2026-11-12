import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ACTIVE_PLAN_KEPT, trialClaimNotice, trialOffer } from "./trial-offer.ts";

describe("trialOffer", () => {
  it("hides the claim button while a paid plan is active", () => {
    assert.equal(trialOffer({ plan_id: "starter" }, false), "active-plan");
    assert.equal(trialOffer({ plan_id: "pro" }, true), "active-plan");
  });

  it("shows the claim button only when the trial is still available", () => {
    assert.equal(trialOffer(null, true), "claim");
    assert.equal(trialOffer(undefined, true), "claim");
  });

  it("keeps the current-trial and already-claimed states", () => {
    assert.equal(trialOffer({ plan_id: "trial" }, false), "using-trial");
    assert.equal(trialOffer(null, false), "claimed");
  });
});

describe("trialClaimNotice", () => {
  it("turns an active-plan 409 into the friendly note", () => {
    const detail = "มีแพ็กเกจที่ยังไม่หมดอายุ จึงไม่ให้แพ็กทดลองทับ";
    assert.equal(trialClaimNotice(409, detail, { plan_id: "starter" }), ACTIVE_PLAN_KEPT);
    assert.equal(trialClaimNotice(409, detail, null), ACTIVE_PLAN_KEPT);
  });

  it("leaves an already-claimed 409 to the API message", () => {
    assert.equal(trialClaimNotice(409, "บัญชีนี้รับแพ็กทดลองไปแล้ว", null), null);
  });

  it("ignores other statuses", () => {
    assert.equal(trialClaimNotice(400, "มีแพ็กเกจที่ยังไม่หมดอายุ", { plan_id: "starter" }), null);
  });
});
