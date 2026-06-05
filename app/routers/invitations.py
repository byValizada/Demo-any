"""
Dəvət Sistemi Router
---------------------
Müəllim token yaradır → Şagird/valideyn linki açır → Qeydiyyatdan keçir
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_teacher
from app.models.invitation import Invitation
from app.models.user import User
from app.models.student import Student
from app.models.tenant import Tenant
from app.models.class_model import Class
from app.services.auth_service import hash_password, create_access_token, create_refresh_token

router = APIRouter(prefix="/invitations", tags=["Invitations"])


# ─── Sxemlər ─────────────────────────────────────────────────────────────────

class InvitationCreateRequest(BaseModel):
    role: str = "student"       # student | parent | teacher
    class_id: Optional[str] = None
    expires_hours: int = 48     # Neçə saat keçərlidir


class InvitationCreateResponse(BaseModel):
    token: str
    link: str
    role: str
    expires_at: str


class InvitationVerifyResponse(BaseModel):
    valid: bool
    role: Optional[str] = None
    tenant_name: Optional[str] = None
    class_name: Optional[str] = None
    message: Optional[str] = None


class InvitationUseRequest(BaseModel):
    token: str
    name: str
    email: EmailStr
    password: str


class InvitationUseResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "InviteUserInfo"


class InviteUserInfo(BaseModel):
    id: str
    name: str
    email: str
    role: str
    tenant_id: str
    tenant_name: str
    is_active: bool = True
    student_limit: int = 0


# ─── Endpoint-lər ────────────────────────────────────────────────────────────

@router.post("/create", response_model=InvitationCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    req: InvitationCreateRequest,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """
    Müəllim/admin üçün: dəvət tokeni yarat.
    """
    if req.role not in ("student", "parent", "teacher"):
        raise HTTPException(status_code=400, detail="Rol yalnız student, parent və ya teacher ola bilər")

    # Sinif mövcuddurmu? (əgər göndərilibsə)
    if req.class_id:
        result = await db.execute(
            select(Class).where(
                Class.id == req.class_id,
                Class.tenant_id == current_user.tenant_id,
            )
        )
        cls = result.scalar_one_or_none()
        if not cls:
            raise HTTPException(status_code=404, detail="Sinif tapılmadı")

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=req.expires_hours)

    invitation = Invitation(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        class_id=req.class_id,
        role=req.role,
        token=token,
        expires_at=expires_at,
    )
    db.add(invitation)
    await db.flush()

    link = f"/join/{token}"

    return InvitationCreateResponse(
        token=token,
        link=link,
        role=req.role,
        expires_at=expires_at.isoformat(),
    )


@router.get("/verify/{token}", response_model=InvitationVerifyResponse)
async def verify_invitation(token: str, db: AsyncSession = Depends(get_db)):
    """
    Public endpoint — tokenin keçərli olub-olmadığını yoxla.
    """
    result = await db.execute(select(Invitation).where(Invitation.token == token))
    inv = result.scalar_one_or_none()

    if not inv:
        return InvitationVerifyResponse(valid=False, message="Token tapılmadı")

    if inv.used:
        return InvitationVerifyResponse(valid=False, message="Bu dəvət artıq istifadə edilib")

    now = datetime.now(timezone.utc)
    expires = inv.expires_at if inv.expires_at.tzinfo else inv.expires_at.replace(tzinfo=timezone.utc)
    if now > expires:
        return InvitationVerifyResponse(valid=False, message="Dəvətin müddəti bitib")

    # Tenant məlumatı
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == inv.tenant_id))
    tenant = tenant_result.scalar_one_or_none()

    # Sinif məlumatı (varsa)
    class_name = None
    if inv.class_id:
        cls_result = await db.execute(select(Class).where(Class.id == inv.class_id))
        cls = cls_result.scalar_one_or_none()
        class_name = cls.name if cls else None

    return InvitationVerifyResponse(
        valid=True,
        role=inv.role,
        tenant_name=tenant.name if tenant else None,
        class_name=class_name,
    )


@router.post("/use", response_model=InvitationUseResponse, status_code=status.HTTP_201_CREATED)
async def use_invitation(req: InvitationUseRequest, db: AsyncSession = Depends(get_db)):
    """
    Public endpoint — dəvət tokeni ilə yeni istifadəçi qeydiyyatı.
    İstifadəçi + tələbə profili yaradılır, token istifadə edilmiş kimi işarələnir.
    """
    # Token tap
    result = await db.execute(select(Invitation).where(Invitation.token == req.token))
    inv = result.scalar_one_or_none()

    if not inv:
        raise HTTPException(status_code=404, detail="Token tapılmadı")

    if inv.used:
        raise HTTPException(status_code=400, detail="Bu dəvət artıq istifadə edilib")

    now = datetime.now(timezone.utc)
    expires = inv.expires_at if inv.expires_at.tzinfo else inv.expires_at.replace(tzinfo=timezone.utc)
    if now > expires:
        raise HTTPException(status_code=400, detail="Dəvətin müddəti bitib")

    # Email mövcuddurmu?
    email_result = await db.execute(select(User).where(User.email == req.email))
    if email_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Bu email artıq qeydiyyatdan keçib")

    # İstifadəçi yarat
    user = User(
        tenant_id=inv.tenant_id,
        name=req.name,
        email=req.email,
        hashed_password=hash_password(req.password),
        role=inv.role,
    )
    db.add(user)
    await db.flush()

    # Şagird profili yarat (rol student olarsa)
    if inv.role == "student":
        student = Student(
            user_id=user.id,
            class_id=inv.class_id,
        )
        db.add(student)
        await db.flush()

    # Tokeni istifadə edilmiş kimi işarələ
    inv.used = True
    inv.used_by = user.id
    await db.flush()

    # Tenant adını al
    tenant_res = await db.execute(select(Tenant).where(Tenant.id == inv.tenant_id))
    tenant = tenant_res.scalar_one_or_none()

    token_data = {"sub": user.id, "tenant_id": inv.tenant_id, "role": user.role}

    return InvitationUseResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        user=InviteUserInfo(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            tenant_id=inv.tenant_id,
            tenant_name=tenant.name if tenant else "",
            is_active=user.is_active,
            student_limit=user.student_limit,
        ),
    )
