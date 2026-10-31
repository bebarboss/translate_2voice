"""เส้นทาง API ของบัญชีผู้ใช้ กระเป๋าเงิน และแพ็กเกจ (accounts.py) ปิดอยู่จนกว่าจะตั้ง AUTH_ENABLED / BILLING_ENABLED

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
        raise HTTPException(404, "ระบบกระเป๋าเงินและแพ็กเกจยังไม่เปิดใช้งาน")


def require_user(request: Request):
    _need_auth()
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "กรุณาเข้าสู่ระบบ")
    return user


def require_admin(user=Depends(require_user)):
    if not accounts.is_admin(user["email"]):
        raise HTTPException(403, "เฉพาะผู้ดูแลระบบ")
    return user


class Signup(BaseModel):
    email: str = Field(..., max_length=200)
    password: str = Field(..., max_length=200)
    name: str = Field("", max_length=80)


class Login(BaseModel):
    email: str = Field(..., max_length=200)
    password: str = Field(..., max_length=200)


class PasswordChange(BaseModel):
    old: str = Field(..., max_length=200)
    new: str = Field(..., max_length=200)


class Subscribe(BaseModel):
    plan_id: str


class Topup(BaseModel):
    amount: int = Field(..., description="สตางค์")


class Credit(BaseModel):
    amount: int = Field(..., description="สตางค์ ติดลบ = หักออก")
    note: str = Field("", max_length=200)


# ---------------------------------------------------------------- บัญชี
@router.get("/auth/config")
def auth_config():
    """ระบบไหนเปิดอยู่ หน้าเว็บใช้ซ่อนหรือแสดงเมนูเข้าสู่ระบบ"""
    from .config import settings
    return {"auth": accounts.auth_enabled(), "billing": accounts.billing_enabled(),
            "payments": bool(settings.payment_provider)}


@router.post("/auth/signup", dependencies=[Depends(_need_auth)])
def signup(body: Signup):
    try:
        return accounts.signup(body.email, body.password, body.name)
    except AccountError as e:
        raise _fail(e)


@router.post("/auth/login", dependencies=[Depends(_need_auth)])
def login(body: Login):
    try:
        return accounts.login(body.email, body.password)
    except AccountError as e:
        raise _fail(e)


@router.post("/auth/logout", status_code=204, dependencies=[Depends(_need_auth)])
def logout(x_user_token: Optional[str] = Header(default=None)):
    if x_user_token:
        accounts.logout(x_user_token)


@router.get("/auth/me")
def me(user=Depends(require_user)):
    return accounts.public_user(user)


@router.post("/auth/password", status_code=204)
def change_password(body: PasswordChange, user=Depends(require_user)):
    try:
        accounts.change_password(user["id"], body.old, body.new)
    except AccountError as e:
        raise _fail(e)


# ---------------------------------------------------------------- กระเป๋าเงินและแพ็กเกจ
@router.get("/billing/plans", dependencies=[Depends(_need_billing)])
def plans():
    return {"plans": [p.__dict__ for p in accounts.PLANS], "payg_per_minute": accounts.PAYG_PER_MINUTE}


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
        return accounts.create_topup(user["id"], body.amount)
    except AccountError as e:
        raise _fail(e)


# ---------------------------------------------------------------- ผู้ดูแลระบบ
@router.get("/admin/users")
def admin_users(_=Depends(require_admin)):
    return accounts.all_users()


@router.post("/admin/users/{user_id}/credit", status_code=204, dependencies=[Depends(_need_billing)])
def admin_credit(user_id: str, body: Credit, admin=Depends(require_admin)):
    """ปรับยอดกระเป๋าเงินด้วยมือ (โอนเงินนอกระบบ ชดเชย ฯลฯ)"""
    try:
        accounts.credit(user_id, body.amount, kind="adjust", note=body.note or f"ปรับยอดโดย {admin['email']}")
    except AccountError as e:
        raise _fail(e)
