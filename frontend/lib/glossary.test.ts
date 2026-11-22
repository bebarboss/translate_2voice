import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parseGlossary, serializeGlossary } from "./glossary.ts";

describe("glossary", () => {
  it("parses source = target # note, keeping old lines without a note", () => {
    assert.deepEqual(parseGlossary("DE Practice = DE Practice # ชื่อแอป คงอักษรละติน\n\nドラえもん = โดราเอมอน\nC# = ซีชาร์ป"), [
      { source: "DE Practice", target: "DE Practice", note: "ชื่อแอป คงอักษรละติน" },
      { source: "ドラえもん", target: "โดราเอมอน", note: "" },
      { source: "C#", target: "ซีชาร์ป", note: "" },
    ]);
  });

  it("keeps half-typed lines instead of dropping them", () => {
    assert.deepEqual(parseGlossary("Duolingo"), [{ source: "Duolingo", target: "", note: "" }]);
  });

  it("round-trips and drops empty rows", () => {
    const text = "DE Practice = DE Practice # ชื่อแอป\nDuolingo = ดูโอลิงโก";
    assert.equal(serializeGlossary(parseGlossary(text)), text);
    assert.equal(serializeGlossary([{ source: " ", target: "", note: "x" }, { source: "A  B", target: "เอ\nบี", note: "" }]), "A B = เอ บี");
  });
});
