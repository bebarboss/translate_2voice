"""คืนเครดิตต้องตรงรายการตัดของรอบที่ล้ม และกลับเข้าถังเดิม"""
from dataclasses import replace

import pytest

from app import accounts
from app.config import settings
from app.jobs import refund_ref_for_failure
from app.schemas import Job


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_conn", None)
    monkeypatch.setattr(accounts, "settings", replace(
        settings, data_dir=tmp_path, db_backend="files", auth_enabled=True, billing_enabled=True))
    accounts._db().execute(
        "INSERT INTO users (id, email, name, pw_hash, created_at) VALUES ('u1', 'a@b.c', 'Ann', 'x', 0)")
    yield accounts
    if accounts._conn is not None:
        accounts._conn.close()
        accounts._conn = None


def _snap(book, uid="u1"):
    with book._lock:
        db = book._db()
        user = db.execute("SELECT credits FROM users WHERE id = ?", (uid,)).fetchone()
        sub = db.execute("SELECT minutes_left FROM subscriptions WHERE user_id = ?", (uid,)).fetchone()
        rows = [dict(r) for r in db.execute(
            "SELECT kind, ref, credits, minutes FROM ledger WHERE user_id = ? ORDER BY id", (uid,)).fetchall()]
    return {
        "credits": user["credits"],
        "minutes_left": sub["minutes_left"] if sub else None,
        "rows": rows,
    }


def _refunds(snap, ref):
    return [r for r in snap["rows"] if r["kind"] == "refund" and r["ref"] == ref]


def _charge(snap, ref):
    return next(r for r in snap["rows"] if r["kind"] == "charge" and r["ref"] == ref)


def test_redub_failure_refunds_only_that_redub(book):
    book.claim_trial("u1")
    assert book.job_credits(30) == 50
    book.charge_job("u1", "job", 30)
    first = book.charge_redub("u1", "job", 1.0, 0)
    second = book.charge_redub("u1", "job", 2.0, 0)
    assert first["ref"] == "job:redub:1"
    assert second["ref"] == "job:redub:2"
    assert first["credits_units"] == 10
    assert second["credits_units"] == 20
    before = _snap(book)
    book.refund_job("u1", second["ref"])
    after = _snap(book)
    assert after["credits"] == 0
    assert after["minutes_left"] == before["minutes_left"] + 20
    assert _refunds(after, "job") == []
    assert _refunds(after, "job:redub:1") == []
    assert len(_refunds(after, "job:redub:2")) == 1
    assert _charge(after, "job")["minutes"] == _charge(before, "job")["minutes"]
    assert _charge(after, "job")["credits"] == 0
    assert _refunds(after, "job:redub:2")[0]["minutes"] == 20
    assert _refunds(after, "job:redub:2")[0]["credits"] == 0


def test_first_analysis_failure_refunds_original_charge(book):
    book.claim_trial("u1")
    assert book.job_credits(16.8) == 28
    book.charge_job("u1", "job", 16.8)
    charged = _snap(book)
    book.refund_job("u1", "job")
    restored = _snap(book)
    assert restored["credits"] == 0
    assert restored["minutes_left"] == charged["minutes_left"] + 28
    assert restored["minutes_left"] == 200
    assert len(_refunds(restored, "job")) == 1
    assert _refunds(restored, "job")[0]["minutes"] == 28
    assert _refunds(restored, "job")[0]["credits"] == 0


def test_refund_same_ref_twice_is_idempotent(book):
    book.claim_trial("u1")
    book.charge_job("u1", "job", 16.8)
    book.refund_job("u1", "job")
    once = _snap(book)
    book.refund_job("u1", "job")
    twice = _snap(book)
    assert twice["credits"] == once["credits"] == 0
    assert twice["minutes_left"] == once["minutes_left"]
    assert len(_refunds(twice, "job")) == 1


