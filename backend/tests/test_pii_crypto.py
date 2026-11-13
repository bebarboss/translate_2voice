"""เข้ารหัส tax_id / account_no ที่พัก: round-trip, คีย์ผิด, หมุนคีย์, HMAC, dual-write, backfill

คีย์ในเทสสุ่มตอนรัน ไม่มีค่าจริงในไฟล์
"""
import base64
import csv
import io
import json
import logging
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

from app import accounts, actors, consent, pii_crypto
from app.config import settings
from app.pgstore import _rewrite
from app.pii_backfill import BackfillError, main, run

TAX_ID = "1101700203450"
TAX_ID_2 = "1100000000008"
ACCOUNT_NO = "998877665544"
ADDRESS = "+123 ถนนสุขุมวิท แขวงคลองเตย"
PAYEE = "=นักพากย์ ทดสอบ"
UID = "actor-pii"
OTHER = "actor-pii-2"
REPO = Path(__file__).resolve().parents[2]


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


@pytest.fixture
def pii_env(monkeypatch):
    monkeypatch.setenv("PII_ENC_KEYS", f"1:{_key()},2:{_key()}")
    monkeypatch.setenv("PII_ENC_ACTIVE_VERSION", "1")
    monkeypatch.setenv("PII_HMAC_KEY", _key())
    monkeypatch.delenv("PII_ENC_DEV_EPHEMERAL", raising=False)
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    pii_crypto.reset()
    yield
    pii_crypto.reset()


@pytest.fixture
def actor_db(pii_env, tmp_path, monkeypatch):
    patched = replace(settings, data_dir=tmp_path, db_backend="files", auth_enabled=True, supabase_db_url="")
    monkeypatch.setattr(accounts, "_conn", None)
    monkeypatch.setattr(accounts, "settings", patched)
    monkeypatch.setattr("app.config.settings", patched)
    monkeypatch.setattr(actors, "_ready", False)
    monkeypatch.setattr(actors, "_va_cache", (0.0, {}))
    monkeypatch.setattr(actors, "_mood_cache", (0.0, {}))
    monkeypatch.setattr(consent, "_ready", False)
    actors._init()
    now = time.time()
    with accounts._tx() as db:
        db.execute(
            "INSERT INTO users (id, email, name, pw_hash, created_at) VALUES (?, ?, ?, '', ?)",
            (UID, "actor-pii@pakdee.test", "สมชาย", now),
        )
        db.execute(
            "INSERT INTO actors (user_id, stage_name, gender, bio, contact, status, created_at) "
            "VALUES (?, 'สมชาย', '', '', '', 'approved', ?)",
            (UID, now),
        )
    yield now
    if accounts._conn is not None:
        accounts._conn.close()


def _save(uid: str = UID, tax_id: str = TAX_ID, account_no: str = ACCOUNT_NO, name: str = PAYEE) -> dict:
    return actors.save_payment(uid, name, tax_id, ADDRESS, "พร้อมเพย์", account_no, "สมชาย ใจดี")


def _raw_payment(uid: str = UID):
    return accounts._read(
        "SELECT tax_id, tax_id_enc, tax_id_hmac, account_no, account_no_enc FROM actor_payment WHERE user_id = ?",
        uid,
    )[0]


def test_round_trip_uses_random_nonce_and_version_prefix(pii_env):
    token = pii_crypto.encrypt("1101700203450", table="actor_payment", column="tax_id", row_id="user-1")
    again = pii_crypto.encrypt("1101700203450", table="actor_payment", column="tax_id", row_id="user-1")
    assert token.startswith("v1:")
    assert again.startswith("v1:")
    assert token != again
    raw = base64.b64decode(token.split(":", 1)[1], validate=True)
    other = base64.b64decode(again.split(":", 1)[1], validate=True)
    assert len(raw) >= 12 + 16
    assert raw[:12] != other[:12]
    assert pii_crypto.decrypt(token, table="actor_payment", column="tax_id", row_id="user-1") == "1101700203450"


