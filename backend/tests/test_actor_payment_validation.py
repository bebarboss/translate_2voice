"""ข้อมูลรับเงินนักพากย์รับเฉพาะเลขอารบิก 0-9 และชื่อบนเวทีถูกตัดช่องว่างก่อนตรวจความยาว"""
import time
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app import accounts, actors
from app.config import settings
from app.main import ActorApply, ActorPayment

TAX_OK = "1101700203450"
ADDRESS = "123 ถนนสุขุมวิท แขวงคลองเตย เขตคลองเตย กรุงเทพ"
UID = "actor-pay"


def _thai_digits(ascii_digits: str) -> str:
    return "".join("๐๑๒๓๔๕๖๗๘๙"[int(ch)] for ch in ascii_digits)


def _fullwidth_digits(ascii_digits: str) -> str:
    return "".join(chr(ord("０") + int(ch)) for ch in ascii_digits)


@pytest.fixture
def actor_db(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_conn", None)
    monkeypatch.setattr(actors, "_ready", False)
    monkeypatch.setattr(accounts, "settings", replace(
        settings, data_dir=tmp_path, db_backend="files", auth_enabled=True))
    actors._init()
    with accounts._tx() as db:
        db.execute("INSERT INTO actors (user_id, stage_name, gender, bio, contact, status, created_at) "
                   "VALUES (?, 'สมชาย', '', '', '', 'approved', ?)", (UID, time.time()))
    yield
    if accounts._conn is not None:
        accounts._conn.close()


def _save(**kw):
    base = dict(payee_name="นาย สมชาย ใจดี", tax_id=TAX_OK, address=ADDRESS,
                bank="พร้อมเพย์", account_no="1234567890", account_name="สมชาย")
    base.update(kw)
    return actors.save_payment(UID, base["payee_name"], base["tax_id"], base["address"], base["bank"],
                               base["account_no"], base["account_name"])


def _model(**kw) -> ActorPayment:
    base = dict(payee_name="นาย สมชาย ใจดี", tax_id=TAX_OK, address=ADDRESS,
                bank="พร้อมเพย์", account_no="1234567890", account_name="สมชาย")
    base.update(kw)
    return ActorPayment(**base)


def test_tax_id_checksum_and_ascii_digits_only():
    import re

    assert actors.valid_tax_id(TAX_OK)
    assert not actors.valid_tax_id("1101700203451")
    assert not actors.valid_tax_id("")
    assert not actors.valid_tax_id("   ")
    assert not actors.valid_tax_id("1-3")
    thai, wide = _thai_digits(TAX_OK), _fullwidth_digits(TAX_OK)
    # \d ของไพธอนรับเลขยูนิโค้ด ตัวตรวจของเราต้องไม่รับ
    assert re.fullmatch(r"\d{13}", thai) and re.fullmatch(r"\d{13}", wide)
    assert not actors.valid_tax_id(thai)
    assert not actors.valid_tax_id(wide)


def test_save_payment_rejects_bad_input_and_stores_normalized_ascii(actor_db):
    with pytest.raises(accounts.AccountError) as bad_sum:
        _save(tax_id="1101700203451")
    assert bad_sum.value.status == 400

    with pytest.raises(accounts.AccountError):
        _save(tax_id=_thai_digits(TAX_OK))
    with pytest.raises(accounts.AccountError):
        _save(tax_id=_fullwidth_digits(TAX_OK))
    with pytest.raises(accounts.AccountError):
        _save(tax_id="   ")
    with pytest.raises(accounts.AccountError):
        _save(tax_id="---")
    with pytest.raises(accounts.AccountError):
        _save(payee_name="   ")
    with pytest.raises(accounts.AccountError):
        _save(payee_name=" \t ")
    with pytest.raises(accounts.AccountError):
        _save(address="     ")
    with pytest.raises(accounts.AccountError):
        _save(address="สั้นไป")
    with pytest.raises(accounts.AccountError) as bad_bank:
        _save(bank="ธนาคารไม่มีจริง")
    assert bad_bank.value.status == 400
    assert "ธนาคาร" in str(bad_bank.value)

    with pytest.raises(accounts.AccountError):
        _save(account_no="123456789")
    with pytest.raises(accounts.AccountError):
        _save(account_no="1234567890123456")
    with pytest.raises(accounts.AccountError):
        _save(account_no="  -  ")
    with pytest.raises(accounts.AccountError):
        _save(account_no=_thai_digits("1234567890"))
    with pytest.raises(accounts.AccountError):
        _save(account_no=_fullwidth_digits("1234567890"))

    _save(tax_id="1101 7002-03450", account_no="123-456-7890")
    stored = actors.payment(UID)
    assert stored["tax_id"] == TAX_OK
    assert stored["account_no"] == "1234567890"

    _save(account_no="123456789012345")
    assert actors.payment(UID)["account_no"] == "123456789012345"


def test_actor_payment_schema_matches_ascii_digit_rules():
    props = ActorPayment.model_json_schema()["properties"]
    assert props["tax_id"]["minLength"] == 13
    assert props["tax_id"]["maxLength"] == 13
    assert props["tax_id"]["pattern"] == "^[0-9]{13}$"
    assert props["account_no"]["minLength"] == 10
    assert props["account_no"]["maxLength"] == 15
    assert props["account_no"]["pattern"] == "^[0-9]{10,15}$"

    spaced = _model(tax_id="1101 7002-03450", account_no="123 456-7890")
    assert spaced.tax_id == TAX_OK
    assert spaced.account_no == "1234567890"

    for bad in ("", "   ", "---", _thai_digits(TAX_OK), _fullwidth_digits(TAX_OK), "110170020345"):
        with pytest.raises(ValidationError):
            _model(tax_id=bad)
    for bad in ("", "  -  ", "123456789", "1234567890123456", _thai_digits("1234567890"),
                _fullwidth_digits("123456789012345")):
        with pytest.raises(ValidationError):
            _model(account_no=bad)


def test_stage_name_is_stripped_before_the_length_check():
    assert ActorApply(stage_name="  มิ้นต์  ", consent_version="v").stage_name == "มิ้นต์"
    assert ActorApply(stage_name=" " + ("ก" * 60) + " ", consent_version="v").stage_name == "ก" * 60
    with pytest.raises(ValidationError):
        ActorApply(stage_name="   ", consent_version="v")
    with pytest.raises(ValidationError):
        ActorApply(stage_name=" \u3000 ", consent_version="v")
    with pytest.raises(ValidationError):
        ActorApply(stage_name=" " + ("ก" * 61) + " ", consent_version="v")
