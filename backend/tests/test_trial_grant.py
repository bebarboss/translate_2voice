"""แพ็กทดลองตอนล็อกอิน Google: ได้ครั้งเดียว และไม่ทับแพ็กที่ยังไม่หมดอายุ"""
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from app import accounts, consent
from app.config import settings


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_conn", None)
    monkeypatch.setattr(accounts, "using_postgres", lambda: False)
    monkeypatch.setattr(accounts, "promote_owner_media", lambda _uid: 0)
    monkeypatch.setattr(consent, "_ready", False)
    consent._status_cache.clear()
    monkeypatch.setattr(accounts, "settings", replace(
        settings, data_dir=tmp_path, db_backend="files", auth_enabled=True, billing_enabled=True))
    accounts._db().execute(
        "INSERT INTO users (id, email, name, pw_hash, created_at) VALUES ('u1', 'a@b.c', 'Ann', '', 0)")
    yield accounts
    if accounts._conn is not None:
        accounts._conn.close()
        accounts._conn = None


def _google(book, email="a@b.c", name="Ann"):
    book._verify_google = lambda _cred: {"email": email, "name": name, "email_verified": True}


def _sub_row(book, uid="u1"):
    return book._db().execute(
        "SELECT plan_id, minutes_left FROM subscriptions WHERE user_id = ?", (uid,)
    ).fetchone()


def _trial_ledger(book, uid="u1"):
    return book._db().execute(
        "SELECT kind, ref, minutes FROM ledger WHERE user_id = ? AND kind = 'trial'", (uid,)
    ).fetchall()


def test_new_user_gets_trial_once_on_login(book):
    _google(book, "new@example.com", "New")
    created = book.google_login("cred")
    uid = created["user"]["id"]
    sub = book.wallet(uid)["subscription"]
    assert sub["plan_id"] == "trial"
    assert sub["minutes_left"] == 2
    assert len(_trial_ledger(book, uid)) == 1


def test_second_login_does_not_add_trial_credits(book):
    _google(book)
    book.google_login("cred")
    assert book.wallet("u1")["subscription"]["minutes_left"] == 2
    book.google_login("cred")
    assert book.wallet("u1")["subscription"]["minutes_left"] == 2
    assert len(_trial_ledger(book)) == 1


def test_concurrent_claims_leave_one_trial_row(book):
    barrier = threading.Barrier(2)
    outcomes = []

    def claim():
        barrier.wait()
        try:
            book.claim_trial("u1")
            outcomes.append("ok")
        except book.AccountError as err:
            outcomes.append(err.status)

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("ok") == 1
    assert outcomes.count(409) == 1
    assert len(_trial_ledger(book)) == 1
    assert book.wallet("u1")["subscription"]["minutes_left"] == 2


def test_active_paid_plan_is_not_overwritten_on_login(book):
    book.grant_plan("u1", "starter", "ops@example.com")
    book._db().execute("UPDATE users SET credits = 500 WHERE id = 'u1'")
    before = book.wallet("u1")
    _google(book)
    book.google_login("cred")
    after = book.wallet("u1")
    assert after["subscription"]["plan_id"] == "starter"
    assert after["subscription"]["minutes_left"] == before["subscription"]["minutes_left"]
    assert after["credits"] == 5
    assert _trial_ledger(book) == []


def test_expired_paid_plan_still_receives_trial(book):
    book.grant_plan("u1", "starter", "ops@example.com")
    with book._tx() as db:
        db.execute(
            "UPDATE subscriptions SET minutes_left = 0, expires_at = ? WHERE user_id = ?",
            (time.time() - 5, "u1"))
    _google(book)
    book.google_login("cred")
    sub = book.wallet("u1")["subscription"]
    assert sub["plan_id"] == "trial"
    assert sub["minutes_left"] == 2
    assert len(_trial_ledger(book)) == 1


