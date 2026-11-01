"""เส้นทาง API ของบัญชีผู้ใช้ เครดิต และแพ็กเกจ (accounts.py) ปิดอยู่จนกว่าจะตั้ง AUTH_ENABLED / BILLING_ENABLED

หน้าเว็บส่ง token ของผู้ใช้มาใน header X-User-Token (proxy อ่านจากคุกกี้ httpOnly ให้)
main.access_guard หาผู้ใช้จาก token แล้วเก็บไว้ที่ request.state.user ทุกคำขอ
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import accounts
from .accounts import AccountError

router = APIRouter()


def _fail(e: AccountError) -> HTTPException:
    return HTTPException(e.status, str(e))


def _need_auth() -> None:
    if not accounts.auth_enabled():
        raise HTTPException(404, "ระบบบัญชีผู้ใช้ยังไม่เปิดใช้งาน")


def _need_billing() -> None:
    if not accounts.billing_enabled():
        raise HTTPException(404, "ระบบเครดิตและแพ็กเกจยังไม่เปิดใช้งาน")


def require_user(request: Request):
    _need_auth()
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "กรุณาเข้าสู่ระบบ")
    return user


def require_admin(user=Depends(require_user)):
    if not accounts.is_admin(user):
        raise HTTPException(403, "เฉพาะผู้ดูแลระบบ")
    return user


class GoogleLogin(BaseModel):
    credential: str = Field(..., max_length=4096, description="ID token จากปุ่มเข้าสู่ระบบด้วย Google")


class Subscribe(BaseModel):
    plan_id: str


class Topup(BaseModel):
    credits: int = Field(..., description="จำนวนเครดิตที่ซื้อ")


class Credit(BaseModel):
    credits: float = Field(..., description="เครดิตเติม ทศนิยมได้ 2 ตำแหน่ง ติดลบ = หักออก")
    note: str = Field("", max_length=200)


class AddCard(BaseModel):
    token: str = Field(..., max_length=200, description="token บัตรจากสคริปต์ของผู้ให้บริการชำระเงิน")


class SetAdmin(BaseModel):
    admin: bool


class GrantPlan(BaseModel):
    plan_id: str


# ---------------------------------------------------------------- บัญชี
@router.get("/auth/config")
def auth_config():
    """ระบบไหนเปิดอยู่ หน้าเว็บใช้ซ่อนหรือแสดงเมนูเข้าสู่ระบบ"""
    from .config import settings
    return {"auth": accounts.auth_enabled(), "billing": accounts.billing_enabled(),
            "payments": bool(settings.payment_provider), "google_client_id": settings.google_client_id}


@router.post("/auth/google", dependencies=[Depends(_need_auth)])
def google_login(body: GoogleLogin):
    """สมัครหรือเข้าสู่ระบบด้วยบัญชี Google (ไม่มีรหัสผ่าน)"""
    try:
        return accounts.google_login(body.credential)
    except AccountError as e:
        raise _fail(e)


@router.post("/auth/logout", status_code=204, dependencies=[Depends(_need_auth)])
def logout(x_user_token: Optional[str] = Header(default=None)):
    if x_user_token:
        accounts.logout(x_user_token)


@router.get("/auth/me")
def me(user=Depends(require_user)):
    return accounts.public_user(user)


# ---------------------------------------------------------------- เครดิตและแพ็กเกจ
@router.get("/billing/plans", dependencies=[Depends(_need_billing)])
def plans():
    return {"plans": [p.__dict__ for p in accounts.PLANS], "credit_price": accounts.CREDIT_PRICE,
            "credit_packs": list(accounts.CREDIT_PACKS), "card_bonus": accounts.CARD_BONUS}


@router.get("/billing/wallet", dependencies=[Depends(_need_billing)])
def wallet(user=Depends(require_user)):
    return accounts.wallet(user["id"])


@router.post("/billing/subscribe", dependencies=[Depends(_need_billing)])
def subscribe(body: Subscribe, user=Depends(require_user)):
    try:
        return accounts.subscribe(user["id"], body.plan_id)
    except AccountError as e:
        raise _fail(e)


@router.post("/billing/topups", dependencies=[Depends(_need_billing)])
def topup(body: Topup, user=Depends(require_user)):
    try:
        return accounts.buy_credits(user["id"], body.credits)
    except AccountError as e:
        raise _fail(e)


@router.get("/billing/cards", dependencies=[Depends(_need_billing)])
def cards(user=Depends(require_user)):
    return accounts.cards(user["id"])


@router.post("/billing/cards", dependencies=[Depends(_need_billing)])
def add_card(body: AddCard, user=Depends(require_user)):
    """ผูกบัตร ครั้งแรกได้เครดิตฟรี (accounts.CARD_BONUS)"""
    try:
        return accounts.add_card(user["id"], body.token)
    except AccountError as e:
        raise _fail(e)


@router.delete("/billing/cards/{card_id}", status_code=204, dependencies=[Depends(_need_billing)])
def remove_card(card_id: str, user=Depends(require_user)):
    try:
        accounts.remove_card(user["id"], card_id)
    except AccountError as e:
        raise _fail(e)


# ---------------------------------------------------------------- ผู้ดูแลระบบ
@router.get("/admin/users")
def admin_users(_=Depends(require_admin)):
    return accounts.all_users()


@router.post("/admin/users/{user_id}/credit", status_code=204, dependencies=[Depends(_need_billing)])
def admin_credit(user_id: str, body: Credit, admin=Depends(require_admin)):
    """เพิ่มหรือหักเครดิตเติมด้วยมือ (รับโอนนอกระบบ ชดเชย ฯลฯ)"""
    try:
        accounts.credit(user_id, body.credits, kind="adjust", note=body.note or f"ปรับเครดิตโดย {admin['email']}")
    except AccountError as e:
        raise _fail(e)


@router.post("/admin/users/{user_id}/plan", status_code=204, dependencies=[Depends(_need_billing)])
def admin_plan(user_id: str, body: GrantPlan, admin=Depends(require_admin)):
    """ให้แพ็กเกจโดยไม่ต้องชำระ"""
    try:
        accounts.grant_plan(user_id, body.plan_id, admin["email"])
    except AccountError as e:
        raise _fail(e)


@router.post("/admin/users/{user_id}/admin", status_code=204)
def admin_set_admin(user_id: str, body: SetAdmin, admin=Depends(require_admin)):
    """ให้หรือถอดสิทธิ์ผู้ดูแลระบบ"""
    try:
        accounts.set_admin(user_id, body.admin, admin)
    except AccountError as e:
        raise _fail(e)