def test_wrong_key_tamper_and_wrong_row_fail(pii_env, monkeypatch):
    token = pii_crypto.encrypt(TAX_ID, table="actor_payment", column="tax_id", row_id="user-1")
    monkeypatch.setenv("PII_ENC_KEYS", f"1:{_key()},2:{_key()}")
    pii_crypto.reset()
    with pytest.raises(pii_crypto.PiiCryptoError):
        pii_crypto.decrypt(token, table="actor_payment", column="tax_id", row_id="user-1")

    fresh = pii_crypto.encrypt(TAX_ID, table="actor_payment", column="tax_id", row_id="user-1")
    version, blob = fresh.split(":", 1)
    flipped = bytearray(base64.b64decode(blob))
    flipped[-1] ^= 0x01
    tampered = version + ":" + base64.b64encode(bytes(flipped)).decode()
    with pytest.raises(pii_crypto.PiiCryptoError):
        pii_crypto.decrypt(tampered, table="actor_payment", column="tax_id", row_id="user-1")
    with pytest.raises(pii_crypto.PiiCryptoError):
        pii_crypto.decrypt(fresh, table="actor_payment", column="tax_id", row_id="someone-else")
    with pytest.raises(pii_crypto.PiiCryptoError):
        pii_crypto.decrypt(fresh, table="actor_payment", column="account_no", row_id="user-1")


def test_key_rotation_keeps_old_ciphertext(pii_env, monkeypatch):
    old = pii_crypto.encrypt(ACCOUNT_NO, table="actor_payment", column="account_no", row_id="user-1")
    assert old.startswith("v1:")
    monkeypatch.setenv("PII_ENC_ACTIVE_VERSION", "2")
    pii_crypto.reset()
    assert pii_crypto.decrypt(old, table="actor_payment", column="account_no", row_id="user-1") == ACCOUNT_NO
    new = pii_crypto.encrypt(ACCOUNT_NO, table="actor_payment", column="account_no", row_id="user-1")
    assert new.startswith("v2:")
    assert pii_crypto.decrypt(new, table="actor_payment", column="account_no", row_id="user-1") == ACCOUNT_NO
    assert pii_crypto.decrypt(old, table="actor_payment", column="account_no", row_id="user-1") == ACCOUNT_NO


def test_missing_keys_fail_fast_and_dev_flag_is_ephemeral(monkeypatch):
    for name in ("PII_ENC_KEYS", "PII_ENC_ACTIVE_VERSION", "PII_HMAC_KEY", "PII_ENC_DEV_EPHEMERAL", "KUBERNETES_SERVICE_HOST"):
        monkeypatch.delenv(name, raising=False)
    pii_crypto.reset()
    with pytest.raises(pii_crypto.PiiCryptoError) as missing:
        pii_crypto.require_keys()
    assert "PII_ENC_KEYS" in str(missing.value)
    assert "PII_HMAC_KEY" in str(missing.value)
    assert "PII_ENC_DEV_EPHEMERAL" in str(missing.value)

    monkeypatch.setenv("PII_ENC_DEV_EPHEMERAL", "1")
    pii_crypto.reset()
    token = pii_crypto.encrypt(TAX_ID, table="actor_payment", column="tax_id", row_id="u")
    assert pii_crypto.decrypt(token, table="actor_payment", column="tax_id", row_id="u") == TAX_ID
    assert pii_crypto.require_keys().ephemeral is True
    pii_crypto.reset()
    with pytest.raises(pii_crypto.PiiCryptoError):
        pii_crypto.decrypt(token, table="actor_payment", column="tax_id", row_id="u")

    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.43.0.1")
    pii_crypto.reset()
    with pytest.raises(pii_crypto.PiiCryptoError) as blocked:
        pii_crypto.require_keys()
    assert "Kubernetes" in str(blocked.value)

    bad = base64.b64encode(b"short-key").decode()
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    monkeypatch.delenv("PII_ENC_DEV_EPHEMERAL", raising=False)
    monkeypatch.setenv("PII_ENC_KEYS", f"1:{bad}")
    monkeypatch.setenv("PII_ENC_ACTIVE_VERSION", "1")
    monkeypatch.setenv("PII_HMAC_KEY", _key())
    pii_crypto.reset()
    with pytest.raises(pii_crypto.PiiCryptoError) as bad_key:
        pii_crypto.require_keys()
    assert bad not in str(bad_key.value)


def test_explicit_keys_win_over_dev_flag(pii_env, monkeypatch):
    monkeypatch.setenv("PII_ENC_DEV_EPHEMERAL", "1")
    pii_crypto.reset()
    ring = pii_crypto.require_keys()
    assert ring.ephemeral is False
    assert ring.active == 1


