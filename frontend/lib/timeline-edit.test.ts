import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { History, snapMove, snapSec } from "./timeline-edit.ts";

describe("snap", () => {
  it("snaps to the nearest point within the threshold only", () => {
    assert.deepEqual(snapSec(5.04, [1, 5, 5.1], 0.08), { sec: 5, hit: 5 });
    assert.deepEqual(snapSec(5.5, [1, 5], 0.08), { sec: 5.5, hit: null });
  });
  it("moves a block so its nearer edge lands on the point, keeping length", () => {
    assert.deepEqual(snapMove(3.97, 2, [4, 6.02], 0.1), { start: 4, hit: 4 });
    const r = snapMove(3.5, 2.5, [6.03], 0.1); // ขอบท้าย 6.0 ชน 6.03
    assert.equal(r.hit, 6.03);
    assert.ok(Math.abs(r.start - 3.53) < 1e-9);
    assert.deepEqual(snapMove(1, 1, [9], 0.1), { start: 1, hit: null });
  });
});

describe("History", () => {
  it("undoes and redoes in order", () => {
    const h = new History<number>();
    h.record(1, "a", 0); h.record(2, "b", 5000);
    assert.equal(h.undo(3), 2);
    assert.equal(h.undo(2), 1);
    assert.equal(h.undo(1), null);
    assert.equal(h.redo(1), 2);
    assert.equal(h.redo(2), 3);
    assert.equal(h.redo(3), null);
  });
  it("merges rapid edits of the same key into one step, not different keys", () => {
    const h = new History<number>();
    h.record(0, "line1", 0); h.record(1, "line1", 100); h.record(2, "line1", 200);
    h.record(3, "line2", 300);
    assert.equal(h.undo(4), 3);
    assert.equal(h.undo(3), 0);
    assert.equal(h.canUndo, false);
  });
  it("a new edit drops the redo branch; clear empties both", () => {
    const h = new History<number>();
    h.record(1, "a", 0);
    h.undo(2);
    assert.equal(h.canRedo, true);
    h.record(1, "a", 9000);
    assert.equal(h.canRedo, false);
    h.clear();
    assert.equal(h.canUndo, false);
  });
});
