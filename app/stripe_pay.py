"""ชำระเงินผ่าน Stripe Checkout (PAYMENT_PROVIDER=stripe)

สร้าง Session ตอนซื้อเครดิต/แพ็กเกจ แล้วรอ webhook checkout.session.completed
เรียก accounts.mark_paid ตาม metadata.topup_id
คีย์: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET (จาก https://docs.stripe.com/keys และหน้า Webhooks)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import stripe

from .config import settings

log = logging.getLogger("dubbing.stripe")


class StripeError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def _api_key() -> str:
    key = settings.stripe_secret_key.strip()
    if not key:
        raise StripeError(503, "ยังไม่ได้ตั้ง STRIPE_SECRET_KEY (ดู https://docs.stripe.com/keys)")
    return key


def create_checkout(*, topup_id: str, user_id: str, amount: int, label: str,
                    email: str = "") -> tuple[str, str]:
    """สร้าง Checkout Session คืน (session_id, checkout_url) ยอดเป็นสตางค์ สกุล THB"""
    web = settings.web_url.rstrip("/")
    if not web:
        raise StripeError(503, "ตั้ง WEB_URL ให้ชี้หน้าเว็บก่อนใช้ Stripe")
    if amount < 1000:
        raise StripeError(400, "ยอดชำระต่ำเกินไปสำหรับ Stripe (ขั้นต่ำ 10 บาท)")
    stripe.api_key = _api_key()
    params: dict[str, Any] = {
        "mode": "payment",
        "success_url": f"{web}/promotions?paid={topup_id}",
        "cancel_url": f"{web}/promotions?cancel={topup_id}",
        "client_reference_id": topup_id,
        "metadata": {"topup_id": topup_id, "user_id": user_id},
        "line_items": [{
            "quantity": 1,
            "price_data": {
                "currency": "thb",
                "unit_amount": amount,
                "product_data": {"name": label[:120]},
            },
        }],
        "payment_intent_data": {"metadata": {"topup_id": topup_id, "user_id": user_id}},
    }
    if email:
        params["customer_email"] = email
    try:
        session = stripe.checkout.Session.create(**params)
    except stripe.StripeError as e:
        log.exception("สร้าง Stripe Checkout ไม่สำเร็จ")
        raise StripeError(502, "สร้างหน้าชำระเงิน Stripe ไม่สำเร็จ") from e
    if not session.url or not session.id:
        raise StripeError(502, "Stripe ไม่ส่งลิงก์ชำระเงินกลับมา")
    return session.id, session.url


def _field(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def handle_webhook(payload: bytes, signature: Optional[str]) -> dict:
    """ตรวจลายเซ็นแล้วเติมเครดิตเมื่อชำระสำเร็จ คืน {ok, event, topup_id}"""
    secret = settings.stripe_webhook_secret.strip()
    if not secret:
        raise StripeError(503, "ยังไม่ได้ตั้ง STRIPE_WEBHOOK_SECRET")
    if not signature:
        raise StripeError(400, "ไม่มี Stripe-Signature")
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except ValueError as e:
        raise StripeError(400, "payload ไม่ถูกต้อง") from e
    except stripe.SignatureVerificationError as e:
        raise StripeError(400, "ลายเซ็น webhook ไม่ถูกต้อง") from e

    etype = _field(event, "type")
    data = _field(event, "data")
    obj = _field(data, "object") if data is not None else None
    if etype not in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        return {"ok": True, "event": etype, "topup_id": None}

    meta = _field(obj, "metadata") or {}
    if not isinstance(meta, dict):
        meta = dict(meta) if meta else {}
    topup_id = meta.get("topup_id") or _field(obj, "client_reference_id")
    payment_status = _field(obj, "payment_status")
    amount_total = _field(obj, "amount_total")
    currency = (_field(obj, "currency") or "").lower()
    session_id = _field(obj, "id") or ""

    if not topup_id:
        log.warning("Stripe event %s ไม่มี topup_id session=%s", etype, session_id)
        return {"ok": True, "event": etype, "topup_id": None}
    if payment_status not in (None, "paid"):
        return {"ok": True, "event": etype, "topup_id": topup_id, "skipped": payment_status}

    from . import accounts
    accounts.fulfill_stripe(str(topup_id), session_id=str(session_id),
                            amount_total=amount_total, currency=currency)
    return {"ok": True, "event": etype, "topup_id": topup_id}