def test_hmac_lookup_ignores_spaces_and_dashes(actor_db):
    _save()
    assert pii_crypto.normalize_tax_id("1101 7002-03450") == TAX_ID
    assert pii_crypto.tax_id_hmac("11017-00203-450") == pii_crypto.tax_id_hmac(TAX_ID)
    assert pii_crypto.tax_id_hmac("11017 00203 450") == pii_crypto.tax_id_hmac(TAX_ID)
    assert actors.find_payment_user("11017-00203-450") == UID
    assert actors.find_payment_user(TAX_ID_2) is None
    thai = "".join("๐๑๒๓๔๕๖๗๘๙"[int(ch)] for ch in TAX_ID)
    wide = "".join(chr(ord("０") + int(ch)) for ch in TAX_ID)
    with pytest.raises(pii_crypto.PiiCryptoError):
        pii_crypto.tax_id_hmac(thai)
    with pytest.raises(pii_crypto.PiiCryptoError):
        pii_crypto.tax_id_hmac(wide)
    assert actors.find_payment_user(thai) is None
    assert actors.find_payment_user(wide) is None


def test_dual_write_prefers_ciphertext_and_rejects_a_duplicate(actor_db, monkeypatch):
    _save()
    row = _raw_payment()
    assert row["tax_id"] == TAX_ID
    assert row["account_no"] == ACCOUNT_NO
    assert row["tax_id_enc"].startswith("v1:")
    assert row["account_no_enc"].startswith("v1:")
    assert row["tax_id_enc"] != TAX_ID
    assert row["tax_id_hmac"] == pii_crypto.tax_id_hmac(TAX_ID)
    assert pii_crypto.decrypt(row["tax_id_enc"], table="actor_payment", column="tax_id", row_id=UID) == TAX_ID
    assert pii_crypto.decrypt(
        row["account_no_enc"], table="actor_payment", column="account_no", row_id=UID,
    ) == ACCOUNT_NO

    with accounts._tx() as db:
        db.execute(
            "UPDATE actor_payment SET tax_id = ?, account_no = ? WHERE user_id = ?",
            ("9999999999994", "0000000000", UID),
        )
    opened = actors.payment(UID)
    assert opened["tax_id"] == TAX_ID
    assert opened["account_no"] == ACCOUNT_NO
    assert "tax_id_enc" not in opened
    masked = actors.payment_out(UID)
    assert masked["tax_id"].endswith(TAX_ID[-4:])
    assert masked["tax_id"] != TAX_ID
    assert masked["account_no"].endswith(ACCOUNT_NO[-4:])

    monkeypatch.setenv("PII_ENC_ACTIVE_VERSION", "2")
    pii_crypto.reset()
    assert actors.payment(UID)["tax_id"] == TAX_ID
    _save()
    assert _raw_payment()["tax_id_enc"].startswith("v2:")
    assert actors.payment(UID)["account_no"] == ACCOUNT_NO

    now = time.time()
    with accounts._tx() as db:
        db.execute(
            "INSERT INTO actors (user_id, stage_name, gender, bio, contact, status, created_at) "
            "VALUES (?, 'อีกคน', '', '', '', 'approved', ?)",
            (OTHER, now),
        )
    with pytest.raises(accounts.AccountError) as clash:
        _save(uid=OTHER)
    assert clash.value.status == 409

    with accounts._tx() as db:
        db.execute("UPDATE actor_payment SET tax_id_enc = ? WHERE user_id = ?", ("v1:AAAA", UID))
    with pytest.raises(pii_crypto.PiiCryptoError):
        actors.payment(UID)


