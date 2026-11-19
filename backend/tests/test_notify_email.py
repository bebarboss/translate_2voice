"""คิวอีเมล การตั้งค่า และการยกเลิกการรับ ใช้ SMTP ปลอมในโปรเซส ไม่ต่อเน็ต"""
import base64
import json
import logging
import smtplib
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import accounts, consent, inbox, notify, outbox
from app.config import settings

SECRET_UID = "user-9f3c2a"
SECRET_EMAIL = "notify-secret-user@example.com"
PASSWORD = "super-secret-key"


class FakeSMTP:
    """เลียนแบบลำดับคำสั่ง: has_extn('starttls') เป็นเท็จจนกว่าจะ EHLO"""

    instances: list["FakeSMTP"] = []
    advertise_tls = True
    fail: BaseException | None = None

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.commands: list[str] = []
        self.messages = []
        self._ehlo = False
        self._tls = False
        self.kind = "plain"
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def ehlo(self):
        self.commands.append("EHLO")
        self._ehlo = True

    def has_extn(self, name):
        if str(name).lower() == "starttls":
            return bool(self.advertise_tls and self._ehlo and not self._tls)
        return False

    def starttls(self, context=None):
        self.commands.append("STARTTLS")
        self._tls = True
        self._ehlo = False

    def login(self, user, password):
        self.commands.append("AUTH")
        self.user = user
        self.password = password

    def send_message(self, msg):
        self.commands.append("DATA")
        if FakeSMTP.fail is not None:
            raise FakeSMTP.fail
        self.messages.append(msg)


class FakeSMTPSSL(FakeSMTP):
    def __init__(self, host, port, timeout=None, context=None):
        super().__init__(host, port, timeout=timeout, context=context)
        self.kind = "ssl"


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + pad).encode())


@pytest.fixture
def book(tmp_path, monkeypatch):
    FakeSMTP.instances = []
    FakeSMTP.advertise_tls = True
    FakeSMTP.fail = None
    monkeypatch.setattr(accounts, "_conn", None)
    monkeypatch.setattr(inbox, "_ready", False)
    monkeypatch.setattr(consent, "_ready", False)
    consent._status_cache.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTPSSL)
    local = replace(
        settings,
        data_dir=tmp_path,
        db_backend="files",
        auth_enabled=True,
        billing_enabled=True,
        smtp_host="smtp.example.test",
        smtp_port=587,
        smtp_user="resend",
        smtp_password=PASSWORD,
        mail_from="noreply@example.com",
        web_url="https://app.example.test",
        api_url="https://api.example.test",
        unsubscribe_secret="test-unsubscribe-secret",
        notify_min_seconds=120,
    )
    monkeypatch.setattr(accounts, "settings", local)
    monkeypatch.setattr("app.config.settings", local)
    db = accounts._db()
    db.execute(
        "INSERT INTO users (id, email, name, pw_hash, created_at) VALUES (?, ?, 'นารี', 'x', 0)",
        (SECRET_UID, SECRET_EMAIL),
    )
    db.execute(
        "INSERT INTO users (id, email, name, pw_hash, created_at) VALUES ('u1', 'person@example.com', 'นารี', 'x', 0)"
    )
    yield accounts
    if accounts._conn is not None:
        accounts._conn.close()
        accounts._conn = None


def _prefs(uid=SECRET_UID):
    with accounts._lock:
        db = accounts._db()
        row = db.execute(
            "SELECT notify_email, notify_prefs, credits_low_armed FROM users WHERE id = ?", (uid,)
        ).fetchone()
    return {
        "notify_email": row["notify_email"],
        "notify_prefs": row["notify_prefs"],
        "credits_low_armed": row["credits_low_armed"],
    }


def _outbox(uid=None):
    with accounts._tx() as db:
        outbox._ensure(db)
        if uid is None:
            rows = db.execute("SELECT * FROM notification_outbox ORDER BY created_at, id").fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM notification_outbox WHERE user_id = ? ORDER BY created_at, id", (uid,)
            ).fetchall()
    return [dict(r) for r in rows]


def _due(row_id):
    with accounts._tx() as db:
        db.execute("UPDATE notification_outbox SET next_attempt_at = 0 WHERE id = ?", (row_id,))


