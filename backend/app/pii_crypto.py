"""เข้ารหัสข้อมูลรับเงินของนักพากย์ขณะเก็บ (AES-256-GCM) และดัชนีค้นเลขผู้เสียภาษี (HMAC-SHA256)

รูปแบบที่เก็บ: ``v{รุ่น}:{base64(nonce 12 ไบต์ || ciphertext)}``
nonce สุ่มใหม่ทุกค่า คีย์รุ่นเก่าถอดค่าที่เขียนไปแล้วได้ รุ่นที่ใช้อยู่ตั้งด้วย ``PII_ENC_ACTIVE_VERSION``

ตัวแปรสภาพแวดล้อม (ค่าจริงอยู่ใน Kubernetes Secret ``pakdee-pii`` ห้ามใส่ในรีโป):
- ``PII_ENC_KEYS`` = ``1:<base64 ของ 32 ไบต์>,2:<base64>``
- ``PII_ENC_ACTIVE_VERSION`` = ``1`` (หรือ ``v1``)
- ``PII_HMAC_KEY`` = base64 ของ 32 ไบต์ สำหรับ HMAC เลขผู้เสียภาษี
- ``PII_ENC_DEV_EPHEMERAL=1`` สร้างคีย์ชั่วคราวในโปรเซสนี้เท่านั้น (เทส / เครื่องพัฒนา)
  บน Kubernetes ธงนี้ใช้ไม่ได้ ถ้าไม่มีคีย์จริงโปรเซสต้องหยุด

AAD ผูกตาราง คอลัมน์ และรหัสแถว เพื่อกันย้าย ciphertext ไปแถวหรือคอลัมน์อื่น
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import threading
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger("dubbing.pii")

_NONCE_LEN = 12
_KEY_LEN = 32
_STORED = re.compile(r"^v([1-9][0-9]*):([A-Za-z0-9+/]+=*)$")
_VERSION_TOKEN = re.compile(r"^v?([1-9][0-9]*)$")

_lock = threading.Lock()
_ring: "KeyRing | None" = None


class PiiCryptoError(RuntimeError):
    """คีย์หาย รูปแบบ ciphertext เสีย หรือถอดรหัสไม่ผ่าน ไม่ใส่ค่าต้นฉบับในข้อความ"""


@dataclass(frozen=True)
class KeyRing:
    versions: dict[int, bytes]
    active: int
    hmac_key: bytes
    ephemeral: bool


def reset() -> None:
    """ล้างแคชคีย์ ใช้ในเทสหลังเปลี่ยนตัวแปรสภาพแวดล้อม"""
    global _ring
    with _lock:
        _ring = None


def require_keys() -> KeyRing:
    """โหลดคีย์ หรือหยุดทันทีถ้าไม่มีคีย์ในโปรดักชัน"""
    return _load()


def encrypt(plaintext: str, *, table: str, column: str, row_id: str) -> str:
    ring = _load()
    key = ring.versions[ring.active]
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), _aad(table, column, row_id))
    blob = base64.b64encode(nonce + ciphertext).decode("ascii")
    return f"v{ring.active}:{blob}"


def decrypt(stored: str, *, table: str, column: str, row_id: str) -> str:
    ring = _load()
    match = _STORED.match((stored or "").strip())
    if match is None:
        raise PiiCryptoError("ciphertext is missing a supported key-version prefix")
    version = int(match.group(1))
    key = ring.versions.get(version)
    if key is None:
        raise PiiCryptoError(f"no encryption key is loaded for version v{version}")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except Exception as exc:
        raise PiiCryptoError("ciphertext encoding is invalid") from exc
    if len(raw) < _NONCE_LEN + 16:
        raise PiiCryptoError("ciphertext is truncated")
    nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    try:
        plain = AESGCM(key).decrypt(nonce, ciphertext, _aad(table, column, row_id))
    except Exception as exc:
        raise PiiCryptoError("decryption failed") from exc
    return plain.decode("utf-8")


def normalize_tax_id(value: str) -> str:
    """ตัดช่องว่างและขีด แล้วต้องเหลือเลข ASCII 0-9 ทั้งก้อน

    ไม่แปลงเลขไทยหรือเลขเต็มความกว้าง และไม่ตัดทิ้งแล้วแฮชส่วนที่เหลือ
    """
    digits = re.sub(r"[\s-]", "", value or "")
    if not digits or re.fullmatch(r"[0-9]+", digits) is None:
        raise PiiCryptoError("tax id must be ASCII digits after spaces and hyphens are removed")
    return digits


def tax_id_hmac(value: str) -> str:
    digits = normalize_tax_id(value)
    ring = _load()
    return hmac.new(ring.hmac_key, digits.encode("ascii"), hashlib.sha256).hexdigest()


def _aad(table: str, column: str, row_id: str) -> bytes:
    if not table or not column or row_id is None or row_id == "":
        raise PiiCryptoError("encryption requires a table, column, and row id")
    return f"{table}:{column}:{row_id}".encode("utf-8")


def _in_kubernetes() -> bool:
    return bool(os.getenv("KUBERNETES_SERVICE_HOST", "").strip())


def _dev_ephemeral_requested() -> bool:
    return os.getenv("PII_ENC_DEV_EPHEMERAL", "").strip().lower() in ("1", "true", "yes", "on")


def _load() -> KeyRing:
    global _ring
    with _lock:
        if _ring is not None:
            return _ring
        keys_raw = os.getenv("PII_ENC_KEYS", "").strip()
        active_raw = os.getenv("PII_ENC_ACTIVE_VERSION", "").strip()
        hmac_raw = os.getenv("PII_HMAC_KEY", "").strip()
        if keys_raw or active_raw or hmac_raw:
            if not (keys_raw and active_raw and hmac_raw):
                raise PiiCryptoError(
                    "PII encryption is misconfigured. Set all of PII_ENC_KEYS, "
                    "PII_ENC_ACTIVE_VERSION, and PII_HMAC_KEY. Refusing to start with a partial key set."
                )
            ring = _parse(keys_raw, active_raw, hmac_raw)
            log.info(
                "pii encryption ready active=v%s versions=%s",
                ring.active,
                ",".join(str(v) for v in sorted(ring.versions)),
            )
            _ring = ring
            return ring
        if _dev_ephemeral_requested() and not _in_kubernetes():
            ring = _ephemeral()
            log.warning(
                "PII_ENC_DEV_EPHEMERAL is set; using a process-local key. "
                "Data encrypted with it cannot be decrypted after this process exits. "
                "Do not set this flag in production."
            )
            _ring = ring
            return ring
        if _dev_ephemeral_requested() and _in_kubernetes():
            raise PiiCryptoError(
                "PII_ENC_DEV_EPHEMERAL is set but ignored in Kubernetes. "
                "Set PII_ENC_KEYS, PII_ENC_ACTIVE_VERSION, and PII_HMAC_KEY from the pakdee-pii Secret."
            )
        raise PiiCryptoError(
            "PII encryption keys are missing. Set PII_ENC_KEYS, PII_ENC_ACTIVE_VERSION, and PII_HMAC_KEY "
            "from the pakdee-pii Kubernetes Secret. "
            "ไม่มีคีย์เข้ารหัสข้อมูลรับเงิน — ตั้งสามตัวนี้จาก Secret pakdee-pii "
            "For a local test or dev API only, set PII_ENC_DEV_EPHEMERAL=1 to use a process-local key. "
            "Refusing to start without keys."
        )


def _parse(keys_raw: str, active_raw: str, hmac_raw: str) -> KeyRing:
    versions: dict[int, bytes] = {}
    for part in keys_raw.split(","):
        item = part.strip()
        if not item:
            continue
        if ":" not in item:
            raise PiiCryptoError(
                "PII_ENC_KEYS entries must look like <version>:<base64> separated by commas"
            )
        version_token, encoded = item.split(":", 1)
        match = _VERSION_TOKEN.match(version_token.strip())
        if match is None:
            raise PiiCryptoError("PII_ENC_KEYS has a version that is not a positive integer")
        version = int(match.group(1))
        if version in versions:
            raise PiiCryptoError(f"PII_ENC_KEYS lists version v{version} more than once")
        versions[version] = _decode_key(encoded, f"PII_ENC_KEYS version v{version}")
    if not versions:
        raise PiiCryptoError("PII_ENC_KEYS did not contain any keys")
    active_match = _VERSION_TOKEN.match(active_raw.strip())
    if active_match is None:
        raise PiiCryptoError("PII_ENC_ACTIVE_VERSION must be a positive integer such as 1 or v1")
    active = int(active_match.group(1))
    if active not in versions:
        raise PiiCryptoError(f"PII_ENC_ACTIVE_VERSION v{active} is not present in PII_ENC_KEYS")
    return KeyRing(
        versions=versions,
        active=active,
        hmac_key=_decode_key(hmac_raw, "PII_HMAC_KEY"),
        ephemeral=False,
    )


def _decode_key(encoded: str, label: str) -> bytes:
    compact = "".join(encoded.split())
    try:
        raw = base64.b64decode(compact, validate=True)
    except Exception as exc:
        raise PiiCryptoError(f"{label} is not valid base64") from exc
    if len(raw) != _KEY_LEN:
        raise PiiCryptoError(f"{label} must decode to exactly {_KEY_LEN} bytes")
    return raw


def _ephemeral() -> KeyRing:
    return KeyRing(versions={1: os.urandom(_KEY_LEN)}, active=1, hmac_key=os.urandom(_KEY_LEN), ephemeral=True)
