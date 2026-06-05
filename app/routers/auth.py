from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.dependencies import get_current_user
from app.schemas.auth import RegisterRequest, InstitutionRegisterRequest, CorporateRegisterRequest, LoginRequest, TokenResponse, UserInfo, RefreshRequest
from app.models.user import User
from app.models.tenant import Tenant
from app.services.auth_service import (
    hash_password, authenticate_user,
    create_access_token, create_refresh_token, decode_token,
    verify_password,
)
from jose import JWTError
import secrets, time, uuid, re as _re

def _slugify(text: str) -> str:
    s = text.lower()
    for a, b in [('ə','e'),('ğ','g'),('ı','i'),('ö','o'),('ü','u'),('ş','s'),('ç','c')]:
        s = s.replace(a, b)
    s = _re.sub(r'[^a-z0-9]+', '-', s).strip('-')[:40]
    return s or 'workspace'

# In-memory reset tokens: {token: {"user_id": ..., "expires": unix_ts}}
_reset_tokens: dict = {}

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Yalnız müəllim qeydiyyatdan keçə bilər
    if req.role != "teacher":
        raise HTTPException(status_code=403, detail="Yalnız müəllimlər qeydiyyatdan keçə bilər")

    # Email mövcuddurmu?
    result = await db.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Bu email artıq qeydiyyatdan keçib")

    # Slug mövcuddurmu?
    result = await db.execute(select(Tenant).where(Tenant.slug == req.tenant.slug))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Bu workspace adı artıq istifadə edilir")

    # Repetitor pulsuz (demo) planda başlayır; digər növlər üçün superadmin aktiv edir
    is_repetitor = req.tenant.type == "repetitor"
    tenant = Tenant(
        name=req.tenant.name,
        slug=req.tenant.slug,
        type=req.tenant.type,
        plan="free",
    )
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        name=req.name,
        email=req.email,
        hashed_password=hash_password(req.password),
        role=req.role,
        is_active=is_repetitor,  # Repetitor: dərhal aktiv (demo), digərləri: superadmin gözləyir
    )
    db.add(user)
    await db.flush()
    await db.commit()

    # Xoş gəldin e-maili
    try:
        from app.services.email_service import send_welcome_email
        await send_welcome_email(user.email, user.name, user.role)
    except Exception:
        pass

    token_data = {"sub": user.id, "tenant_id": tenant.id, "role": user.role}

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        user=UserInfo(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            tenant_plan=tenant.plan,
            tenant_type=tenant.type,
            is_active=user.is_active,
            student_limit=user.student_limit,
        )
    )


