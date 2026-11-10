"""สลิปโอนเงิน: อ่านยอดจากข้อความ และเติมเครดิตเมื่อ Typhoon OCR (จำลอง) ได้ยอดตรงบัญชี"""
from dataclasses import replace

import pytest

from app import accounts
from app.config import settings
from app.slip_ocr import SlipOcrError, SlipRead, account_in_text, choose_amount, labeled_amount, parse_when, verdict


def _slip(**kw) -> SlipRead:
    base = dict(text="โอนเข้า 1234567890 จำนวนเงิน 150.00 บาท", amount=15000, conflict=False,
                ref="REF1", payer="นาย ก", payee="สตูดิโอ", payee_account="1234567890",
                transferred_at=None, when=None)
    base.update(kw)
    return SlipRead(**base)


def test_labeled_amount_reads_thai_label_and_html():
    assert labeled_amount("ค่าธรรมเนียม 0.00 บาท\nจำนวนเงิน 150.00 บาท") == 15000
    assert labeled_amount("<tr><td>จำนวนเงิน</td><td>1,500.00</td></tr>") == 150000
    assert labeled_amount("คงเหลือ 9,999.00 บาท และ 150.00 บาท") is None


def test_choose_amount_conflicts_when_sources_disagree():
    assert choose_amount(15000, 15000) == (15000, False)
    assert choose_amount(15000, None) == (15000, False)
    assert choose_amount(15000, 14900) == (None, True)


def test_account_and_buddhist_date():
    assert account_in_text("123-4-56789-0", "ไปยัง 1234567890")
    assert not account_in_text("9999999999", "ไปยัง 1234567890")
    when = parse_when("6 พ.ย. 2569 17:30")
    assert when is not None
    assert when > parse_when("2026-11-06 17:00")


def test_verdict_requires_exact_amount_and_account():
    ok, _ = verdict(15000, _slip(), payee_account="123-4-56789-0", max_age_hours=72, now=1_700_000_000)
    assert ok
    bad, note = verdict(9900, _slip(), payee_account="123-4-56789-0", max_age_hours=72, now=1_700_000_000)
    assert not bad and "ไม่ตรง" in note
    old = _slip(when=1_700_000_000 - 80 * 3600)
    late, note = verdict(15000, old, payee_account="123-4-56789-0", max_age_hours=72, now=1_700_000_000)
    assert not late and "เก่ากว่า" in note


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_conn", None)
    monkeypatch.setattr(accounts, "settings", replace(
        settings, data_dir=tmp_path, db_backend="files", payment_provider="slip", payee_name="สตูดิโอ",
        payee_bank="กสิกรไทย", payee_account="123-4-56789-0", auth_enabled=True, billing_enabled=True,
        slip_max_mb=8, slip_max_age_hours=72))
    accounts._db().execute(
        "INSERT INTO users (id, email, name, pw_hash, created_at) VALUES ('u1', 'a@b.c', 'Ann', 'x', 0)")
    yield accounts
    if accounts._conn is not None:
        accounts._conn.close()
        accounts._conn = None


def _jpeg(mark: bytes) -> bytes:
    return b"\xff\xd8\xff" + mark


def _with_package(book):
    """เติมเครดิตได้เมื่อมีแพ็กเกจแล้ว ทดลองให้สิทธิ์โดยไม่เพิ่มเครดิตเติม"""
    book.claim_trial("u1")


def _matching(book, credits: int = 10):
    """สลิปที่ยอดตรงกับออเดอร์ ตามราคาเครดิตปัจจุบัน ไม่ผูกกับตัวเลขบาทที่เคยใช้"""
    return _slip(amount=credits * book.CREDIT_PRICE)


def test_topup_requires_a_package(book):
    with pytest.raises(book.AccountError) as err:
        book.buy_credits("u1", 10)
    assert err.value.status == 402
    assert book.wallet("u1")["credits"] == 0


def test_matching_slip_adds_credits(book, monkeypatch):
    _with_package(book)
    monkeypatch.setattr(book, "read_slip", lambda data, mime: _matching(book))
    order = book.buy_credits("u1", 10)
    assert order["status"] == "pending"
    assert order["amount"] == 10 * book.CREDIT_PRICE
    assert order["payee"]["account"] == "123-4-56789-0"
    done = book.submit_slip("u1", order["id"], _jpeg(b"a"))
    assert done["status"] == "paid"
    assert "เติมเครดิตแล้ว" in done["note"]
    assert book.wallet("u1")["credits"] == 10


def test_mismatch_waits_for_admin_then_approve(book, monkeypatch):
    _with_package(book)
    wrong = 10 * book.CREDIT_PRICE + 100
    monkeypatch.setattr(book, "read_slip", lambda data, mime: _slip(amount=wrong, text="จำนวนเงิน 100.00 บาท 1234567890"))
    order = book.buy_credits("u1", 10)
    waiting = book.submit_slip("u1", order["id"], _jpeg(b"b"))
    assert waiting["status"] == "review"
    assert book.wallet("u1")["credits"] == 0
    approved = book.approve_payment(order["id"], "admin@b.c")
    assert approved["status"] == "paid"
    assert book.wallet("u1")["credits"] == 10


def test_duplicate_slip_is_rejected_and_resubmit_stays_in_review(book, monkeypatch):
    _with_package(book)
    monkeypatch.setattr(book, "read_slip", lambda data, mime: _matching(book))
    first = book.buy_credits("u1", 10)
    image = _jpeg(b"same")
    assert book.submit_slip("u1", first["id"], image)["status"] == "paid"
    second = book.buy_credits("u1", 10)
    with pytest.raises(book.AccountError) as err:
        book.submit_slip("u1", second["id"], image)
    assert err.value.status == 409
    wrong = 10 * book.CREDIT_PRICE + 100
    monkeypatch.setattr(book, "read_slip", lambda data, mime: _slip(amount=wrong, text="100.00"))
    bad = book.submit_slip("u1", second["id"], _jpeg(b"other"))
    assert bad["status"] == "review"
    book.reject_payment(second["id"], "admin@b.c", "ยอดไม่ครบ")
    monkeypatch.setattr(book, "read_slip", lambda data, mime: _matching(book))
    again = book.submit_slip("u1", second["id"], _jpeg(b"fresh"))
    assert again["status"] == "review"
    assert book.wallet("u1")["credits"] == 10


def test_unreadable_image_and_ocr_failure(book, monkeypatch):
    _with_package(book)
    order = book.buy_credits("u1", 10)
    with pytest.raises(book.AccountError) as err:
        book.submit_slip("u1", order["id"], b"not-an-image")
    assert err.value.status == 400

    def boom(data, mime):
        raise SlipOcrError("อ่านสลิปไม่สำเร็จ")

    monkeypatch.setattr(book, "read_slip", boom)
    waiting = book.submit_slip("u1", order["id"], _jpeg(b"c"))
    assert waiting["status"] == "review"
    assert waiting["has_slip"]
    assert book.wallet("u1")["credits"] == 0
