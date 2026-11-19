import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  badgeText,
  bellAriaLabel,
  internalNotifPath,
  notifIcon,
  relativeTime,
  unreadCount,
} from "./notifications.ts";

const T0 = 1_700_000_000;

describe("unreadCount", () => {
  it("keeps whole counts and drops the fraction", () => {
    assert.equal(unreadCount(0), 0);
    assert.equal(unreadCount(3), 3);
    assert.equal(unreadCount(9.9), 9);
    assert.equal(unreadCount(14), 14);
  });

  it("treats negatives and non-numbers as zero", () => {
    assert.equal(unreadCount(-4), 0);
    assert.equal(unreadCount(Number.NaN), 0);
    assert.equal(unreadCount(Number.POSITIVE_INFINITY), 0);
    assert.equal(unreadCount(undefined as unknown as number), 0);
  });
});

describe("badgeText", () => {
  it("hides the badge when nothing is unread", () => {
    assert.equal(badgeText(0), null);
    assert.equal(badgeText(-1), null);
  });

  it("shows 1 through 9 as the number", () => {
    for (let n = 1; n <= 9; n++) assert.equal(badgeText(n), String(n));
  });

  it("caps the visible badge at 9+ and never uses 99+", () => {
    assert.equal(badgeText(10), "9+");
    assert.equal(badgeText(14), "9+");
    assert.equal(badgeText(99), "9+");
    assert.equal(badgeText(100), "9+");
    assert.notEqual(badgeText(14), "14");
    assert.notEqual(badgeText(100), "99+");
  });
});

describe("bellAriaLabel", () => {
  it("uses the plain name when nothing is unread", () => {
    assert.deepEqual(bellAriaLabel(0), { template: "การแจ้งเตือน" });
    assert.deepEqual(bellAriaLabel(-2), { template: "การแจ้งเตือน" });
  });

  it("uses the real count, including when the badge is 9+", () => {
    assert.deepEqual(bellAriaLabel(1), { template: "การแจ้งเตือน ({n} ยังไม่อ่าน)", n: 1 });
    assert.deepEqual(bellAriaLabel(9), { template: "การแจ้งเตือน ({n} ยังไม่อ่าน)", n: 9 });
    assert.deepEqual(bellAriaLabel(14), { template: "การแจ้งเตือน ({n} ยังไม่อ่าน)", n: 14 });
    assert.deepEqual(bellAriaLabel(100), { template: "การแจ้งเตือน ({n} ยังไม่อ่าน)", n: 100 });
  });
});

describe("relativeTime", () => {
  it("says just now under a minute, and for a future timestamp", () => {
    assert.deepEqual(relativeTime(T0, T0), { template: "เมื่อกี้" });
    assert.deepEqual(relativeTime(T0, T0 + 59.9), { template: "เมื่อกี้" });
    assert.deepEqual(relativeTime(T0 + 30, T0), { template: "เมื่อกี้" });
  });

  it("counts whole minutes until an hour", () => {
    assert.deepEqual(relativeTime(T0, T0 + 60), { template: "{n} นาทีที่แล้ว", n: 1 });
    assert.deepEqual(relativeTime(T0, T0 + 119), { template: "{n} นาทีที่แล้ว", n: 1 });
    assert.deepEqual(relativeTime(T0, T0 + 3599), { template: "{n} นาทีที่แล้ว", n: 59 });
  });

  it("counts whole hours until a day", () => {
    assert.deepEqual(relativeTime(T0, T0 + 3600), { template: "{n} ชั่วโมงที่แล้ว", n: 1 });
    assert.deepEqual(relativeTime(T0, T0 + 86399), { template: "{n} ชั่วโมงที่แล้ว", n: 23 });
  });

  it("counts whole days after that", () => {
    assert.deepEqual(relativeTime(T0, T0 + 86400), { template: "{n} วันที่แล้ว", n: 1 });
    assert.deepEqual(relativeTime(T0, T0 + 86400 * 3 + 4000), { template: "{n} วันที่แล้ว", n: 3 });
  });

  it("does not throw when the timestamps are not numbers", () => {
    assert.deepEqual(relativeTime(Number.NaN, T0), { template: "เมื่อกี้" });
    assert.deepEqual(relativeTime(T0, Number.NaN), { template: "เมื่อกี้" });
  });
});

describe("notifIcon", () => {
  it("maps the four designed job and credit kinds", () => {
    assert.equal(notifIcon("job_done"), "done");
    assert.equal(notifIcon("job_failed"), "fail");
    assert.equal(notifIcon("credits_low"), "credits");
    assert.equal(notifIcon("job_review"), "review");
  });

  it("maps actor inbox kinds to the mic", () => {
    assert.equal(notifIcon("actor_approved"), "actor");
    assert.equal(notifIcon("actor_rejected"), "actor");
    assert.equal(notifIcon("actor_paid"), "actor");
  });

  it("uses a neutral icon for unknown kinds, including voice and payment rows", () => {
    assert.equal(notifIcon("voice_approved"), "neutral");
    assert.equal(notifIcon("voice_rejected"), "neutral");
    assert.equal(notifIcon("payment_received"), "neutral");
    assert.equal(notifIcon(""), "neutral");
    assert.equal(notifIcon("Job_Done"), "neutral");
    assert.equal(notifIcon("actor"), "neutral");
    assert.equal(notifIcon(undefined as unknown as string), "neutral");
  });

  it("trims whitespace before matching", () => {
    assert.equal(notifIcon("  job_review  "), "review");
    assert.equal(notifIcon(" actor_paid "), "actor");
  });
});

describe("internalNotifPath", () => {
  it("keeps in-app paths, including a query", () => {
    assert.equal(internalNotifPath("/jobs/job_1"), "/jobs/job_1");
    assert.equal(internalNotifPath("/account?tab=prefs"), "/account?tab=prefs");
    assert.equal(internalNotifPath("/promotions"), "/promotions");
    assert.equal(internalNotifPath("/actor"), "/actor");
    assert.equal(internalNotifPath("  /jobs/a#clip  "), "/jobs/a#clip");
  });

  it("rejects anything that is not a single in-app path", () => {
    assert.equal(internalNotifPath(""), null);
    assert.equal(internalNotifPath("jobs/1"), null);
    assert.equal(internalNotifPath("https://pakdee-app.cobie.online/jobs/1"), null);
    assert.equal(internalNotifPath("//evil.example/jobs/1"), null);
    assert.equal(internalNotifPath("/\\evil"), null);
    assert.equal(internalNotifPath("/jobs/1/../..//evil"), null);
    assert.equal(internalNotifPath("javascript:alert(1)"), null);
    assert.equal(internalNotifPath("/jobs/1?next=http://evil.example"), null);
    assert.equal(internalNotifPath("/jobs/\n1"), null);
    assert.equal(internalNotifPath("/jobs/1\n"), "/jobs/1");
    assert.equal(internalNotifPath("/jobs/my file"), null);
    assert.equal(internalNotifPath(undefined as unknown as string), null);
  });
});
