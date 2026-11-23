"""แจ้งเตือนในแอป (inbox.py): เขียน กันซ้ำ แยกตามผู้ใช้ อ่านแล้ว และเชื่อมกับ notify"""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app import accounts, inbox, notify
from app.config import settings


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_conn", None)
    monkeypatch.setattr(inbox, "_ready", False)
    local = replace(settings, data_dir=tmp_path, db_backend="files", auth_enabled=True, billing_enabled=True)
    monkeypatch.setattr(accounts, "settings", local)
    monkeypatch.setattr("app.config.settings", local)  # using_postgres() อ่านจากโมดูล config ไม่ใช่ accounts (.env ในเครื่องตั้ง postgres)
    db = accounts._db()
    for uid, mail in (("u1", "a@b.c"), ("u2", "d@e.f")):
        db.execute("INSERT INTO users (id, email, name, pw_hash, created_at) VALUES (?, ?, 'N', 'x', 0)", (uid, mail))
    yield accounts
    if accounts._conn is not None:
        accounts._conn.close()
        accounts._conn = None


def test_add_and_list_newest_first_with_unread(book):
    inbox.add("u1", "job_done", "เสร็จ", "a", "/jobs/1", "j1")
    inbox.add("u1", "job_failed", "ล้ม", "b", "/jobs/2", "j2")
    out = inbox.list_for("u1")
    assert out["unread"] == 2
    assert [i["title"] for i in out["items"]] == ["ล้ม", "เสร็จ"]
    assert out["items"][0]["read"] is False and out["items"][0]["link"] == "/jobs/2"


def test_same_job_and_kind_is_deduped_but_other_kind_is_not(book):
    assert inbox.add("u1", "job_done", "x", job_id="j1") is not None
    assert inbox.add("u1", "job_done", "x", job_id="j1") is None
    assert inbox.add("u1", "job_failed", "x", job_id="j1") is not None
    assert inbox.unread_count("u1") == 2


def test_users_only_see_and_mark_their_own(book):
    n = inbox.add("u1", "job_done", "เสร็จ", job_id="j1")
    assert inbox.list_for("u2") == {"items": [], "unread": 0}
    assert inbox.mark_read("u2", n["id"]) is False  # ของคนอื่น
    assert inbox.unread_count("u1") == 1
    assert inbox.mark_read("u1", n["id"]) is True
    assert inbox.unread_count("u1") == 0
    assert inbox.list_for("u1")["items"][0]["read"] is True


def test_mark_all_only_affects_that_user(book):
    inbox.add("u1", "a", "1")
    inbox.add("u1", "b", "2")
    inbox.add("u2", "a", "3")
    inbox.mark_all("u1")
    assert inbox.unread_count("u1") == 0
    assert inbox.unread_count("u2") == 1


def test_unread_count_is_not_capped_by_list_limit(book):
    for i in range(5):
        inbox.add("u1", f"k{i}", "t")
    out = inbox.list_for("u1", limit=2)
    assert len(out["items"]) == 2 and out["unread"] == 5


def test_old_rows_are_purged_on_add(book, monkeypatch):
    import time
    inbox.add("u1", "old", "เก่า")
    with accounts._tx() as db:
        db.execute("UPDATE notifications SET created_at = ?", (time.time() - (inbox.KEEP_DAYS + 1) * 86400,))
    monkeypatch.setattr(inbox.secrets, "randbelow", lambda n: 0)  # บังคับให้รอบนี้ลบของเก่า
    inbox.add("u1", "new", "ใหม่")
    assert [i["title"] for i in inbox.list_for("u1")["items"]] == ["ใหม่"]


def test_auth_disabled_writes_nothing(book, monkeypatch):
    monkeypatch.setattr(accounts, "settings", replace(accounts.settings, auth_enabled=False))
    assert inbox.add("u1", "job_done", "x") is None
    assert inbox.add(None, "job_done", "x") is None


def test_add_failure_does_not_raise(book, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(accounts, "_tx", boom)
    assert inbox.add("u1", "job_done", "x") is None  # แค่บันทึก log ไม่กระทบงาน


@pytest.mark.parametrize("kind,key,expect", [
    ("done", "job_done", "พร้อมดูผล"), ("review", "job_review", "รอคุณตรวจบท"), ("failed", "job_failed", "ทำไม่สำเร็จ"),
])
def test_job_events_create_inbox_rows_even_for_fast_or_email_off(book, kind, key, expect):
    job = SimpleNamespace(filename="clip.mp4", error="boom\nmore")
    notify._inbox_job({"id": "u1"}, job, "j9", kind)
    item = inbox.list_for("u1")["items"][0]
    assert item["kind"] == key and expect in item["body"] and item["link"] == "/jobs/j9" and item["job_id"] == "j9"
    if kind == "failed":
        assert item["body"] == (
            "งาน “clip.mp4” ทำไม่สำเร็จ เครดิตของขั้นที่ไม่สำเร็จคืนให้อัตโนมัติ "
            "กดเปิดงานเพื่อดูรายละเอียดและลองใหม่"
        )
        assert "boom" not in item["body"] and "more" not in item["body"]


def test_api_routes_are_scoped_to_the_signed_in_user(book):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import account_api

    app = FastAPI()
    app.include_router(account_api.router)
    who = {"id": "u1"}
    app.dependency_overrides[account_api.require_user] = lambda: who
    c = TestClient(app)
    mine = inbox.add("u1", "job_done", "เสร็จ", job_id="j1")
    theirs = inbox.add("u2", "job_done", "ของอีกคน", job_id="j2")

    r = c.get("/notifications")
    assert r.status_code == 200 and r.json()["unread"] == 1 and r.json()["items"][0]["id"] == mine["id"]
    assert c.get("/notifications/unread").json() == {"unread": 1}
    assert c.post(f"/notifications/{theirs['id']}/read").status_code == 404  # อ่านของคนอื่นไม่ได้
    assert c.post(f"/notifications/{mine['id']}/read").json() == {"unread": 0}
    inbox.add("u1", "job_failed", "ล้ม", job_id="j3")
    assert c.post("/notifications/read-all").json() == {"unread": 0}
    assert inbox.unread_count("u2") == 1  # ของอีกคนไม่ถูกแตะ