def test_failed_redub_does_not_refund_another_redub(book):
    book.claim_trial("u1")
    book.charge_job("u1", "job", 30)
    book.charge_redub("u1", "job", 1.0, 0)
    book.charge_redub("u1", "job", 2.0, 0)
    before = _snap(book)
    book.refund_job("u1", "job:redub:1")
    after = _snap(book)
    assert after["minutes_left"] == before["minutes_left"] + 10
    assert after["credits"] == 0
    assert _refunds(after, "job:redub:2") == []
    assert _charge(after, "job:redub:2")["minutes"] == -20
    assert len(_refunds(after, "job:redub:1")) == 1


def test_trial_only_refund_does_not_touch_topup_credits(book):
    """บัญชีทดลอง 2.00 ไม่เคยเติม สองงาน 0.28 และ 0.17 งานที่สองล้ม — เครดิตเติมต้องเป็น 0"""
    book.claim_trial("u1")
    assert book.job_credits(16.8) == 28  # 0.28 เครดิต
    assert book.job_credits(10.2) == 17  # 0.17 เครดิต
    book.charge_job("u1", "job-a", 16.8)
    book.charge_job("u1", "job-b", 10.2)
    charged = _snap(book)
    assert charged["minutes_left"] == 200 - 28 - 17
    assert charged["credits"] == 0
    book.refund_job("u1", "job-b")
    restored = _snap(book)
    assert restored["credits"] == 0
    assert restored["minutes_left"] == 200 - 28
    assert _charge(restored, "job-a")["minutes"] == -28
    assert _refunds(restored, "job-a") == []
    assert _refunds(restored, "job-b")[0]["credits"] == 0
    assert _refunds(restored, "job-b")[0]["minutes"] == 17


def test_expired_plan_does_not_move_minutes_into_topup(book):
    book.claim_trial("u1")
    book.charge_job("u1", "job-a", 16.8)
    book.charge_job("u1", "job-b", 10.2)
    with book._tx() as db:
        db.execute("UPDATE subscriptions SET expires_at = 1 WHERE user_id = ?", ("u1",))
    book.refund_job("u1", "job-b")
    snap = _snap(book)
    assert snap["credits"] == 0
    assert snap["minutes_left"] == 200 - 28 - 17
    assert _refunds(snap, "job-b")[0]["credits"] == 0
    assert _refunds(snap, "job-b")[0]["minutes"] == 0
    book.refund_job("u1", "job-b")
    again = _snap(book)
    assert again["credits"] == 0
    assert again["minutes_left"] == snap["minutes_left"]
    assert len(_refunds(again, "job-b")) == 1


def test_mixed_charge_refunds_each_bucket(book):
    book.claim_trial("u1")
    book.credit("u1", 1.0, note="test top-up")
    book.charge_job("u1", "job-a", 60)    # 1.00 จากแพ็ก
    book.charge_job("u1", "job-b", 120)   # ที่เหลือของแพ็ก 1.00 + เครดิตเติม 1.00
    charged = _snap(book)
    assert charged["minutes_left"] == 0
    assert charged["credits"] == 0
    assert _charge(charged, "job-b")["minutes"] == -100
    assert _charge(charged, "job-b")["credits"] == -100
    book.refund_job("u1", "job-b")
    restored = _snap(book)
    assert restored["minutes_left"] == 100
    assert restored["credits"] == 100
    assert _charge(restored, "job-a")["minutes"] == -100
    assert _refunds(restored, "job-a") == []


def test_failure_ref_is_the_run_that_failed():
    redub_n = Job(id="job", filename="a.mp4", owner="u1", billing_ref="job:redub:2")
    redub_m = Job(id="job", filename="a.mp4", owner="u1", billing_ref="job:redub:1")
    first = Job(id="job", filename="a.mp4", owner="u1")
    assert refund_ref_for_failure(redub_n, "synthesize") == "job:redub:2"
    assert refund_ref_for_failure(redub_m, "synthesize") == "job:redub:1"
    assert refund_ref_for_failure(first, "analyze") == "job"
    assert refund_ref_for_failure(first, "synthesize") is None
    assert refund_ref_for_failure(first, "render") is None
    assert refund_ref_for_failure(redub_n, "voice") is None
    assert refund_ref_for_failure(Job(id="job", filename="a.mp4", billing_ref="job:redub:2"), "synthesize") is None
