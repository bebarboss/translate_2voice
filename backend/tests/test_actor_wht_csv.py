"""ช่องชื่อ ที่อยู่ และหมายเหตุใน CSV หักภาษีต้องไม่กลายเป็นสูตรของสเปรดชีต"""
import csv
import io
import time
from dataclasses import replace

import pytest

from app import accounts, actors
from app.config import settings

UID = "actor-csv"


@pytest.fixture
def actor_db(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_conn", None)
    monkeypatch.setattr(actors, "_ready", False)
    monkeypatch.setattr(accounts, "settings", replace(
        settings, data_dir=tmp_path, db_backend="files", auth_enabled=True))
    actors._init()
    yield
    if accounts._conn is not None:
        accounts._conn.close()


def _insert(name: str, address: str, note: str, paid_at: float) -> None:
    with accounts._tx() as db:
        db.execute("INSERT INTO actor_payouts (actor_id, month, amount, wht, payee_name, tax_id, address, note, "
                   "paid_by, paid_at) VALUES (?, '2026-10', 100000, 3000, ?, '1101700203450', ?, ?, 'admin@pakdee.test', ?)",
                   (UID, name, address, note, paid_at))


def _csv_rows(paid_at: float) -> list[list[str]]:
    from app.main import admin_actor_wht_csv

    res = admin_actor_wht_csv(actors.month_of(paid_at))
    return list(csv.reader(io.StringIO(res.body.decode("utf-8-sig"))))


def test_csv_text_prefixes_formula_and_leaves_plain_text():
    assert actors.csv_text("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
    assert actors.csv_text("+CMD") == "'+CMD"
    assert actors.csv_text("-1+1") == "'-1+1"
    assert actors.csv_text("@SUM(A1)") == "'@SUM(A1)"
    assert actors.csv_text("\t=1+1") == "'\t=1+1"
    assert actors.csv_text("\r=1+1") == "'\r=1+1"
    assert actors.csv_text("นาย สมชาย") == "นาย สมชาย"
    assert actors.csv_text("สมชาย = นักพากย์") == "สมชาย = นักพากย์"
    assert actors.csv_text("") == ""
    assert actors.csv_text(None) == ""


def test_wht_csv_neutralizes_name_address_and_note(actor_db):
    paid_at = time.time()
    dangerous = [
        ("=HYPERLINK(\"http://evil\")", "ที่อยู่ปกติ", "โอนแล้ว"),
        ("นาย ปกติ", "+CMD|' /C calc'!A0", "หมายเหตุ"),
        ("นาย อีกคน", "123 ถนนสุขุมวิท", "-1+1"),
        ("@SUM(A1)", "ที่อยู่", "ok"),
        ("\tชื่อ", "ที่อยู่", "ok"),
        ("ชื่อ", "\rที่อยู่", "ok"),
    ]
    for i, (name, address, note) in enumerate(dangerous):
        _insert(name, address, note, paid_at + i)
    # แถวธรรมดาต้องไม่ถูกเติม '
    _insert("นาง สมหญิง ใจดี", "99/1 ถนนพระราม เขตบางรัก", "อ้างอิง 1234", paid_at + 10)

    rows = _csv_rows(paid_at)
    body = rows[1:]
    assert len(body) == 7
    # คอลัมน์: ชื่อ index 2, ที่อยู่ index 3, หมายเหตุ index 11, เลขภาษี index 1 ไม่ถูกเติม '
    assert body[0][2].startswith("'=")
    assert body[0][3] == "ที่อยู่ปกติ"
    assert body[0][11] == "โอนแล้ว"
    assert body[1][2] == "นาย ปกติ"
    assert body[1][3].startswith("'+")
    assert body[2][11].startswith("'-")
    assert body[3][2].startswith("'@")
    assert body[4][2].startswith("'\t")
    assert body[5][3].startswith("'\r")
    assert body[6][2] == "นาง สมหญิง ใจดี"
    assert body[6][3] == "99/1 ถนนพระราม เขตบางรัก"
    assert body[6][11] == "อ้างอิง 1234"
    for row in body:
        assert row[1] == "1101700203450"
        assert not row[1].startswith("'")
