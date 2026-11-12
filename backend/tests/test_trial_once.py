"""แพ็กทดลองได้ครั้งเดียวต่อตัวตน Google แม้ปิดบัญชีแล้วสมัครใหม่ หรือเปลี่ยนอีเมล"""
import sqlite3

import pytest
from dataclasses import replace

from app import accounts
from app import consent
from app.config import settings


@pytest.fixture
def book(tmp_path, monkeypatch):
    if accounts._conn is not None:
        accounts._conn.close()
        accounts._conn = None
    accounts._session_cache.clear()
    consent._status_cache.clear()
    monkeypatch.setattr(accounts, "_conn", None)
    monkeypatch.setattr(accounts, "using_postgres", lambda: False)
    monkeypatch.setattr(accounts, "_trial_schema_ready", False)
    monkeypatch.setattr(consent, "_ready", False)
    monkeypatch.setattr(accounts, "settings", replace(
        settings, data_dir=tmp_path, db_backend="files", auth_enabled=True, billing_enabled=True,
        trial_claim_pepper="test-pepper", google_client_id="test-client", admin_emails=()))
    yield accounts
    accounts._session_cache.clear()
    if accounts._conn is not None:
        accounts._conn.close()
        accounts._conn = None


@pytest.fixture
def google(book, monkeypatch):
    holder = {}

    def fake(_credential):
        return holder["info"]

    monkeypatch.setattr(book, "_verify_google", fake)

    def login(email, sub, name="Ann"):
        holder["info"] = {"email": email, "email_verified": True, "name": name, "sub": sub}
        return book.google_login("token")

    return login


def _hashes(book):
    return book._db().execute("SELECT id_hash, kind FROM trial_claims ORDER BY kind").fetchall()


def _assert_no_raw_identity(book, *secrets):
    rows = _hashes(book)
    assert rows
    blob = " ".join(f"{r['id_hash']} {r['kind']}" for r in rows).lower()
    for secret in secrets:
        assert secret.lower() not in blob
    for row in rows:
        assert row["kind"] in ("email", "sub")
        assert len(row["id_hash"]) == 64
        int(row["id_hash"], 16)


def test_normalize_email_collapses_gmail_only():
    assert accounts._normalize_email("A.B+News@gmail.com") == "ab@gmail.com"
    assert accounts._normalize_email("a.b@googlemail.com") == "ab@gmail.com"
    assert accounts._normalize_email("a.b@outlook.com") == "a.b@outlook.com"
    assert accounts._normalize_email("closed-1@deleted.invalid") == ""


def test_new_google_user_gets_trial_on_login(book, google):
    """ผู้ใช้ใหม่ได้แพ็กทดลองตอนล็อกอิน และกดรับซ้ำไม่ได้"""
    out = google("new@b.co", "sub-new")
    uid = out["user"]["id"]
    sub = book.wallet(uid)["subscription"]
    assert sub["plan_id"] == "trial"
    assert sub["minutes_left"] == 2
    with pytest.raises(book.AccountError) as err:
        book.claim_trial(uid)
    assert err.value.status == 409
    stored = book._db().execute("SELECT google_sub FROM users WHERE id = ?", (uid,)).fetchone()
    assert stored["google_sub"] == "sub-new"
    assert {r["kind"] for r in _hashes(book)} == {"email", "sub"}
    _assert_no_raw_identity(book, "new@b.co", "sub-new")


def test_close_and_signup_again_does_not_grant_another_trial(book, google):
    first = google("person@b.co", "sub-person")
    uid = first["user"]["id"]
    assert book.wallet(uid)["subscription"]["plan_id"] == "trial"
    book.close_account(uid)
    closed = book._db().execute(
        "SELECT email, google_sub, name, phone, full_name FROM users WHERE id = ?", (uid,)).fetchone()
    assert closed["email"] == f"closed-{uid}@deleted.invalid"
    assert closed["google_sub"] is None
    assert closed["name"] == "บัญชีที่ปิดแล้ว"
    assert closed["phone"] == ""
    assert closed["full_name"] == ""
    second = google("person@b.co", "sub-person")
    assert second["user"]["id"] != uid
    wallet = book.wallet(second["user"]["id"])
    assert wallet["subscription"] is None
    assert wallet["credits"] == 0
    assert wallet["entitlements"]["trial_available"] is False
    assert book.trial_claimed(second["user"]["id"])
    with pytest.raises(book.AccountError) as err:
        book.claim_trial(second["user"]["id"])
    assert err.value.status == 409
    _assert_no_raw_identity(book, "person@b.co", "sub-person")


