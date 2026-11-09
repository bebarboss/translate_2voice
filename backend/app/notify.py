"""แจ้งเตือนทางอีเมลผ่าน SMTP (Gmail, Resend, SendGrid, Amazon SES ฯลฯ) ตั้ง SMTP_HOST และ MAIL_FROM แล้วถึงจะส่ง
ไม่ได้ตั้ง = ไม่ส่ง (บันทึกลง log อย่างเดียว) ส่งในเธรดแยก คำขอและงานไม่ต้องรอ ส่งไม่สำเร็จแค่บันทึก log

ผู้ใช้ปิดอีเมลแจ้งเตือนงานได้ที่หน้าบัญชี (users.notify_email) อีเมลเรื่องบัญชีนักพากย์และค่าตอบแทนส่งเสมอ
งานที่เสร็จภายใน NOTIFY_MIN_SECONDS ไม่ส่ง (ผู้ใช้น่าจะยังเปิดหน้าดูอยู่)
"""
import html
import logging
import smtplib
import ssl
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Optional

from .config import settings

log = logging.getLogger("dubbing.notify")
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mail")
BRAND = "Thai Dubbing"


def enabled() -> bool:
    return bool(settings.smtp_host and settings.mail_from)


def _link(path: str) -> Optional[str]:
    return f"{settings.web_url.rstrip('/')}{path}" if settings.web_url else None


def _message(to: str, subject: str, lines: list[str], link: Optional[str], button: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((BRAND, settings.mail_from))
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=settings.mail_from.rpartition("@")[2] or None)
    text = "\n\n".join(lines) + (f"\n\n{button}: {link}" if link else "")
    msg.set_content(text + "\n\n— " + BRAND)
    body = "".join(f'<p style="margin:0 0 14px">{html.escape(x)}</p>' for x in lines)
    if link:
        body += (f'<p style="margin:22px 0"><a href="{html.escape(link)}" style="background:#FF8A4C;color:#1a1a1a;'
                 f'padding:11px 20px;border-radius:9px;text-decoration:none;font-weight:600">{html.escape(button)}</a></p>')
    msg.add_alternative(
        f'<div style="font-family:Sarabun,Tahoma,sans-serif;font-size:15px;line-height:1.6;color:#222;max-width:560px">'
        f'{body}<p style="color:#888;font-size:13px;margin-top:28px">— {BRAND}</p></div>', subtype="html")
    return msg


def _deliver(msg: EmailMessage) -> None:
    try:
        if settings.smtp_port == 465:
            smtp = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        with smtp:
            if settings.smtp_port != 465 and smtp.has_extn("starttls"):
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        log.info("mail sent to %s: %s", msg["To"], msg["Subject"])
    except Exception:  # noqa: BLE001 ส่งไม่ได้ไม่ให้กระทบงาน
        log.exception("mail to %s failed", msg["To"])


def send(to: str, subject: str, lines: list[str], path: Optional[str] = None, button: str = "เปิดดู") -> None:
    """ส่งอีเมลในเธรดแยก path = หน้าเว็บที่ลิงก์ไป (ต่อท้าย WEB_URL)"""
    if not to or to.endswith("@deleted.invalid"):
        return
    if not enabled():
        log.info("mail (not configured) to %s: %s", to, subject)
        return
    _pool.submit(_deliver, _message(to, subject, lines, _link(path) if path else None, button))


def _user(uid: Optional[str]):
    from . import accounts
    if not uid or not accounts.auth_enabled():
        return None
    u = accounts.user_by_id(uid)
    return u if u is not None and u["deleted_at"] is None else None


def admins() -> list[str]:
    from . import accounts
    if not accounts.auth_enabled():
        return []
    rows = accounts._read("SELECT email FROM users WHERE admin = 1 AND deleted_at IS NULL")
    return sorted(set(settings.admin_emails) | {r["email"] for r in rows})