@router.post("/register-institution", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register_institution(req: InstitutionRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Müəssisə / kurs mərkəzi qeydiyyatı — corporate admin yaradır, admin aktivləşdirir."""
    # Email unikallığı
    result = await db.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Bu email artıq qeydiyyatdan keçib")

    # Slug yarat + unikallığını yoxla
    base_slug = _slugify(req.institution_name)
    slug = base_slug + '-' + str(uuid.uuid4())[:6]
    while True:
        r = await db.execute(select(Tenant).where(Tenant.slug == slug))
        if not r.scalar_one_or_none():
            break
        slug = base_slug + '-' + str(uuid.uuid4())[:6]

    # Müəssisə növü doğrulaması
    valid_types = {"school", "academy", "corporate"}
    inst_type = req.institution_type if req.institution_type in valid_types else "school"

    # Tenant yarat
    tenant = Tenant(name=req.institution_name.strip(), slug=slug, type=inst_type)
    db.add(tenant)
    await db.flush()

    # Korporativ admin yarat (deaktiv — superadmin aktivləşdirir)
    user = User(
        tenant_id=tenant.id,
        name=req.admin_name.strip(),
        email=req.email,
        hashed_password=hash_password(req.password),
        role="corporate",
        is_active=False,
    )
    db.add(user)
    await db.flush()

    token_data = {"sub": user.id, "tenant_id": tenant.id, "role": user.role}
    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        user=UserInfo(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            tenant_plan=tenant.plan,
            tenant_type=tenant.type,
            is_active=user.is_active,
            student_limit=user.student_limit,
        )
    )


@router.post("/register-corporate", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register_corporate(req: CorporateRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Korporativ şirkət qeydiyyatı — ayrıca endpoint, type='corporate', role='corporate'."""
    # Email unikallığı
    result = await db.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Bu email artıq qeydiyyatdan keçib")

    # Slug avtomatik yarat
    base_slug = _slugify(req.company_name)
    slug = base_slug + '-' + str(uuid.uuid4())[:6]
    while True:
        r = await db.execute(select(Tenant).where(Tenant.slug == slug))
        if not r.scalar_one_or_none():
            break
        slug = base_slug + '-' + str(uuid.uuid4())[:6]

    # Tenant yarat
    tenant = Tenant(name=req.company_name.strip(), slug=slug, type='corporate')
    db.add(tenant)
    await db.flush()

    # Korporativ admin yarat
    user = User(
        tenant_id=tenant.id,
        name=req.admin_name.strip(),
        email=req.email,
        hashed_password=hash_password(req.password),
        role="corporate",
        is_active=False,
    )
    db.add(user)
    await db.flush()
    await db.commit()

    token_data = {"sub": user.id, "tenant_id": tenant.id, "role": user.role}
    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        user=UserInfo(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            tenant_plan=tenant.plan,
            tenant_type=tenant.type,
            is_active=user.is_active,
            student_limit=user.student_limit,
        )
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    from app.models.login_log import LoginLog
    user = await authenticate_user(db, req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Email və ya şifrə yanlışdır")

    # Tenant məlumatı
    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()

    # Log login event
    try:
        log_entry = LoginLog(
            user_id=user.id,
            user_name=user.name,
            user_role=user.role,
            tenant_id=user.tenant_id,
            tenant_name=tenant.name if tenant else None,
            success=1,
        )
        db.add(log_entry)
        await db.commit()
    except Exception:
        pass  # Never fail a login due to logging error

    token_data = {"sub": user.id, "tenant_id": user.tenant_id, "role": user.role}

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        user=UserInfo(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            tenant_id=user.tenant_id,
            tenant_name=tenant.name if tenant else "",
            tenant_plan=tenant.plan if tenant else "free",
            tenant_type=tenant.type if tenant else "repetitor",
            is_active=user.is_active,
            student_limit=user.student_limit,
        )
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(req.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Token növü yanlışdır")
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Refresh token etibarsızdır")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="İstifadəçi tapılmadı")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Hesabınız deaktiv edilib. Müəssisə administratoru ilə əlaqə saxlayın.")

    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()

    token_data = {"sub": user.id, "tenant_id": user.tenant_id, "role": user.role}

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        user=UserInfo(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            tenant_id=user.tenant_id,
            tenant_name=tenant.name if tenant else "",
            tenant_plan=tenant.plan if tenant else "free",
            tenant_type=tenant.type if tenant else "repetitor",
            is_active=user.is_active,
            student_limit=user.student_limit,
        )
    )


class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TestEmailBody(BaseModel):
    email: str


@router.post("/test-email", status_code=200)
async def test_email(body: TestEmailBody):
    """SMTP konfiqurasiyasını yoxla — verilən ünvana test maili göndər."""
    from app.services.email_service import _is_configured, _send_sync, _from_addr
    from app.config import settings as _s
    if not _is_configured():
        return {"configured": False, "sent": False,
                "detail": ".env-də SMTP_USER və SMTP_PASSWORD doldurulmayıb (dev rejim)"}
    try:
        import asyncio
        html = "<h2>Test ✓</h2><p>VarisAcademy e-mail sistemi işləyir. Bu test mesajıdır.</p>"
        await asyncio.to_thread(_send_sync, body.email, "VarisAcademy — Test e-mail", html)
        return {"configured": True, "sent": True, "from": _from_addr(), "to": body.email}
    except Exception as e:
        return {"configured": True, "sent": False, "detail": str(e)}


@router.post("/forgot-password", status_code=200)
async def forgot_password(req: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    # Always return 200 to avoid email enumeration
    if not user:
        return {"message": "Əgər bu email mövcuddursa, sıfırlama kodu göndərildi", "token": None}
    # Generate 6-digit code → e-mail ilə göndər
    token = str(secrets.randbelow(900000) + 100000)  # 6-digit
    _reset_tokens[token] = {"user_id": user.id, "expires": time.time() + 1800}  # 30 min
    from app.services.email_service import send_password_reset_email, _is_configured
    await send_password_reset_email(user.email, user.name, token)
    # DEBUG rejimdə test üçün kodu qaytarırıq; real e-mail varsa qaytarmırıq
    from app.config import settings as _s
    resp = {"message": "Əgər bu email mövcuddursa, sıfırlama kodu e-mailə göndərildi"}
    if _s.DEBUG and not _is_configured():
        resp["token"] = token   # yalnız dev rejim
    return resp


@router.post("/reset-password", status_code=200)
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    entry = _reset_tokens.get(req.token)
    if not entry or time.time() > entry["expires"]:
        raise HTTPException(status_code=400, detail="Kod yanlış və ya vaxtı keçib")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Şifrə ən az 6 simvol olmalıdır")
    result = await db.execute(select(User).where(User.id == entry["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="İstifadəçi tapılmadı")
    user.hashed_password = hash_password(req.new_password)
    await db.commit()
    del _reset_tokens[req.token]
    return {"message": "Şifrə uğurla sıfırlandı"}


@router.post("/change-password", status_code=200)
async def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(req.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Cari şifrə yanlışdır")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Yeni şifrə ən az 6 simvol olmalıdır")
    current_user.hashed_password = hash_password(req.new_password)
    await db.commit()
    return {"message": "Şifrə uğurla dəyişdirildi"}


@router.get("/me", response_model=UserInfo)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cari istifadəçinin profilini backend-dən qaytarır. localStorage cache-indən asılı deyil."""
    result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = result.scalar_one_or_none()
    return UserInfo(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        role=current_user.role,
        tenant_id=current_user.tenant_id,
        tenant_name=tenant.name if tenant else "",
        tenant_plan=tenant.plan if tenant else "free",
        tenant_type=tenant.type if tenant else "repetitor",
        is_active=current_user.is_active,
        student_limit=current_user.student_limit,
    )