def test_email_change_same_sub_does_not_grant_another_trial(book, google):
    first = google("old@b.co", "sub-1")
    uid = first["user"]["id"]
    minutes = book.wallet(uid)["subscription"]["minutes_left"]
    second = google("new@b.co", "sub-1")
    assert second["user"]["id"] == uid
    assert second["user"]["email"] == "new@b.co"
    # จุดที่ auto-claim จะเรียก claim_trial หลังล็อกอิน ต้องไม่ให้ซ้ำ
    with pytest.raises(book.AccountError) as err:
        book.claim_trial(uid)
    assert err.value.status == 409
    assert book.wallet(uid)["subscription"]["minutes_left"] == minutes
    assert book.wallet(uid)["subscription"]["plan_id"] == "trial"
    count = book._db().execute("SELECT COUNT(*) AS n FROM ledger WHERE kind = 'trial'").fetchone()["n"]
    assert count == 1
    stored = book._db().execute("SELECT google_sub FROM users WHERE id = ?", (uid,)).fetchone()
    assert stored["google_sub"] == "sub-1"


def test_gmail_alias_after_close_does_not_get_a_second_trial(book, google):
    first = google("a.b+news@gmail.com", "sub-g")
    assert book.wallet(first["user"]["id"])["subscription"]["plan_id"] == "trial"
    book.close_account(first["user"]["id"])
    second = google("ab@gmail.com", "sub-other")
    assert second["user"]["id"] != first["user"]["id"]
    assert book.wallet(second["user"]["id"])["subscription"] is None
    with pytest.raises(book.AccountError) as err:
        book.claim_trial(second["user"]["id"])
    assert err.value.status == 409


def test_close_before_any_trial_can_still_claim_once(book, google):
    book._db().execute(
        "INSERT INTO users (id, email, name, pw_hash, created_at) VALUES ('plain', 'plain@b.co', 'Plain', '', 0)")
    book.close_account("plain")
    out = google("plain@b.co", "sub-plain")
    assert out["user"]["id"] != "plain"
    assert book.wallet(out["user"]["id"])["subscription"]["plan_id"] == "trial"
    assert book.wallet(out["user"]["id"])["subscription"]["minutes_left"] == 2
    with pytest.raises(book.AccountError) as err:
        book.claim_trial(out["user"]["id"])
    assert err.value.status == 409


def test_two_people_each_get_a_trial(book, google):
    first = google("a@b.co", "sub-a")
    second = google("b@b.co", "sub-b")
    assert first["user"]["id"] != second["user"]["id"]
    assert book.wallet(first["user"]["id"])["subscription"]["plan_id"] == "trial"
    assert book.wallet(second["user"]["id"])["subscription"]["plan_id"] == "trial"


def test_different_sub_cannot_take_over_an_email(book, google):
    first = google("a@b.co", "sub-a")
    with pytest.raises(book.AccountError) as err:
        google("a@b.co", "sub-b")
    assert err.value.status == 409
    stored = book._db().execute(
        "SELECT google_sub FROM users WHERE id = ?", (first["user"]["id"],)).fetchone()
    assert stored["google_sub"] == "sub-a"


def test_existing_user_without_sub_backfills_and_cannot_reclaim(book, google, tmp_path):
    """ฐานเก่าไม่มีคอลัมน์ google_sub และผู้ใช้ที่รับทดลองไปแล้วได้ sub ตอนล็อกอินครั้งถัดไป"""
    if book._conn is not None:
        book._conn.close()
        book._conn = None
    path = tmp_path / "accounts.db"
    raw = sqlite3.connect(path)
    raw.execute(
        "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, "
        "pw_hash TEXT NOT NULL, balance INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL)")
    raw.execute(
        "INSERT INTO users (id, email, name, pw_hash, created_at) VALUES ('legacy', 'old@b.co', 'Old', '', 0)")
    raw.commit()
    raw.close()
    book.claim_trial("legacy")
    stored = book._db().execute("SELECT google_sub FROM users WHERE id = 'legacy'").fetchone()
    assert stored["google_sub"] is None
    out = google("old@b.co", "sub-legacy")
    assert out["user"]["id"] == "legacy"
    stored = book._db().execute("SELECT google_sub FROM users WHERE id = 'legacy'").fetchone()
    assert stored["google_sub"] == "sub-legacy"
    with pytest.raises(book.AccountError) as err:
        book.claim_trial("legacy")
    assert err.value.status == 409
    book.close_account("legacy")
    again = google("new-mail@b.co", "sub-legacy")
    assert again["user"]["id"] != "legacy"
    assert book.wallet(again["user"]["id"])["subscription"] is None
