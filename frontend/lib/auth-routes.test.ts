import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { authGate, isProtectedPath, safeNext, signInPath } from "./auth-routes.ts";

describe("isProtectedPath", () => {
  it("protects studio pages and leaves public pages alone", () => {
    for (const path of ["/", "/dashboard", "/jobs", "/jobs/abc", "/projects", "/projects/p1", "/voices", "/voices/v1", "/timeline", "/admin", "/admin/extra", "/account", "/settings", "/support", "/actor", "/actors", "/onboarding"]) {
      assert.equal(isProtectedPath(path), true, path);
    }
    for (const path of ["/welcome", "/login", "/terms", "/privacy", "/actor-consent", "/share", "/share/tok", "/promotions", "/this-page-does-not-exist"]) {
      assert.equal(isProtectedPath(path), false, path);
    }
  });

  it("does not treat the actor consent page as the apply page", () => {
    assert.equal(isProtectedPath("/actor-consent"), false);
    assert.equal(isProtectedPath("/actors"), true);
  });
});

describe("signInPath", () => {
  it("preserves the destination for Google sign-in", () => {
    assert.equal(signInPath("/dashboard"), "/login?next=%2Fdashboard");
    assert.equal(signInPath("/jobs", "?q=1"), "/login?next=%2Fjobs%3Fq%3D1");
  });

  it("opens signup when the visitor came for the actor application", () => {
    assert.equal(signInPath("/actor"), "/login?mode=signup&next=%2Factor");
  });

  it("rejects off-site next values", () => {
    assert.equal(safeNext("//evil.example"), "/dashboard");
    assert.equal(safeNext("https://evil.example"), "/dashboard");
    assert.equal(signInPath("//evil.example"), "/login?next=%2Fdashboard");
  });
});

describe("authGate", () => {
  it("redirects anonymous visitors of protected pages to login", () => {
    assert.deepEqual(authGate("/dashboard", "", { authOn: true, hasSession: false }), {
      action: "redirect",
      location: "/login?next=%2Fdashboard",
    });
    assert.deepEqual(authGate("/jobs", "?q=1", { authOn: true, hasSession: false }), {
      action: "redirect",
      location: "/login?next=%2Fjobs%3Fq%3D1",
    });
    assert.deepEqual(authGate("/actor", "", { authOn: true, hasSession: false }), {
      action: "redirect",
      location: "/login?mode=signup&next=%2Factor",
    });
    assert.deepEqual(authGate("/admin", "", { authOn: true, hasSession: false }), {
      action: "redirect",
      location: "/login?next=%2Fadmin",
    });
  });

  it("sends anonymous visitors and crawlers from / to the public landing page", () => {
    // ไม่มีคุกกี้ session คือทั้งผู้เยี่ยมชมและ Googlebot — ไม่ดู User-Agent
    assert.deepEqual(authGate("/", "", { authOn: true, hasSession: false }), {
      action: "redirect",
      location: "/welcome",
    });
    assert.deepEqual(authGate("/", "?utm=google", { authOn: true, hasSession: false }), {
      action: "redirect",
      location: "/welcome",
    });
  });

  it("lets signed-in users through and skips the gate when auth is off", () => {
    assert.deepEqual(authGate("/", "", { authOn: true, hasSession: true }), { action: "next" });
    assert.deepEqual(authGate("/", "?project=p1", { authOn: true, hasSession: true }), { action: "next" });
    assert.deepEqual(authGate("/jobs", "", { authOn: true, hasSession: true }), { action: "next" });
    assert.deepEqual(authGate("/dashboard", "", { authOn: false, hasSession: false }), { action: "next" });
    assert.deepEqual(authGate("/", "", { authOn: false, hasSession: false }), { action: "next" });
  });

  it("does not send unknown or public routes to login", () => {
    assert.deepEqual(authGate("/this-page-does-not-exist", "", { authOn: true, hasSession: false }), { action: "next" });
    assert.deepEqual(authGate("/welcome", "", { authOn: true, hasSession: false }), { action: "next" });
    assert.deepEqual(authGate("/promotions", "", { authOn: true, hasSession: false }), { action: "next" });
    assert.deepEqual(authGate("/terms", "", { authOn: true, hasSession: false }), { action: "next" });
  });

  it("sends non-admins away from /admin without rendering it", () => {
    assert.deepEqual(authGate("/admin", "", { authOn: true, hasSession: true, admin: "no" }), {
      action: "redirect",
      location: "/dashboard",
    });
    assert.deepEqual(authGate("/admin", "", { authOn: true, hasSession: true, admin: "anon" }), {
      action: "redirect",
      location: "/login?next=%2Fadmin",
    });
    assert.deepEqual(authGate("/admin", "", { authOn: true, hasSession: true, admin: "admin" }), { action: "next" });
    assert.deepEqual(authGate("/admin", "", { authOn: true, hasSession: true, admin: "unknown" }), { action: "next" });
  });
});
