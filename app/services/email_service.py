"""
E-mail servisi — SMTP üzərindən göndərmə.
SMTP konfiqurasiya olunmayıbsa "dev rejim": e-mail konsola + sent_emails.log faylına yazılır.
"""
import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)
OUTBOX = Path("sent_emails.log")


def _is_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)


def _from_addr() -> str:
    # SMTP_FROM boşdursa göndərən kimi SMTP_USER istifadə olunur
    return (settings.SMTP_FROM or settings.SMTP_USER or "noreply@varisacademy.az").strip()


def _send_sync(to: str, subject: str, html: str) -> None:
    sender = _from_addr()
    # App Password-dakı təsadüfi boşluqları təmizlə
    password = settings.SMTP_PASSWORD.replace(" ", "")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.EMAIL_FROM_NAME, sender))
    msg["To"] = to
    msg["Reply-To"] = sender
    # Plain-text + HTML (düz mətn spam filtrini azaldır; HTML sonda → üstünlük)
    msg.attach(MIMEText(_strip_html(html), "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
        server.starttls()
        server.login(settings.SMTP_USER, password)
        server.sendmail(sender, [to], msg.as_string())


async def send_email(to: str, subject: str, html: str) -> bool:
    """E-mail göndər. Konfiqurasiya yoxdursa dev-rejimdə log-a yazır. True qaytarır."""
    if not _is_configured():
        line = f"\n{'='*60}\n[DEV E-MAIL] {datetime.now():%Y-%m-%d %H:%M}\nTo: {to}\nSubject: {subject}\n{'-'*60}\n{_strip_html(html)}\n{'='*60}\n"
        try:
            with OUTBOX.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass
        logger.info(f"[DEV E-MAIL] → {to} | {subject}")
        return True
    try:
        await asyncio.to_thread(_send_sync, to, subject, html)
        logger.info(f"E-mail göndərildi: {to} | {subject}")
        return True
    except Exception as e:
        logger.error(f"E-mail xətası ({to}): {e}")
        return False


def _strip_html(html: str) -> str:
    import re
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


# ── Şablonlar ──────────────────────────────────────────────────────────────────

def _wrap(title: str, body: str, button_text: str = "", button_url: str = "") -> str:
    btn = ""
    if button_text and button_url:
        btn = f'<div style="text-align:center;margin:24px 0"><a href="{button_url}" style="display:inline-block;background:#2196f3;color:#fff;text-decoration:none;padding:12px 28px;border-radius:10px;font-weight:700">{button_text}</a></div>'
    return f"""<div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden">
  <div style="background:linear-gradient(135deg,#2196f3,#1a56a0);padding:22px 28px">
    <div style="color:#fff;font-size:20px;font-weight:800;letter-spacing:-.02em">⚡ {settings.EMAIL_FROM_NAME}</div>
  </div>
  <div style="padding:28px">
    <h2 style="margin:0 0 14px;font-size:18px;color:#1a1a2e">{title}</h2>
    <div style="font-size:14px;line-height:1.6;color:#374151">{body}</div>
    {btn}
  </div>
  <div style="padding:16px 28px;border-top:1px solid #f1f5f9;font-size:11px;color:#94a3b8;text-align:center">
    © {datetime.now().year} {settings.EMAIL_FROM_NAME}. Bu avtomatik mesajdır.
  </div>
</div>"""


async def send_welcome_email(to: str, name: str, role: str) -> bool:
    role_az = {"teacher": "müəllim", "student": "şagird", "parent": "valideyn", "corporate": "korporativ"}.get(role, "")
    body = (f"Salam, <b>{name}</b>!<br><br>"
            f"{settings.EMAIL_FROM_NAME} platformasına {role_az} kimi qoşulduğunuz üçün təşəkkür edirik. "
            f"Hesabınız aktivdir — daxil olub başlaya bilərsiniz.")
    return await send_email(to, f"{settings.EMAIL_FROM_NAME} — Xoş gəldiniz! 🎉",
                            _wrap("Xoş gəldiniz!", body, "Platformaya daxil ol", settings.APP_URL))


async def send_password_reset_email(to: str, name: str, code: str) -> bool:
    body = (f"Salam, <b>{name}</b>!<br><br>"
            f"Şifrənizi sıfırlamaq üçün aşağıdakı kodu daxil edin. Kod <b>30 dəqiqə</b> etibarlıdır.<br><br>"
            f'<div style="text-align:center;font-size:30px;font-weight:800;letter-spacing:6px;color:#2196f3;background:#eff6ff;border-radius:10px;padding:16px">{code}</div><br>'
            f"Əgər bu sorğunu siz etməmisinizsə, bu məktubu nəzərə almayın.")
    return await send_email(to, f"{settings.EMAIL_FROM_NAME} — Şifrə bərpası kodu",
                            _wrap("Şifrə bərpası", body))


async def send_event_email(to: str, name: str, title: str, message: str,
                           button_text: str = "Bax", button_url: str = "") -> bool:
    body = f"Salam, <b>{name}</b>!<br><br>{message}"
    return await send_email(to, f"{settings.EMAIL_FROM_NAME} — {title}",
                            _wrap(title, body, button_text, button_url or settings.APP_URL))