def _client():
    app = FastAPI()
    from app import account_api
    app.include_router(account_api.router)
    app.include_router(notify.public_router)
    app.dependency_overrides[account_api.require_user] = lambda: {"id": SECRET_UID}
    return TestClient(app)


def _no_identity(text: str):
    assert SECRET_EMAIL not in text
    assert SECRET_UID not in text


def test_enqueue_then_pump_sends_once_and_orders_starttls(book):
    notify.send(
        "person@example.com", "สวัสดี", ["บรรทัด"], "/jobs/j1", "เปิดดู",
        kind="job_done", user_id="u1", dedupe_key="u1:job_done:j1",
    )
    assert len(_outbox()) == 1 and _outbox()[0]["status"] == "pending"
    assert outbox.pump() == 1
    assert len(FakeSMTP.instances) == 1
    assert FakeSMTP.instances[0].commands == ["EHLO", "STARTTLS", "EHLO", "AUTH", "DATA"]
    assert len(FakeSMTP.instances[0].messages) == 1
    assert _outbox()[0]["status"] == "sent"
    assert "พากย์ดี" in FakeSMTP.instances[0].messages[0]["From"]


def test_port_465_uses_ssl_without_starttls(book, monkeypatch):
    monkeypatch.setattr("app.config.settings", replace(accounts.settings, smtp_port=465))
    notify.send("person@example.com", "สวัสดี", ["บรรทัด"], kind="actor_paid", user_id="u1", dedupe_key="ssl")
    outbox.pump()
    assert FakeSMTP.instances[0].kind == "ssl"
    assert FakeSMTP.instances[0].commands == ["AUTH", "DATA"]


def test_missing_starttls_is_dead_and_does_not_auth(book):
    FakeSMTP.advertise_tls = False
    notify.send("person@example.com", "สวัสดี", ["บรรทัด"], kind="actor_paid", user_id="u1", dedupe_key="notls")
    outbox.pump()
    assert FakeSMTP.instances[0].commands == ["EHLO"]
    assert "AUTH" not in FakeSMTP.instances[0].commands
    row = _outbox()[0]
    assert row["status"] == "dead"
    assert "STARTTLS" in row["last_error"]
    assert PASSWORD not in row["last_error"]


def test_smtp_5xx_is_dead_immediately(book):
    FakeSMTP.fail = smtplib.SMTPResponseException(550, b"no such user")
    notify.send("person@example.com", "สวัสดี", ["บรรทัด"], kind="actor_paid", user_id="u1", dedupe_key="dead")
    outbox.pump()
    assert _outbox()[0]["status"] == "dead"
    assert _outbox()[0]["attempts"] == 1


def test_backoff_then_dead_on_fifth_and_password_is_redacted(book, caplog):
    FakeSMTP.fail = RuntimeError(f"auth failed {PASSWORD}")
    caplog.set_level(logging.INFO, logger="dubbing.notify")
    notify.send("person@example.com", "สวัสดี", ["บรรทัด"], kind="actor_paid", user_id="u1", dedupe_key="retry")
    expected = (60, 300, 1800, 7200)
    for delay in expected:
        before = time.time()
        outbox.pump()
        row = _outbox()[0]
        assert row["status"] == "pending"
        assert abs((row["next_attempt_at"] - before) - delay) < 5
        assert PASSWORD not in row["last_error"]
        _due(row["id"])
    outbox.pump()
    assert _outbox()[0]["status"] == "dead"
    assert _outbox()[0]["attempts"] == outbox.MAX_ATTEMPTS
    assert PASSWORD not in caplog.text


def test_stuck_sending_is_reclaimed_then_sent(book):
    now = time.time()
    with accounts._tx() as db:
        outbox._ensure(db)
        db.execute(
            "INSERT INTO notification_outbox ("
            "id, user_id, to_email, kind, subject, text_body, html_body, headers, status, attempts, "
            "next_attempt_at, last_error, created_at, sent_at, dedupe_key"
            ") VALUES ('stuck', 'u1', 'person@example.com', 'actor_paid', 'เรื่อง', 'ข้อความ', '<p>x</p>', "
            "'{}', 'sending', 2, ?, '', ?, NULL, 'stuck-key')",
            (now - 1, now),
        )
    assert outbox.pump() == 1
    assert _outbox()[0]["status"] == "sent"
    assert _outbox()[0]["attempts"] == 3
    assert len(FakeSMTP.instances[0].messages) == 1