def test_expired_trial_is_not_granted_again(book):
    book.claim_trial("u1")
    with book._tx() as db:
        db.execute(
            "UPDATE subscriptions SET expires_at = ? WHERE user_id = ?",
            (time.time() - 10, "u1"))
    with pytest.raises(book.AccountError) as err:
        book.claim_trial("u1")
    assert err.value.status == 409
    row = _sub_row(book)
    assert row["plan_id"] == "trial"
    assert row["minutes_left"] == 200
    assert len(_trial_ledger(book)) == 1


def test_admin_does_not_receive_trial(book):
    book._db().execute("UPDATE users SET admin = 1 WHERE id = 'u1'")
    with pytest.raises(book.AccountError) as err:
        book.claim_trial("u1")
    assert err.value.status == 400
    _google(book)
    book.google_login("cred")
    assert _sub_row(book) is None
    assert _trial_ledger(book) == []


def test_grant_plan_trial_is_once_unless_forced(book):
    book.grant_plan("u1", "trial", "ops@example.com")
    assert _sub_row(book)["minutes_left"] == 200
    with pytest.raises(book.AccountError) as err:
        book.grant_plan("u1", "trial", "ops@example.com")
    assert err.value.status == 409
    assert _sub_row(book)["minutes_left"] == 200
    book.grant_plan("u1", "trial", "ops@example.com", force=True)
    # ทบได้ 1 รอบของแพ็กทดลอง (2 เครดิต) จากยอดที่ยังเหลือ
    assert _sub_row(book)["minutes_left"] == 400


def test_unique_index_rejects_a_second_trial_row_and_rolls_back(book, monkeypatch):
    book.claim_trial("u1")
    before = _sub_row(book)["minutes_left"]
    monkeypatch.setattr(book, "_trial_taken", lambda _db, _uid: False)
    with pytest.raises(book.AccountError) as err:
        book.claim_trial("u1")
    assert err.value.status == 409
    assert _sub_row(book)["minutes_left"] == before
    assert len(_trial_ledger(book)) == 1
    with pytest.raises(sqlite3.IntegrityError):
        book._db().execute(
            "INSERT INTO ledger (user_id, kind, note, created_at) VALUES ('u1', 'trial', 'dup', ?)",
            (time.time(),))


def test_duplicate_trial_rows_are_kept_and_skip_the_index(tmp_path):
    db = sqlite3.connect(tmp_path / "dup.db")
    db.row_factory = sqlite3.Row
    db.executescript(accounts.SCHEMA)
    db.execute("INSERT INTO ledger (user_id, kind, note, created_at) VALUES ('u', 'trial', 'a', 1)")
    db.execute("INSERT INTO ledger (user_id, kind, note, created_at) VALUES ('u', 'trial', 'b', 2)")
    accounts._ensure_trial_once_index(db)
    assert db.execute("SELECT COUNT(*) FROM ledger WHERE kind = 'trial'").fetchone()[0] == 2
    names = [row[1] for row in db.execute("PRAGMA index_list('ledger')")]
    assert "ledger_trial_once" not in names
    db.execute("DELETE FROM ledger WHERE note = 'b'")
    accounts._ensure_trial_once_index(db)
    names = [row[1] for row in db.execute("PRAGMA index_list('ledger')")]
    assert "ledger_trial_once" in names
    db.close()


def test_postgres_migration_does_not_delete_and_guards_duplicates():
    sql = Path(__file__).resolve().parents[1].joinpath(
        "supabase", "migrations", "20261112000000_ledger_trial_once.sql"
    ).read_text()
    folded = sql.lower()
    assert "create unique index" in folded
    assert "ledger_trial_once" in folded
    assert "having count(*) > 1" in folded
    assert "delete from" not in folded
    assert "update studio.ledger" not in folded
    init = Path(__file__).resolve().parents[2].joinpath(
        "deploy", "db", "init", "02_studio_accounts.sql"
    ).read_text().lower()
    assert "ledger_trial_once" in init
