"""เส้นทาง API ของบัญชีผู้ใช้ เครดิต และแพ็กเกจ (accounts.py) ปิดอยู่จนกว่าจะตั้ง AUTH_ENABLED / BILLING_ENABLED

หน้าเว็บส่ง token ของผู้ใช้มาใน header X-User-Token (proxy อ่านจากคุกกี้ httpOnly ให้)
main.access_guard หาผู้ใช้จาก token แล้วเก็บไว้ที่ request.state.user ทุกคำขอ
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import accounts, consent
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


class Profile(BaseModel):
    name: str = Field("", max_length=80, description="ชื่อที่แสดงในระบบ ว่าง = ใช้ชื่อจากบัญชี Google")
    full_name: str = Field(..., max_length=100, description="ชื่อ-นามสกุล")
    phone: str = Field(..., max_length=30)
    account_type: str = Field(..., description="personal = บุคคลทั่วไป, creator = ครีเอเตอร์, business = บริษัท/หน่วยงาน")
    company: str = Field("", max_length=120, description="ชื่อบริษัทหรือหน่วยงาน (จำเป็นเมื่อ account_type = business)")
    use_case: str = Field("", max_length=300, description="ใช้พากย์งานแบบไหน")
    terms_version: Optional[str] = Field(None, max_length=20, description="ฉบับข้อกำหนดที่อ่านและยอมรับ (จำเป็นจนกว่าจะยอมรับฉบับปัจจุบัน)")
    privacy_version: Optional[str] = Field(None, max_length=20, description="ฉบับนโยบายความเป็นส่วนตัวที่อ่านและรับทราบ")
    marketing: Optional[bool] = Field(None, description="รับข่าวสารและโปรโมชัน (ไม่บังคับ)")


class ConsentAccept(BaseModel):
    terms_version: str = Field(..., max_length=20)
    privacy_version: str = Field(..., max_length=20)
    marketing: Optional[bool] = None


class Marketing(BaseModel):
    on: bool


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


class RejectSlip(BaseModel):
    note: str = Field("", max_length=300, description="เหตุผลที่สลิปไม่ผ่าน ผู้ใช้เห็นข้อความนี้")


# ---------------------------------------------------------------- บัญชี
@router.get("/auth/config")
def auth_config():
    """ระบบไหนเปิดอยู่ หน้าเว็บใช้ซ่อนหรือแสดงเมนูเข้าสู่ระบบ"""
    from .config import settings
    return {"auth": accounts.auth_enabled(), "billing": accounts.billing_enabled(),
            "payments": bool(settings.payment_provider), "payment_provider": settings.payment_provider,
            "google_client_id": settings.google_client_id,
            "stripe_publishable_key": settings.stripe_publishable_key if settings.payment_provider == "stripe" else ""}


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


def _client(request: Request) -> tuple[str, str]:
    """IP และเบราว์เซอร์ของผู้กดยอมรับ (หน้าเว็บส่งต่อมาใน x-client-ip / x-client-ua)"""
    ip = request.headers.get("x-client-ip") or (request.client.host if request.client else "")
    return ip, request.headers.get("x-client-ua") or request.headers.get("user-agent") or ""


@router.get("/legal")
def legal():
    """ข้อกำหนดการใช้งานและนโยบายความเป็นส่วนตัวฉบับปัจจุบัน (อ่านได้โดยไม่ต้องล็อกอิน)"""
    return consent.documents()


@router.put("/auth/profile")
def save_profile(body: Profile, request: Request, user=Depends(require_user)):
    """ข้อมูลเบื้องต้นพร้อมยอมรับข้อกำหนดและนโยบาย: ผู้ใช้ต้องทำก่อนใช้งานครั้งแรก (main.access_guard) แก้ภายหลังได้"""
    try:
        if body.terms_version or body.privacy_version:
            consent.accept(user["id"], body.terms_version or "", body.privacy_version or "", body.marketing,
                           *_client(request))
        elif not consent.status(user["id"])["current"]:
            raise AccountError(400, "ต้องยอมรับข้อกำหนดการใช้งานและนโยบายความเป็นส่วนตัวก่อน")
        return accounts.save_profile(user["id"], body.name, body.full_name, body.phone, body.account_type,
                                     body.company, body.use_case)
    except AccountError as e:
        raise _fail(e)


@router.post("/auth/consent")
def accept_consent(body: ConsentAccept, request: Request, user=Depends(require_user)):
    """ยอมรับข้อกำหนดและนโยบายฉบับใหม่ (เมื่อแก้ข้อความแล้วผู้ใช้ต้องยอมรับใหม่)"""
    try:
        consent.accept(user["id"], body.terms_version, body.privacy_version, body.marketing, *_client(request))
    except AccountError as e:
        raise _fail(e)
    return accounts.public_user(accounts.user_by_id(user["id"]))


@router.put("/auth/notify")
def set_notify(body: Marketing, user=Depends(require_user)):
    """เปิดหรือปิดอีเมลแจ้งเตือนเมื่องานรอตรวจบท พากย์เสร็จ หรือล้มเหลว"""
    return accounts.set_notify(user["id"], body.on)


@router.put("/auth/marketing")
def set_marketing(body: Marketing, request: Request, user=Depends(require_user)):
    """เปิดหรือปิดการรับข่าวสาร (ถอนความยินยอมได้ตลอด)"""
    consent.set_marketing(user["id"], body.on, *_client(request))
    return accounts.public_user(accounts.user_by_id(user["id"]))


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


@router.get("/billing/topups", dependencies=[Depends(_need_billing)])
def my_topups(user=Depends(require_user)):
    """รายการเติมเครดิตและแพ็กเกจล่าสุด รวมรายการที่รอสลิป"""
    return accounts.user_payments(user["id"])


@router.post("/billing/topups/{topup_id}/slip", dependencies=[Depends(_need_billing)])
async def upload_slip(topup_id: str, file: UploadFile = File(...), user=Depends(require_user)):
    """แนบรูปสลิป Typhoon OCR อ่านยอด ตรงกับรายการแล้วเติมให้ทันที"""
    from .config import settings
    limit = max(1, settings.slip_max_mb) * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(400, f"รูปสลิปใหญ่เกิน {settings.slip_max_mb} MB")
        chunks.append(chunk)
    try:
        return accounts.submit_slip(user["id"], topup_id, b"".join(chunks))
    except AccountError as e:
        raise _fail(e)


@router.get("/billing/topups/{topup_id}/slip", dependencies=[Depends(_need_billing)])
def slip_image(topup_id: str, user=Depends(require_user)):
    try:
        path, mime, name = accounts.slip_file(topup_id, user["id"], accounts.is_admin(user))
    except AccountError as e:
        raise _fail(e)
    return FileResponse(path, media_type=mime, filename=name)


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


@router.get("/admin/payments", dependencies=[Depends(_need_billing)])
def admin_payments(status: str = "review", _=Depends(require_admin)):
    """คิวสลิป status ว่าง = รายการล่าสุดทุกสถานะ"""
    try:
        return accounts.admin_payments(status)
    except AccountError as e:
        raise _fail(e)


@router.post("/admin/payments/{topup_id}/approve", dependencies=[Depends(_need_billing)])
def admin_approve_payment(topup_id: str, admin=Depends(require_admin)):
    try:
        return accounts.approve_payment(topup_id, admin["email"])
    except AccountError as e:
        raise _fail(e)


@router.post("/admin/payments/{topup_id}/reject", dependencies=[Depends(_need_billing)])
def admin_reject_payment(topup_id: str, body: RejectSlip, admin=Depends(require_admin)):
    try:
        return accounts.reject_payment(topup_id, admin["email"], body.note)
    except AccountError as e:
        raise _fail(e)


@router.post("/admin/users/{user_id}/admin", status_code=204)
def admin_set_admin(user_id: str, body: SetAdmin, admin=Depends(require_admin)):
    """ให้หรือถอดสิทธิ์ผู้ดูแลระบบ"""
    try:
        accounts.set_admin(user_id, body.admin, admin)
    except AccountError as e:
        raise _fail(e)
