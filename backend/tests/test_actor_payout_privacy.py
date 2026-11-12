"""GET /actor/me และ GET /admin/actor-usage ต้องไม่ส่งเลขผู้เสียภาษี ที่อยู่ หรือเลขบัญชีเต็ม

สำเนา PDPA (/auth/export), CSV หักภาษี และ GET /admin/actors/{id}/payment ยังส่งค่าเต็มตามเดิม
"""
import csv
import io
import json
import time
from dataclasses import replace

import pytest

from app import accounts, actors
from app.config import settings

TAX_ID = "1101700203450"
PAYOUT_ADDRESS = "ที่อยู่ลับในสำเนาการจ่าย-XYZ"
OWN_ADDRESS = "บ้านเลขที่ 1 ถนนสุขุมวิท แขวงคลองเตย"
ACCOUNT_NO = "998877665544"
UID = "actor-pii"


@pytest.fixture
def actor_db(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_conn", None)
    monkeypatch.setattr(actors, "_ready", False)
    monkeypatch.setattr(actors, "_va_cache", (0.0, {}))
    monkeypatch.setattr(actors, "_mood_cache", (0.0, {}))
    monkeypatch.setattr(accounts, "settings", replace(
        settings, data_dir=tmp_path, db_backend="files", auth_enabled=True))
    actors._init()
    paid_at = time.time()
    with accounts._tx() as db:
        db.execute("INSERT INTO actors (user_id, stage_name, gender, bio, contact, status, created_at) "
                   "VALUES (?, 'สมชาย', '', '', '', 'approved', ?)", (UID, paid_at))
        db.execute("INSERT INTO actor_payment (user_id, payee_name, tax_id, address, bank, account_no, "
                   "account_name, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (UID, "นาย สมชาย ใจดี", TAX_ID, OWN_ADDRESS, "พร้อมเพย์", ACCOUNT_NO, "สมชาย", paid_at))
        db.execute("INSERT INTO actor_payouts (actor_id, month, amount, wht, payee_name, tax_id, address, note, "
                   "paid_by, paid_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (UID, "2026-10", 150000, 4500, "นาย สมชาย ใจดี", TAX_ID, PAYOUT_ADDRESS, "โอนแล้ว",
                    "admin@pakdee.test", paid_at))
    yield paid_at
    if accounts._conn is not None:
        accounts._conn.close()


def _blob(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_actor_me_payouts_omit_tax_id_address_and_account(actor_db):
    from app.main import actor_me

    me = actor_me(user={"id": UID})
    assert len(me["payouts"]) == 1
    assert set(me["payouts"][0]) == {"id", "month", "amount", "wht", "paid_at"}
    assert me["payouts"][0]["amount"] == 150000
    assert me["payouts"][0]["wht"] == 4500
    text = _blob(me)
    assert TAX_ID not in text
    assert PAYOUT_ADDRESS not in text
    assert ACCOUNT_NO not in text
    # ข้อมูลรับเงินของตัวเองยังอยู่ แต่เลขผู้เสียภาษีและเลขบัญชีถูกปิดเหลือ 4 ตัวท้าย
    assert me["payment"]["address"] == OWN_ADDRESS
    assert me["payment"]["tax_id"].endswith(TAX_ID[-4:])
    assert me["payment"]["tax_id"] != TAX_ID
    assert me["payment"]["account_no"].endswith(ACCOUNT_NO[-4:])
    assert me["payment"]["account_no"] != ACCOUNT_NO


def test_admin_actor_usage_payouts_omit_tax_id_address_and_account(actor_db):
    from app.main import admin_actor_usage

    body = admin_actor_usage()
    assert len(body["payouts"]) == 1
    row = body["payouts"][0]
    assert set(row) == {"id", "month", "amount", "wht", "payee_name", "note", "paid_by", "paid_at"}
    assert row["payee_name"] == "นาย สมชาย ใจดี"
    assert row["note"] == "โอนแล้ว"
    assert row["paid_by"] == "admin@pakdee.test"
    text = _blob(body)
    assert TAX_ID not in text
    assert PAYOUT_ADDRESS not in text
    assert OWN_ADDRESS not in text
    assert ACCOUNT_NO not in text
    assert "tax_id" not in row
    assert "address" not in row
    assert "account_no" not in row


def test_export_wht_csv_and_admin_payment_keep_full_values(actor_db):
    from app.main import admin_actor_payment, admin_actor_wht_csv

    exported = actors.export_data(UID)
    assert exported["payouts"][0]["tax_id"] == TAX_ID
    assert exported["payouts"][0]["address"] == PAYOUT_ADDRESS
    assert exported["payment"]["account_no"] == ACCOUNT_NO
    assert exported["payment"]["tax_id"] == TAX_ID

    payment = admin_actor_payment(UID)
    assert payment["tax_id"] == TAX_ID
    assert payment["address"] == OWN_ADDRESS
    assert payment["account_no"] == ACCOUNT_NO

    month = actors.month_of(actor_db)
    res = admin_actor_wht_csv(month)
    rows = list(csv.reader(io.StringIO(res.body.decode("utf-8-sig"))))
    assert rows[1][1] == TAX_ID
    assert rows[1][3] == PAYOUT_ADDRESS
