import assert from "node:assert/strict";
import test from "node:test";
import { DEMO_CLIPS, pickLang, visibleDemoClips, type DemoClip } from "./demo-clips.ts";

const clip = (n: number, over: Partial<DemoClip> = {}): DemoClip => ({
  title: `คลิป ${n}`, before: `/brand/demo/${n}-before.mp3`, after: `/brand/demo/${n}-after.mp3`, ...over,
});

test("empty list hides the section", () => {
  assert.deepEqual(visibleDemoClips([]), []);
});

test("shipped list has no placeholder clips", () => {
  assert.deepEqual(visibleDemoClips(DEMO_CLIPS), DEMO_CLIPS.slice(0, 3));
});

test("keeps at most three clips", () => {
  assert.equal(visibleDemoClips([1, 2, 3, 4].map((n) => clip(n))).length, 3);
});

test("drops clips without a title or with off-site audio", () => {
  const out = visibleDemoClips([
    clip(1, { title: "" }),
    clip(2, { before: "https://example.com/a.mp3" }),
    clip(3, { after: "//cdn.example.com/b.mp3" }),
    clip(4, { after: "" }),
    clip(5),
  ]);
  assert.deepEqual(out.map((c) => c.title), ["คลิป 5"]);
});

test("pickLang falls back to Thai", () => {
  assert.equal(pickLang("ไทย", "en"), "ไทย");
  assert.equal(pickLang({ th: "ไทย", en: "English" }, "en"), "English");
  assert.equal(pickLang({ th: "ไทย" }, "en"), "ไทย");
  assert.equal(pickLang({ th: "ไทย", en: "English" }, "th"), "ไทย");
  assert.equal(pickLang(undefined, "th"), "");
});
