"""เติม ciphertext ให้แถวนักพากย์ที่ยังมีแต่ค่าเดิม

พิมพ์จำนวนแถวอย่างเดียว ไม่พิมพ์เลขผู้เสียภาษี เลขบัญชี หรือ ciphertext
รันซ้ำได้: แถวที่ ciphertext ครบแล้วไม่ถูกเขียนใหม่
"""
from __future__ import annotations

import argparse
import json
import sys

from . import accounts, actors, pii_crypto

_PAYMENT_COLS = ("tax_id_enc", "tax_id_hmac", "account_no_enc")
_PAYOUT_COLS = ("tax_id_enc", "tax_id_hmac")


class BackfillError(RuntimeError):
    """งานเติมค่าล้มเหลวโดยไม่มีค่าต้นฉบับในข้อความ"""


def run(*, dry_run: bool, batch: int) -> dict:
    if batch < 1:
        raise BackfillError("--batch must be a positive integer")
    ring = pii_crypto.require_keys()
    if ring.ephemeral:
        raise BackfillError(
            "refusing to backfill with a process-local key. "
            "Set PII_ENC_KEYS, PII_ENC_ACTIVE_VERSION, and PII_HMAC_KEY."
        )
    _require_columns()
    payment_stats, payment_writes = _plan_payment(dry_run=dry_run)
    payout_stats, payout_writes = _plan_payouts(dry_run=dry_run)
    if not dry_run:
        _write_batches(
            "UPDATE actor_payment SET tax_id_enc = ?, tax_id_hmac = ?, account_no_enc = ? WHERE user_id = ?",
            payment_writes,
            batch,
        )
        _write_batches(
            "UPDATE actor_payouts SET tax_id_enc = ?, tax_id_hmac = ? WHERE id = ?",
            payout_writes,
            batch,
        )
    return {
        "dry_run": dry_run,
        "batch": batch,
        "actor_payment": payment_stats,
        "actor_payouts": payout_stats,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill actor tax_id and account_no ciphertext. Prints aggregate counts only.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count rows that would change and do not write.")
    parser.add_argument("--batch", type=int, default=200, help="Rows per transaction (default 200).")
    parser.add_argument(
        "--count-only",
        action="store_true",
        help="Print aggregate counts only. This is the only output mode; plaintext is never printed.",
    )
    args = parser.parse_args(argv)
    try:
        report = run(dry_run=args.dry_run, batch=args.batch)
    except (BackfillError, pii_crypto.PiiCryptoError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"error": "backfill failed", "type": type(exc).__name__}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


def _present(value) -> bool:
    return value is not None and str(value) != ""


def _ascii_digits(value: str) -> str | None:
    """ตัดช่องว่างและขีด ถ้าเหลือไม่ใช่เลข 0-9 ทั้งก้อน ให้ข้ามแถวโดยไม่คืนค่าเดิม"""
    if not value:
        return ""
    try:
        return pii_crypto.normalize_tax_id(value)
    except pii_crypto.PiiCryptoError:
        return None


def _require_columns() -> None:
    actors._init()
    missing = []
    for table, needed in (("actor_payment", _PAYMENT_COLS), ("actor_payouts", _PAYOUT_COLS)):
        have = _column_names(table)
        lack = [name for name in needed if name not in have]
        if lack:
            missing.append(f"{table} missing {', '.join(lack)}")
    if missing:
        raise BackfillError(
            "encrypted columns are missing (" + "; ".join(missing) + "). "
            "Apply backend/supabase/migrations/20261112010000_actor_pii_columns.sql on Postgres first. "
            "Plaintext columns are not dropped by that file."
        )


def _column_names(table: str) -> set[str]:
    if table not in ("actor_payment", "actor_payouts"):
        raise BackfillError("unexpected table")
    return {row["name"] for row in accounts._read(f"PRAGMA table_info({table})")}


def _plan_payment(*, dry_run: bool) -> tuple[dict, list]:
    rows = [dict(row) for row in accounts._read(
        "SELECT user_id, tax_id, account_no, tax_id_enc, tax_id_hmac, account_no_enc "
        "FROM actor_payment ORDER BY user_id"
    )]
    stats = {"scanned": len(rows), "updated": 0, "already": 0, "skipped_empty": 0, "conflicts": 0}
    claimed: dict[str, str] = {}
    for row in rows:
        digest = row["tax_id_hmac"] or ""
        if digest:
            claimed.setdefault(digest, str(row["user_id"]))
    writes: list[tuple] = []
    for row in rows:
        uid = str(row["user_id"])
        tax_id = _ascii_digits(row["tax_id"] or "")
        account_no = _ascii_digits(row["account_no"] or "")
        if tax_id is None or account_no is None:
            stats["skipped_empty"] += 1
            continue
        if not tax_id and not account_no:
            stats["skipped_empty"] += 1
            continue
        digest = ""
        if tax_id:
            digest = row["tax_id_hmac"] or pii_crypto.tax_id_hmac(tax_id)
            owner = claimed.get(digest)
            if owner is not None and owner != uid:
                stats["conflicts"] += 1
                continue
            claimed.setdefault(digest, uid)
        need_tax = bool(tax_id) and (not _present(row["tax_id_enc"]) or not _present(row["tax_id_hmac"]))
        need_account = bool(account_no) and not _present(row["account_no_enc"])
        if not need_tax and not need_account:
            stats["already"] += 1
            continue
        stats["updated"] += 1
        if dry_run:
            continue
        tax_enc = row["tax_id_enc"] if _present(row["tax_id_enc"]) else None
        tax_hmac = row["tax_id_hmac"] if _present(row["tax_id_hmac"]) else None
        account_enc = row["account_no_enc"] if _present(row["account_no_enc"]) else None
        if tax_id and not _present(tax_enc):
            tax_enc = pii_crypto.encrypt(tax_id, table="actor_payment", column="tax_id", row_id=uid)
        if tax_id and not _present(tax_hmac):
            tax_hmac = digest
        if account_no and not _present(account_enc):
            account_enc = pii_crypto.encrypt(
                account_no, table="actor_payment", column="account_no", row_id=uid,
            )
        writes.append((tax_enc, tax_hmac, account_enc, uid))
    return stats, writes


def _plan_payouts(*, dry_run: bool) -> tuple[dict, list]:
    rows = [dict(row) for row in accounts._read(
        "SELECT id, tax_id, tax_id_enc, tax_id_hmac FROM actor_payouts ORDER BY id"
    )]
    stats = {"scanned": len(rows), "updated": 0, "already": 0, "skipped_empty": 0, "conflicts": 0}
    writes: list[tuple] = []
    for row in rows:
        tax_id = _ascii_digits(row["tax_id"] or "")
        if tax_id is None or not tax_id:
            stats["skipped_empty"] += 1
            continue
        if _present(row["tax_id_enc"]) and _present(row["tax_id_hmac"]):
            stats["already"] += 1
            continue
        stats["updated"] += 1
        if dry_run:
            continue
        row_id = str(row["id"])
        tax_enc = row["tax_id_enc"] if _present(row["tax_id_enc"]) else pii_crypto.encrypt(
            tax_id, table="actor_payouts", column="tax_id", row_id=row_id,
        )
        tax_hmac = row["tax_id_hmac"] if _present(row["tax_id_hmac"]) else pii_crypto.tax_id_hmac(tax_id)
        writes.append((tax_enc, tax_hmac, row["id"]))
    return stats, writes


def _write_batches(sql: str, rows: list, batch: int) -> None:
    for start in range(0, len(rows), batch):
        try:
            with accounts._tx() as db:
                for params in rows[start:start + batch]:
                    db.execute(sql, params)
        except Exception as exc:
            raise BackfillError("backfill write failed") from exc


if __name__ == "__main__":
    raise SystemExit(main())