# ---------------------------------------------------------------- งาน
def job_event(job_id: str, kind: str, elapsed: float) -> None:
    """kind: review = แปลเสร็จรอตรวจบท, done = พากย์เสร็จ, failed = ล้มเหลว"""
    from .main import store
    job = store.get(job_id)
    u = _user(job.owner if job else None)
    if job is None or u is None or not u["notify_email"]:
        return
    if kind != "failed" and elapsed < settings.notify_min_seconds:
        return
    name = job.filename
    if kind == "review":
        what = "แยกเสียงเสร็จแล้ว เลือกบันทึกเสียงของแต่ละคนลงคลังได้" if job.library else "ถอดเสียงและแปลเสร็จแล้ว รอคุณตรวจบทก่อนพากย์"
        send(u["email"], f"รอตรวจบท: {name}", [f"สวัสดีคุณ{u['name']}", f"งาน “{name}” {what}"], f"/jobs/{job_id}", "ตรวจบท")
    elif kind == "done":
        what = "พากย์เสร็จแล้ว ดาวน์โหลดไฟล์สำหรับโปรแกรมตัดต่อได้" if job.timeline else "พากย์เสร็จแล้ว ดูผลและดาวน์โหลดวิดีโอได้"
        send(u["email"], f"พากย์เสร็จแล้ว: {name}", [f"สวัสดีคุณ{u['name']}", f"งาน “{name}” {what}"], f"/jobs/{job_id}", "ดูผลงาน")
    elif kind == "failed":
        send(u["email"], f"งานไม่สำเร็จ: {name}",
             [f"สวัสดีคุณ{u['name']}", f"งาน “{name}” ทำไม่สำเร็จ: {(job.error or 'ไม่ทราบสาเหตุ').splitlines()[0][:300]}",
              "กดลองใหม่ได้ที่หน้างาน เครดิตของขั้นถอดเสียงที่ไม่สำเร็จคืนให้อัตโนมัติ"], f"/jobs/{job_id}", "เปิดงาน")


# ---------------------------------------------------------------- นักพากย์
def actor_applied(uid: str, stage_name: str) -> None:
    for to in admins():
        send(to, f"ผู้สมัครนักพากย์ใหม่: {stage_name}", [f"“{stage_name}” สมัครเป็นนักพากย์ รอตรวจใบสมัคร"], "/actors", "ตรวจใบสมัคร")


def actor_voice_submitted(uid: str, voice_name: str) -> None:
    from . import actors
    a = actors.actor(uid)
    who = a["stage_name"] if a else ""
    for to in admins():
        send(to, f"เสียงนักพากย์รอตรวจ: {voice_name}", [f"{who} ส่งเสียง “{voice_name}” เข้าคลัง รอตรวจฟังก่อนเปิดให้ผู้ใช้"],
             "/actors", "ตรวจฟังเสียง")


def actor_reviewed(uid: str, approve: bool, note: str) -> None:
    u = _user(uid)
    if u is None:
        return
    lines = [f"สวัสดีคุณ{u['name']}"]
    if approve:
        lines.append("ใบสมัครนักพากย์ของคุณได้รับอนุมัติแล้ว เข้าไปอัดเสียงเข้าคลังได้เลย")
    else:
        lines.append("ใบสมัครนักพากย์ของคุณยังไม่ผ่าน" + (f": {note}" if note else "") + " แก้ไขแล้วสมัครใหม่ได้")
    send(u["email"], "ใบสมัครนักพากย์ได้รับอนุมัติ" if approve else "ผลใบสมัครนักพากย์", lines, "/actor", "ไปหน้านักพากย์")


def voice_reviewed(uid: str, voice_name: str, approve: bool, note: str, bonus: int = 0) -> None:
    u = _user(uid)
    if u is None:
        return
    lines = [f"สวัสดีคุณ{u['name']}"]
    if approve:
        lines.append(f"เสียง “{voice_name}” ผ่านการตรวจแล้ว ผู้ใช้ทุกคนเลือกใช้พากย์ได้ตั้งแต่ตอนนี้")
        if bonus > 0:
            lines.append(f"ได้รับโบนัส {bonus} เครดิตจากการอนุมัติเสียงนี้ (เครดิตเติม ไม่หมดอายุ)")
    else:
        lines.append(f"เสียง “{voice_name}” ยังไม่ผ่านการตรวจ" + (f": {note}" if note else "") + " อัดใหม่แล้วส่งอีกครั้งได้")
    send(u["email"], f"ผลตรวจเสียง: {voice_name}", lines, "/actor", "ไปหน้านักพากย์")


def actor_paid(uid: str, month: str, amount: int, wht: int) -> None:
    u = _user(uid)
    if u is None:
        return
    baht = lambda s: f"{s / 100:,.2f} บาท"  # noqa: E731
    lines = [f"สวัสดีคุณ{u['name']}", f"โอนค่าตอบแทนของเดือน {month} ให้แล้ว {baht(amount - wht)}"]
    if wht:
        lines.append(f"ยอดก่อนหักภาษี {baht(amount)} หักภาษี ณ ที่จ่าย {baht(wht)}")
    send(u["email"], f"โอนค่าตอบแทนเดือน {month} แล้ว", lines, "/actor", "ดูรายละเอียด")