def test_authorized_export_and_csv_keep_full_values(actor_db):
    from app.main import actor_me, admin_actor_payment, admin_actor_usage, admin_actor_wht_csv, export_my_data

    _save()
    now = actor_db
    with accounts._tx() as db:
        db.execute(
            "INSERT INTO voice_usage (job_id, voice_id, actor_id, user_id, job_name, seconds, lines, month, "
            "created_at, updated_at) VALUES ('job-pii', 'voice-pii', ?, 'customer-1', 'clip', 60000, 4, '2026-10', ?, ?)",
            (UID, now, now),
        )
    actors.add_payout(UID, "2026-10", "=note", "admin@pakdee.test")
    payout = actors.payouts(UID)[0]
    assert payout["tax_id"] == TAX_ID
    assert payout["address"] == ADDRESS
    assert "tax_id_enc" not in payout
    with accounts._tx() as db:
        db.execute("UPDATE actor_payouts SET tax_id = ? WHERE actor_id = ?", ("0000000000000", UID))
    assert actors.payouts(UID)[0]["tax_id"] == TAX_ID

    response = export_my_data(user={"id": UID})
    exported = json.loads(response.body)
    actor = exported["actor"]
    assert actor["payment"]["tax_id"] == TAX_ID
    assert actor["payment"]["account_no"] == ACCOUNT_NO
    assert actor["payouts"][0]["tax_id"] == TAX_ID
    blob = json.dumps(exported, ensure_ascii=False)
    assert "tax_id_enc" not in blob
    assert "v1:" not in blob
    assert TAX_ID in blob

    payment = admin_actor_payment(UID)
    assert payment["tax_id"] == TAX_ID
    assert payment["account_no"] == ACCOUNT_NO
    assert "account_no_enc" not in payment

    month = actors.month_of(actors.payouts(UID)[0]["paid_at"])
    res = admin_actor_wht_csv(month)
    rows = list(csv.reader(io.StringIO(res.body.decode("utf-8-sig"))))
    assert rows[1][1] == TAX_ID
    assert not rows[1][1].startswith("'")
    assert rows[1][2].startswith("'=")
    assert rows[1][3].startswith("'+")
    assert rows[1][11].startswith("'=")

    me = actor_me(user={"id": UID})
    me_blob = json.dumps(me, ensure_ascii=False)
    assert TAX_ID not in me_blob
    assert ACCOUNT_NO not in me_blob
    assert "v1:" not in me_blob
    assert me["payment"]["tax_id"].endswith(TAX_ID[-4:])
    assert me["payment"]["account_no"].endswith(ACCOUNT_NO[-4:])

    usage = json.dumps(admin_actor_usage(), ensure_ascii=False)
    assert TAX_ID not in usage
    assert ACCOUNT_NO not in usage


def test_backfill_is_idempotent_and_prints_counts_only(actor_db, capsys):
    now = time.time()
    with accounts._tx() as db:
        db.execute(
            "INSERT INTO actor_payment (user_id, payee_name, tax_id, address, bank, account_no, account_name, updated_at) "
            "VALUES (?, 'นาย สมชาย', ?, ?, 'พร้อมเพย์', ?, 'สมชาย', ?)",
            (UID, TAX_ID, ADDRESS, ACCOUNT_NO, now),
        )
        db.execute(
            "INSERT INTO actor_payouts (actor_id, month, amount, wht, payee_name, tax_id, address, note, paid_by, paid_at) "
            "VALUES (?, '2026-10', 100, 0, 'นาย สมชาย', ?, ?, '', 'admin', ?)",
            (UID, TAX_ID, ADDRESS, now),
        )
    sink = _LogSink()
    logging.getLogger("dubbing.pii").addHandler(sink)
    logging.getLogger("dubbing.pii_backfill").addHandler(sink)
    try:
        assert main(["--dry-run", "--count-only", "--batch", "1"]) == 0
        dry_out = capsys.readouterr()
        assert TAX_ID not in dry_out.out and TAX_ID not in dry_out.err
        assert ACCOUNT_NO not in dry_out.out and ACCOUNT_NO not in dry_out.err
        dry = json.loads(dry_out.out)
        assert dry["dry_run"] is True
        assert dry["actor_payment"]["updated"] == 1
        assert dry["actor_payouts"]["updated"] == 1
        assert _raw_payment()["tax_id_enc"] in (None, "")

        assert main(["--count-only", "--batch", "1"]) == 0
        first_out = capsys.readouterr()
        assert TAX_ID not in first_out.out and ACCOUNT_NO not in first_out.err
        first = json.loads(first_out.out)
        assert first["actor_payment"]["updated"] == 1
        assert first["actor_payouts"]["updated"] == 1
        stored = _raw_payment()
        assert pii_crypto.decrypt(stored["tax_id_enc"], table="actor_payment", column="tax_id", row_id=UID) == TAX_ID
        assert pii_crypto.decrypt(
            stored["account_no_enc"], table="actor_payment", column="account_no", row_id=UID,
        ) == ACCOUNT_NO
        payout = accounts._read("SELECT id, tax_id, tax_id_enc, tax_id_hmac FROM actor_payouts")[0]
        assert pii_crypto.decrypt(
            payout["tax_id_enc"], table="actor_payouts", column="tax_id", row_id=str(payout["id"]),
        ) == TAX_ID
        assert actors.payment(UID)["tax_id"] == TAX_ID

        assert main(["--count-only"]) == 0
        second = json.loads(capsys.readouterr().out)
        assert second["actor_payment"]["updated"] == 0
        assert second["actor_payment"]["already"] == 1
        assert second["actor_payouts"]["updated"] == 0
        assert second["actor_payouts"]["already"] == 1
        assert _raw_payment()["tax_id_enc"] == stored["tax_id_enc"]

        with accounts._tx() as db:
            db.execute("UPDATE actor_payment SET account_no_enc = NULL WHERE user_id = ?", (UID,))
        partial = run(dry_run=False, batch=1)
        assert partial["actor_payment"]["updated"] == 1
        again = _raw_payment()
        assert again["tax_id_enc"] == stored["tax_id_enc"]
        assert pii_crypto.decrypt(
            again["account_no_enc"], table="actor_payment", column="account_no", row_id=UID,
        ) == ACCOUNT_NO
        logged = "\n".join(sink.messages)
        assert TAX_ID not in logged
        assert ACCOUNT_NO not in logged
    finally:
        logging.getLogger("dubbing.pii").removeHandler(sink)
        logging.getLogger("dubbing.pii_backfill").removeHandler(sink)