def test_two_workers_claim_one_row(book):
    notify.send("person@example.com", "สวัสดี", ["บรรทัด"], kind="actor_paid", user_id="u1", dedupe_key="once")
    barrier = threading.Barrier(2)
    found = []

    def grab():
        barrier.wait(timeout=5)
        found.append(outbox.claim_due(1))

    threads = [threading.Thread(target=grab) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    claimed = [row for batch in found for row in batch]
    assert len(claimed) == 1
    for row in claimed:
        outbox.deliver_one(row)
    assert len(FakeSMTP.instances) == 1
    assert sum(len(s.messages) for s in FakeSMTP.instances) == 1
    assert "FOR UPDATE SKIP LOCKED" in outbox.PG_CLAIM


def test_duplicate_job_notice_sends_one_email(book):
    job = SimpleNamespace(filename="clip.mp4", library=False, timeline=False, error="boom")
    user = accounts.user_by_id("u1")
    notify.deliver_job_notice(user, job, "job-1", "done", 500)
    notify.deliver_job_notice(user, job, "job-1", "done", 500)
    rows = _outbox("u1")
    assert len(rows) == 1
    assert rows[0]["dedupe_key"] == "u1:job_done:job-1"
    assert "ดูผลงาน" in rows[0]["html_body"]


def test_header_injection_is_stripped_and_enqueue_never_raises(book, monkeypatch):
    notify.send(
        "person@example.com\r\n",
        "สวัสดี\r\nBcc: evil@example.com",
        ["บรรทัด\r\nX-Injected: yes"],
        kind="actor_paid", user_id="u1", dedupe_key="inject",
    )
    row = _outbox()[0]
    assert "\r" not in row["subject"] and "\n" not in row["subject"]
    assert "\r" not in row["text_body"] and "\nX-Injected" not in row["text_body"]
    outbox.pump()
    raw = FakeSMTP.instances[0].messages[0].as_string()
    assert "\nBcc:" not in raw and "\r" not in raw

    def boom(*_a, **_k):
        raise RuntimeError("disk")

    monkeypatch.setattr(outbox, "enqueue", boom)
    notify.send("person@example.com", "อีกเรื่อง\nBcc: x", ["x"], kind="actor_paid", user_id="u1", dedupe_key="x")


def test_unconfigured_smtp_logs_masked_address_and_does_not_enqueue(book, monkeypatch, caplog):
    monkeypatch.setattr("app.config.settings", replace(accounts.settings, smtp_host="", mail_from=""))
    caplog.set_level(logging.INFO, logger="dubbing.notify")
    notify.send("person@example.com", "สวัสดี", ["บรรทัด"], kind="actor_paid", user_id="u1", dedupe_key="noconfig")
    assert _outbox() == []
    assert "p***@example.com" in caplog.text
    assert "person@example.com" not in caplog.text


def test_template_escapes_filename_and_uses_ink_button(book):
    job = SimpleNamespace(filename="<b>คลิป</b>\r\n", library=False, timeline=False, error="internal boom")
    notify.deliver_job_notice(accounts.user_by_id("u1"), job, "job-9", "failed", 1)
    row = _outbox("u1")[0]
    html = row["html_body"]
    assert "max-width:600px" in html
    assert "background:#141414" in html and "color:#ffffff" in html
    assert "#FF8A4C" not in html and "#ff8a4c" not in html.lower()
    assert "&lt;b&gt;" in html and "<b>" not in html
    assert "internal boom" not in html and "internal boom" not in row["text_body"]
    assert "งานไม่สำเร็จ" in row["subject"]
    assert "เปิดงาน" in html
    assert "ทำไม่สำเร็จ" in row["text_body"]
    assert "https://app.example.test/jobs/job-9" in html
    assert "https://app.example.test/account?tab=prefs" in html
    assert "https://app.example.test/unsubscribe?token=" in html
    headers = json.loads(row["headers"])
    assert headers["List-Unsubscribe"].startswith("<https://api.example.test/notifications/unsubscribe?token=")
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert SECRET_EMAIL not in html and SECRET_EMAIL not in row["text_body"]
    assert "person@example.com" not in html
    for blob in (html, row["text_body"], headers["List-Unsubscribe"]):
        assert "@" not in blob.split("unsubscribe", 1)[-1]


def test_always_on_has_settings_only_and_empty_api_omits_header(book, monkeypatch):
    accounts.set_notify("u1", False)
    notify.actor_paid("u1", "2026-11", 15000, 500)
    row = _outbox("u1")[0]
    assert row["kind"] == "actor_paid"
    assert "account?tab=prefs" in row["html_body"]
    assert "unsubscribe" not in row["html_body"]
    assert "ยกเลิกการรับ" not in row["html_body"]
    assert json.loads(row["headers"]) == {}

    monkeypatch.setattr("app.config.settings", replace(accounts.settings, api_url=""))
    notify.send(
        "person@example.com", "รอตรวจบท: a.mp4", ["สวัสดี"], "/jobs/j", "ตรวจบท",
        kind="job_review", user_id="u1", dedupe_key="u1:job_review:j",
    )
    # สวิตช์ทั้งกลุ่มปิดอยู่ งานที่ตั้งค่าได้ไม่เข้าคิว
    assert len(_outbox("u1")) == 1
    accounts.set_notify("u1", True)
    notify.send(
        "person@example.com", "รอตรวจบท: a.mp4", ["สวัสดี"], "/jobs/j", "ตรวจบท",
        kind="job_review", user_id="u1", dedupe_key="u1:job_review:j2",
    )
    review = _outbox("u1")[-1]
    assert "unsubscribe?token=" in review["html_body"]
    assert json.loads(review["headers"]) == {}


def test_notify_prefs_master_keeps_stored_map(book):
    client = _client()
    denied = client.put("/auth/notify-prefs", json={"nope": True})
    assert denied.status_code == 422
    assert client.put("/auth/notify-prefs", json={"job_done": None}).status_code == 422

    updated = client.put("/auth/notify-prefs", json={"job_review": False})
    assert updated.status_code == 200
    body = updated.json()
    assert body["email"]["job_review"] is False
    assert body["email"]["job_done"] is True
    assert body["email"]["job_failed"] is True
    assert body["email"]["credits_low"] is True
    assert "actor_paid" in body["always_on"]
    stored = client.get("/auth/notify-prefs").json()["email"]
    column = _prefs()["notify_prefs"]

    off = client.put("/auth/notify", json={"on": False})
    assert off.status_code == 200 and off.json()["notify_email"] is False
    assert client.get("/auth/notify-prefs").json()["email"] == stored
    assert _prefs()["notify_prefs"] == column and _prefs()["notify_email"] == 0

    notify.deliver_job_notice(
        accounts.user_by_id(SECRET_UID),
        SimpleNamespace(filename="a.mp4", library=False, timeline=False, error=""),
        "j-done", "done", 500,
    )
    notify.credits_low(SECRET_UID, 90)
    notify.actor_paid(SECRET_UID, "2026-11", 10000, 0)
    kinds = [r["kind"] for r in _outbox(SECRET_UID)]
    assert kinds == ["actor_paid"]
    assert any(i["kind"] == "credits_low" for i in inbox.list_for(SECRET_UID)["items"])

    on = client.put("/auth/notify", json={"on": True})
    assert on.json()["notify_email"] is True
    assert client.get("/auth/notify-prefs").json()["email"]["job_review"] is False
    notify.deliver_job_notice(
        accounts.user_by_id(SECRET_UID),
        SimpleNamespace(filename="a.mp4", library=True, timeline=False, error=""),
        "j-review", "review", 500,
    )
    notify.deliver_job_notice(
        accounts.user_by_id(SECRET_UID),
        SimpleNamespace(filename="a.mp4", library=False, timeline=True, error=""),
        "j-done-2", "done", 500,
    )
    kinds = [r["kind"] for r in _outbox(SECRET_UID)]
    assert "job_review" not in kinds and "job_done" in kinds
    review_off = client.get("/auth/notify-prefs").json()["email"]
    assert review_off["job_review"] is False and review_off["job_done"] is True
    me = accounts.user_by_id(SECRET_UID)
    assert me["notify_email"] == 1


def test_unsubscribe_get_is_readonly_and_responses_omit_identity(book):
    token = notify.make_token(SECRET_UID, "credits_low")
    payload = _b64d(token.split(".", 1)[0])
    assert SECRET_UID.encode() in payload
    assert b"credits_low" in payload
    exp = int(payload.split(b"|")[2])
    assert abs(exp - (time.time() + notify.TOKEN_TTL)) < 5
    assert SECRET_EMAIL not in token
    assert SECRET_EMAIL.encode() not in payload

    before = _prefs()
    client = _client()
    for _ in range(3):
        response = client.get("/notifications/unsubscribe", params={"token": token})
        assert response.status_code == 200
        assert response.json() == {"category": "credits_low"}
        _no_identity(response.text)
    assert _prefs() == before

    form = client.post(
        "/notifications/unsubscribe",
        params={"token": token},
        data={"List-Unsubscribe": "One-Click"},
    )
    assert form.status_code == 200
    assert form.json() == {"ok": True, "category": "credits_low"}
    _no_identity(form.text)
    again = client.post("/notifications/unsubscribe", json={"token": token})
    assert again.status_code == 200 and again.json() == {"ok": True, "category": "credits_low"}
    _no_identity(again.text)
    after = accounts.notify_prefs_public(SECRET_UID)["email"]
    assert after["credits_low"] is False
    assert after["job_done"] is True and after["job_review"] is True and after["job_failed"] is True
    assert accounts.user_by_id(SECRET_UID)["notify_email"] == 1

    still = client.get("/notifications/unsubscribe", params={"token": token})
    assert still.status_code == 200 and still.json() == {"category": "credits_low"}
    assert accounts.notify_prefs_public(SECRET_UID)["email"]["credits_low"] is False


def test_unsubscribe_400_and_410_do_not_leak_or_change_prefs(book):
    client = _client()
    before = _prefs()
    expired = notify.sign_token(SECRET_UID, "job_done", int(time.time()) - 10)
    gone = client.get("/notifications/unsubscribe", params={"token": expired})
    assert gone.status_code == 410
    _no_identity(gone.text)
    posted = client.post("/notifications/unsubscribe", json={"token": expired})
    assert posted.status_code == 410
    _no_identity(posted.text)

    tampered = expired[:-2] + ("A" if expired[-2:] != "AA" else "B")
    bad = client.post("/notifications/unsubscribe", params={"token": tampered})
    assert bad.status_code == 400
    _no_identity(bad.text)
    assert client.get("/notifications/unsubscribe", params={"token": "not-a-token"}).status_code == 400
    wrong = notify.sign_token(SECRET_UID, "actor_paid", int(time.time()) + 3600)
    wrong_old = notify.sign_token(SECRET_UID, "actor_paid", int(time.time()) - 10)
    assert client.get("/notifications/unsubscribe", params={"token": wrong}).status_code == 400
    assert client.post("/notifications/unsubscribe", json={"token": wrong_old}).status_code == 400
    mailed = client.post("/notifications/unsubscribe", json={"token": SECRET_EMAIL})
    assert mailed.status_code == 400
    _no_identity(mailed.text)
    named = client.get("/notifications/unsubscribe", params={"token": SECRET_UID})
    assert named.status_code == 400
    _no_identity(named.text)
    assert _prefs() == before


def test_empty_secret_omits_links(book, monkeypatch):
    monkeypatch.setattr("app.config.settings", replace(accounts.settings, unsubscribe_secret=""))
    assert notify.make_token(SECRET_UID, "job_done") == ""
    notify.send(
        "person@example.com", "พากย์เสร็จแล้ว: a.mp4", ["สวัสดี"], "/jobs/j", "ดูผลงาน",
        kind="job_done", user_id="u1", dedupe_key="u1:job_done:nosecret",
    )
    row = _outbox("u1")[0]
    assert "unsubscribe" not in row["html_body"]
    assert "account?tab=prefs" in row["html_body"]
    assert json.loads(row["headers"]) == {}
    assert _client().get("/notifications/unsubscribe", params={"token": "x"}).status_code == 400


def _plan(uid, minutes, credits):
    """แพ็ก starter คงอยู่เสมอ เพื่อให้ตรวจความยาวคลิปผ่าน แม้เครดิตแพ็กจะเป็น 0"""
    now = time.time()
    with accounts._tx() as db:
        db.execute("UPDATE users SET credits = ? WHERE id = ?", (credits, uid))
        db.execute("DELETE FROM subscriptions WHERE user_id = ?", (uid,))
        db.execute(
            "INSERT INTO subscriptions (user_id, plan_id, minutes_left, started_at, expires_at) "
            "VALUES (?, 'starter', ?, ?, ?)",
            (uid, minutes, now, now + 86400),
        )


def _ledger(uid):
    with accounts._lock:
        db = accounts._db()
        return [dict(r) for r in db.execute(
            "SELECT kind, credits, minutes FROM ledger WHERE user_id = ? AND kind = 'charge' ORDER BY id",
            (uid,),
        ).fetchall()]


def test_credits_low_uses_spendable_balance_and_rearms(book):
    _plan("u1", 100, 50)
    accounts.charge_job("u1", "job-a", 36)
    wallet = accounts.wallet("u1")
    assert wallet["credits"] + wallet["subscription"]["minutes_left"] == pytest.approx(0.90)
    rows = _outbox("u1")
    assert len(rows) == 1 and rows[0]["kind"] == "credits_low"
    assert "0.90" in rows[0]["text_body"]
    assert "0.50" not in rows[0]["text_body"] and "0.40" not in rows[0]["text_body"]
    assert "เติมเครดิต" in rows[0]["html_body"]
    assert "เครดิตใกล้หมดแล้ว" in rows[0]["subject"]
    item = next(i for i in inbox.list_for("u1")["items"] if i["kind"] == "credits_low")
    assert item["title"] == "เครดิตใกล้หมด"
    assert item["body"] == "ยอดที่ใช้ได้เหลือ 0.90 เครดิต เติมเพื่อส่งงานต่อได้"
    assert item["link"] == "/promotions"
    charge = _ledger("u1")[0]
    assert charge["minutes"] == -60 and charge["credits"] == 0
    assert _prefs("u1")["credits_low_armed"] == 0

    accounts.charge_job("u1", "job-b", 12)
    assert len(_outbox("u1")) == 1
    assert _ledger("u1")[1]["minutes"] == -20

    _plan("u1", 0, 200)
    accounts.charge_job("u1", "job-c", 12)
    assert len(_outbox("u1")) == 1
    assert _prefs("u1")["credits_low_armed"] == 1

    accounts.charge_job("u1", "job-d", 90)
    assert len(_outbox("u1")) == 2
    assert "0.30" in _outbox("u1")[-1]["text_body"]
    assert _prefs("u1")["credits_low_armed"] == 0


def test_credits_low_fires_when_one_charge_crosses_both_thresholds(book):
    _plan("u1", 0, 250)
    with accounts._tx() as db:
        db.execute("UPDATE users SET credits_low_armed = 0 WHERE id = ?", ("u1",))
    accounts.charge_job("u1", "job-cross", 150)
    assert _ledger("u1")[0]["credits"] == -250
    assert len(_outbox("u1")) == 1
    assert "0.00" in _outbox("u1")[0]["text_body"]


def test_credits_low_inbox_without_email_when_pref_or_master_off(book):
    _plan(SECRET_UID, 0, 50)
    accounts.update_notify_prefs(SECRET_UID, {"credits_low": False})
    accounts.charge_job(SECRET_UID, "job-pref", 30)
    assert _outbox(SECRET_UID) == []
    assert any(i["kind"] == "credits_low" for i in inbox.list_for(SECRET_UID)["items"])
    assert _ledger(SECRET_UID)[0]["credits"] == -50

    _plan("u1", 0, 50)
    accounts.set_notify("u1", False)
    accounts.charge_job("u1", "job-master", 30)
    assert _outbox("u1") == []
    assert any(i["kind"] == "credits_low" for i in inbox.list_for("u1")["items"])
    stored = accounts.notify_prefs_public("u1")["email"]["credits_low"]
    assert stored is True


def test_admin_charge_does_not_alert(book):
    with accounts._tx() as db:
        db.execute("UPDATE users SET admin = 1, credits = 50 WHERE id = ?", ("u1",))
    accounts.charge_job("u1", "job-admin", 36)
    assert accounts.user_by_id("u1")["credits"] == 50
    assert _outbox("u1") == []
    assert _ledger("u1") == []


def test_fast_success_skips_email_but_failed_does_not(book):
    user = accounts.user_by_id("u1")
    job = SimpleNamespace(filename="clip.mp4", library=False, timeline=False, error="secret-trace")
    notify.deliver_job_notice(user, job, "fast", "done", 1)
    assert _outbox("u1") == []
    assert inbox.list_for("u1")["items"][0]["kind"] == "job_done"
    notify.deliver_job_notice(user, job, "bad", "failed", 1)
    row = _outbox("u1")[0]
    assert row["kind"] == "job_failed"
    assert "secret-trace" not in row["text_body"] and "secret-trace" not in row["html_body"]


def test_invalid_session_cookie_does_not_401(book, monkeypatch):
    """แอปจริง: คุกกี้ dub_session และ X-User-Token ที่ใช้ไม่ได้ต้องไม่กลายเป็น 401/403"""
    import asyncio

    import httpx

    from app import main as main_mod

    secured = replace(accounts.settings, api_key="test-api-key")
    monkeypatch.setattr(accounts, "settings", secured)
    monkeypatch.setattr("app.config.settings", secured)
    monkeypatch.setattr(main_mod, "settings", secured)
    headers = {
        "cookie": "dub_session=not-a-real-session",
        "x-user-token": "not-a-real-session",
    }
    expired = notify.sign_token(SECRET_UID, "job_done", int(time.time()) - 30)
    before = _prefs()

    async def _call():
        transport = httpx.ASGITransport(app=main_mod.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            bad = await client.get("/notifications/unsubscribe", params={"token": "nope"}, headers=headers)
            posted = await client.post("/notifications/unsubscribe", params={"token": "nope"}, headers=headers)
            gone = await client.get("/notifications/unsubscribe", params={"token": expired}, headers=headers)
            gone_post = await client.post("/notifications/unsubscribe", json={"token": expired}, headers=headers)
            slash = await client.get("/notifications/unsubscribe/", params={"token": "nope"}, headers=headers)
            other = await client.get("/jobs", headers=headers)
            return bad, posted, gone, gone_post, slash, other

    bad, posted, gone, gone_post, slash, other = asyncio.run(_call())
    assert bad.status_code == 400
    assert posted.status_code == 400
    assert gone.status_code == 410
    assert gone_post.status_code == 410
    assert slash.status_code == 400
    for response in (bad, posted, gone, gone_post, slash):
        assert response.status_code not in (401, 403)
        assert "กรุณาเข้าสู่ระบบ" not in response.text
        assert "API key" not in response.text
        _no_identity(response.text)
    assert _prefs() == before
    assert other.status_code == 401


def test_access_log_redacts_unsubscribe_token(caplog):
    from uvicorn.logging import AccessFormatter

    secret = "super-secret-unsubscribe-token"
    notify.install_access_log_filter()
    path = f"/notifications/unsubscribe?token={secret}&x=1"
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:9", "GET", path, "1.1", 400),
        exc_info=None,
    )
    assert notify.AccessTokenFilter().filter(record) is True
    formatted = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s').format(record)
    assert secret not in formatted
    assert "token=REDACTED" in formatted
    assert "x=1" in formatted

    kept = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:9", "GET", f"/jobs?token={secret}", "1.1", 200),
        exc_info=None,
    )
    notify.redact_access_record(kept)
    assert kept.args[2] == f"/jobs?token={secret}"

    caplog.set_level(logging.INFO, logger="uvicorn.access")
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:9", "POST", f"/notifications/unsubscribe/?token={secret}", "1.1", 410,
    )
    assert secret not in caplog.text
    assert "token=REDACTED" in caplog.text