def test_backfill_conflict_is_idempotent(actor_db):
    now = time.time()
    with accounts._tx() as db:
        db.execute(
            "INSERT INTO actor_payment (user_id, payee_name, tax_id, address, bank, account_no, account_name, updated_at) "
            "VALUES ('b-actor', 'ข', ?, 'ที่อยู่ทดสอบยาวพอ', 'พร้อมเพย์', '1111111111', 'ข', ?),"
            " ('a-actor', 'ก', ?, 'ที่อยู่ทดสอบยาวพอ', 'พร้อมเพย์', '2222222222', 'ก', ?)",
            (TAX_ID, now, TAX_ID, now),
        )
    first = run(dry_run=False, batch=1)
    assert first["actor_payment"]["updated"] == 1
    assert first["actor_payment"]["conflicts"] == 1
    second = run(dry_run=False, batch=1)
    assert second["actor_payment"]["updated"] == 0
    assert second["actor_payment"]["already"] == 1
    assert second["actor_payment"]["conflicts"] == 1
    winner = accounts._read("SELECT user_id, tax_id_enc FROM actor_payment WHERE tax_id_enc IS NOT NULL")
    assert [row["user_id"] for row in winner] == ["a-actor"]
    loser = accounts._read("SELECT tax_id_enc FROM actor_payment WHERE user_id = 'b-actor'")[0]
    assert loser["tax_id_enc"] in (None, "")


def test_backfill_refuses_ephemeral_key(monkeypatch):
    for name in ("PII_ENC_KEYS", "PII_ENC_ACTIVE_VERSION", "PII_HMAC_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PII_ENC_DEV_EPHEMERAL", "1")
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    pii_crypto.reset()
    with pytest.raises(BackfillError):
        run(dry_run=False, batch=10)


def test_pg_rewrite_updates_encrypted_columns():
    sql = _rewrite(
        "INSERT OR REPLACE INTO actor_payment "
        "(user_id, payee_name, tax_id, account_no, tax_id_enc, tax_id_hmac, account_no_enc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    assert "tax_id_enc = EXCLUDED.tax_id_enc" in sql
    assert "tax_id_hmac = EXCLUDED.tax_id_hmac" in sql
    assert "account_no_enc = EXCLUDED.account_no_enc" in sql
    assert "user_id = EXCLUDED.user_id" not in sql


def test_manifests_and_sql_do_not_contain_key_material_or_drop_plaintext():
    deployment = (REPO / "deploy/k8s/api/deployment.yaml").read_text()
    assert "name: pakdee-pii" in deployment
    assert "key: PII_ENC_KEYS" in deployment
    assert "key: PII_ENC_ACTIVE_VERSION" in deployment
    assert "key: PII_HMAC_KEY" in deployment
    assert "secretKeyRef" in deployment
    example = (REPO / "deploy/k8s/pii-secret.example.yaml").read_text()
    assert 'PII_ENC_KEYS: ""' in example
    assert 'PII_HMAC_KEY: ""' in example
    kustomize = (REPO / "deploy/k8s/kustomization.yaml").read_text()
    assert "pii-secret" not in kustomize
    sql = (REPO / "backend/supabase/migrations/20261112010000_actor_pii_columns.sql").read_text().lower()
    assert "tax_id_enc" in sql
    assert "account_no_enc" in sql
    assert "drop column" not in sql
    env = (REPO / ".env.example").read_text()
    for line in env.splitlines():
        if line.startswith("PII_ENC_KEYS=") or line.startswith("PII_HMAC_KEY=") or line.startswith("PII_ENC_ACTIVE_VERSION="):
            assert line.split("=", 1)[1].strip() == ""


class _LogSink(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())
