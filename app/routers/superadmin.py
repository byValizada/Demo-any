import csv
import io
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_role
from app.models.ai_log import AILog
from app.models.announcement import AnnouncementHistory
from app.models.audit_log import AuditLog
from app.models.exam import Exam, ExamResult
from app.models.homework import Homework
from app.models.invoice import Invoice
from app.models.login_log import LoginLog
from app.models.support_ticket import SupportTicket
from app.models.tenant import Tenant
from app.models.user import User
from app.services.notification_service import send_notification

router = APIRouter(prefix="/superadmin", tags=["Super Admin"])
require_superadmin = require_role("superadmin")


# ── Audit helper ─────────────────────────────────────────────────────────────

async def audit(
    db: AsyncSession,
    actor: User,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    target_name: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """Insert an audit log row. Caller must commit."""
    entry = AuditLog(
        actor_id=actor.id,
        actor_name=actor.name,
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        detail=detail,
    )
    db.add(entry)


# ── Response schemas ────────────────────────────────────────────────────────

class PlatformStats(BaseModel):
    total_tenants: int
    active_tenants: int
    total_users: int
    total_teachers: int
    total_students: int
    total_parents: int
    total_ai_calls: int
    total_tokens_used: int
    pending_teachers: int = 0


class TenantOut(BaseModel):
    id: str
    name: str
    slug: str
    type: str
    is_active: bool
    created_at: datetime
    user_count: int
    student_limit: int = 0
    teacher_limit: int = 0
    ai_daily_limit: int = 0

    model_config = {"from_attributes": True}


class TenantCreate(BaseModel):
    name: str
    slug: str
    type: str = "repetitor"  # repetitor | corporate
    ai_daily_limit: Optional[int] = None


class TenantPatch(BaseModel):
    is_active: Optional[bool] = None
    name: Optional[str] = None
    slug: Optional[str] = None
    student_limit: Optional[int] = None
    teacher_limit: Optional[int] = None
    ai_daily_limit: Optional[int] = None


class UserOut(BaseModel):
    id: str
    tenant_id: str
    tenant_name: Optional[str] = None
    name: str
    email: str
    role: str
    is_active: bool
    student_limit: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class UserPatch(BaseModel):
    is_active: Optional[bool] = None
    student_limit: Optional[int] = None


class AuditLogOut(BaseModel):
    id: str
    actor_name: str
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    target_name: Optional[str] = None
    detail: Optional[str] = None
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


class LoginLogOut(BaseModel):
    id: str
    user_name: str
    user_role: str
    tenant_name: Optional[str] = None
    success: int = 1
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


class AILogOut(BaseModel):
    id: str
    tenant_name: str = "—"
    user_name: str = "—"
    provider: str
    purpose: Optional[str] = None
    tokens_used: int
    latency_ms: int
    success: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AILogPage(BaseModel):
    items: list[AILogOut]
    total: int
    page: int
    limit: int
    pages: int


class ProviderBreakdown(BaseModel):
    provider: str
    calls: int
    tokens: int


class PurposeBreakdown(BaseModel):
    purpose: str
    calls: int


class AIStats(BaseModel):
    total_calls: int
    total_tokens: int
    success_rate: float
    avg_latency_ms: float
    by_provider: list[ProviderBreakdown]
    by_purpose: list[PurposeBreakdown]


class DailyPoint(BaseModel):
    date: str          # YYYY-MM-DD
    logins: int
    ai_calls: int


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/stats/daily", response_model=list[DailyPoint])
async def get_daily_stats(
    days: int = Query(14, ge=7, le=60),
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Returns daily login count + AI calls for the last N days."""
    from datetime import date, timedelta

    today = date.today()
    result: list[DailyPoint] = []

    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        d_str = d.isoformat()

        # Count logins for this day (created_at starts with YYYY-MM-DD)
        login_res = await db.execute(
            select(func.count(LoginLog.id)).where(
                LoginLog.created_at.like(f"{d_str}%")
            )
        )
        logins = login_res.scalar_one()

        # Count AI calls for this day
        ai_res = await db.execute(
            select(func.count(AILog.id)).where(
                func.strftime('%Y-%m-%d', AILog.created_at) == d_str
            )
        )
        ai_calls = ai_res.scalar_one()

        result.append(DailyPoint(date=d_str, logins=logins, ai_calls=ai_calls))

    return result


@router.get("/stats", response_model=PlatformStats)
async def get_platform_stats(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Platform-wide statistics for the superadmin dashboard."""

    # Tenant counts (system tenant xaric)
    tenant_count_result = await db.execute(
        select(func.count(Tenant.id)).where(Tenant.id != "tenant-system")
    )
    total_tenants = tenant_count_result.scalar_one()

    active_tenant_result = await db.execute(
        select(func.count(Tenant.id)).where(
            Tenant.is_active == True,  # noqa: E712
            Tenant.id != "tenant-system",
        )
    )
    active_tenants = active_tenant_result.scalar_one()

    # Users total + by role (superadmin xaric)
    role_results = await db.execute(
        select(User.role, func.count(User.id))
        .where(User.role != "superadmin")
        .group_by(User.role)
    )
    role_rows = role_results.all()

    total_users = sum(row[1] for row in role_rows)
    role_map: dict[str, int] = {row[0]: row[1] for row in role_rows}

    # AI totals
    ai_total_result = await db.execute(select(func.count(AILog.id)))
    total_ai_calls = ai_total_result.scalar_one()

    tokens_result = await db.execute(select(func.coalesce(func.sum(AILog.tokens_used), 0)))
    total_tokens_used = tokens_result.scalar_one()

    # Pending (inactive) teachers
    pending_result = await db.execute(
        select(func.count(User.id)).where(
            User.role == "teacher",
            User.is_active == False,  # noqa: E712
        )
    )
    pending_teachers = pending_result.scalar_one()

    return PlatformStats(
        total_tenants=total_tenants,
        active_tenants=active_tenants,
        total_users=total_users,
        total_teachers=role_map.get("teacher", 0),
        total_students=role_map.get("student", 0),
        total_parents=role_map.get("parent", 0),
        total_ai_calls=total_ai_calls,
        total_tokens_used=total_tokens_used,
        pending_teachers=pending_teachers,
    )


class PendingTeacherOut(BaseModel):
    id: str
    name: str
    email: str
    tenant_name: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/login-logs", response_model=list[LoginLogOut])
async def list_login_logs(
    limit: int = Query(200, ge=1, le=1000),
    role: Optional[str] = Query(None),
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent login events across the platform."""
    from sqlalchemy import desc as sa_desc
    q = select(LoginLog).order_by(sa_desc(LoginLog.created_at)).limit(limit)
    if role:
        q = q.where(LoginLog.user_role == role)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/audit-logs", response_model=list[AuditLogOut])
async def list_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent superadmin audit log entries."""
    from sqlalchemy import desc as sa_desc
    result = await db.execute(
        select(AuditLog).order_by(sa_desc(AuditLog.created_at)).limit(limit)
    )
    return result.scalars().all()


@router.get("/pending-teachers", response_model=list[PendingTeacherOut])
async def list_pending_teachers(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """List all inactive teacher accounts awaiting activation."""

    result = await db.execute(
        select(User, Tenant.name.label("t_name"))
        .outerjoin(Tenant, User.tenant_id == Tenant.id)
        .where(User.role == "teacher", User.is_active == False)  # noqa: E712
        .order_by(User.created_at.desc())
    )
    rows = result.all()
    return [
        PendingTeacherOut(
            id=u.id,
            name=u.name,
            email=u.email,
            tenant_name=t_name,
            created_at=u.created_at,
        )
        for u, t_name in rows
    ]


@router.get("/tenants", response_model=list[TenantOut])
async def list_tenants(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """List tenants with pagination & optional name search."""

    user_count_sq = (
        select(User.tenant_id, func.count(User.id).label("user_count"))
        .group_by(User.tenant_id)
        .subquery()
    )

    q = (
        select(Tenant, func.coalesce(user_count_sq.c.user_count, 0).label("user_count"))
        .outerjoin(user_count_sq, Tenant.id == user_count_sq.c.tenant_id)
        .where(Tenant.id != "tenant-system")  # sistem tenant-ı gizlət
        .order_by(Tenant.created_at.desc())
    )
    if search:
        q = q.where(Tenant.name.ilike(f"%{search}%"))

    result = await db.execute(q.offset(skip).limit(limit))
    rows = result.all()

    return [
        TenantOut(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            type=tenant.type,
            is_active=tenant.is_active,
            created_at=tenant.created_at,
            user_count=user_count,
            student_limit=tenant.student_limit,
            teacher_limit=tenant.teacher_limit,
            ai_daily_limit=tenant.ai_daily_limit or 0,
        )
        for tenant, user_count in rows
    ]


@router.post("/tenants", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new tenant."""

    # Check slug uniqueness
    existing = await db.execute(select(Tenant).where(Tenant.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Slug '{body.slug}' artıq mövcuddur",
        )

    tenant = Tenant(
        name=body.name,
        slug=body.slug,
        type=body.type,
        ai_daily_limit=max(0, body.ai_daily_limit) if body.ai_daily_limit is not None else 0,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)

    return TenantOut(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        type=tenant.type,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
        user_count=0,
        student_limit=tenant.student_limit,
        teacher_limit=tenant.teacher_limit,
        ai_daily_limit=tenant.ai_daily_limit or 0,
    )


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
async def patch_tenant(
    tenant_id: str,
    body: TenantPatch,
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Activate or deactivate a tenant."""

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant tapılmadı")

    if body.is_active is not None:
        tenant.is_active = body.is_active
    if body.name is not None and body.name.strip():
        tenant.name = body.name.strip()
    if body.slug is not None and body.slug.strip():
        new_slug = body.slug.strip().lower()
        # Check uniqueness (excluding current tenant)
        existing_slug = await db.execute(
            select(Tenant).where(Tenant.slug == new_slug, Tenant.id != tenant_id)
        )
        if existing_slug.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"'{new_slug}' slug artıq başqa müəssisədə istifadə olunur")
        tenant.slug = new_slug
    if body.student_limit is not None:
        tenant.student_limit = max(0, body.student_limit)
    if body.teacher_limit is not None:
        tenant.teacher_limit = max(0, body.teacher_limit)
    if body.ai_daily_limit is not None:
        tenant.ai_daily_limit = max(0, body.ai_daily_limit)
    await db.commit()
    await db.refresh(tenant)

    # Fetch user count
    count_result = await db.execute(
        select(func.count(User.id)).where(User.tenant_id == tenant_id)
    )
    user_count = count_result.scalar_one()

    return TenantOut(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        type=tenant.type,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
        user_count=user_count,
        student_limit=tenant.student_limit,
        teacher_limit=tenant.teacher_limit,
        ai_daily_limit=tenant.ai_daily_limit or 0,
    )


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: str,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a tenant and ALL related data (users, exams, students, repetitor data, etc.)."""
    import sqlalchemy as _sa

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant tapılmadı")

    # Bu tenanta aid bütün user ID-ləri
    users_result = await db.execute(_sa.text("SELECT id FROM users WHERE tenant_id = :tid"), {"tid": tenant_id})
    user_ids = [r[0] for r in users_result.fetchall()]

    for uid in user_ids:
        # students → exam_results
        stud_res = await db.execute(_sa.text("SELECT id FROM students WHERE user_id = :uid"), {"uid": uid})
        stud_ids = [r[0] for r in stud_res.fetchall()]
        for sid in stud_ids:
            await db.execute(_sa.text("DELETE FROM exam_results WHERE student_id = :sid"), {"sid": sid})
        await db.execute(_sa.text("DELETE FROM students WHERE user_id = :uid"), {"uid": uid})
        await db.execute(_sa.text("DELETE FROM students WHERE parent_id = :uid"), {"uid": uid})

        # exams → exam_results
        exam_res = await db.execute(_sa.text("SELECT id FROM exams WHERE teacher_id = :uid"), {"uid": uid})
        exam_ids = [r[0] for r in exam_res.fetchall()]
        for eid in exam_ids:
            await db.execute(_sa.text("DELETE FROM exam_results WHERE exam_id = :eid"), {"eid": eid})
        await db.execute(_sa.text("DELETE FROM exams WHERE teacher_id = :uid"), {"uid": uid})

        # classes, homeworks, invitations
        await db.execute(_sa.text("DELETE FROM classes WHERE teacher_id = :uid"), {"uid": uid})
        await db.execute(_sa.text("DELETE FROM homeworks WHERE teacher_id = :uid"), {"uid": uid})
        await db.execute(_sa.text("DELETE FROM invitations WHERE created_by = :uid"), {"uid": uid})

        # ai_logs, notifications, messages
        await db.execute(_sa.text("DELETE FROM ai_logs WHERE user_id = :uid"), {"uid": uid})
        await db.execute(_sa.text("DELETE FROM notifications WHERE user_id = :uid"), {"uid": uid})
        await db.execute(_sa.text("DELETE FROM messages WHERE from_user_id = :uid OR to_user_id = :uid"), {"uid": uid})

        # repetitor cədvəlləri
        rep_stud_res = await db.execute(_sa.text("SELECT id FROM repetitor_students WHERE teacher_id = :uid"), {"uid": uid})
        rep_stud_ids = [r[0] for r in rep_stud_res.fetchall()]
        for rsid in rep_stud_ids:
            await db.execute(_sa.text("DELETE FROM repetitor_sessions WHERE student_id = :sid"), {"sid": rsid})
            await db.execute(_sa.text("DELETE FROM repetitor_payments WHERE student_id = :sid"), {"sid": rsid})
        await db.execute(_sa.text("DELETE FROM repetitor_sessions WHERE teacher_id = :uid"), {"uid": uid})
        await db.execute(_sa.text("DELETE FROM repetitor_payments WHERE teacher_id = :uid"), {"uid": uid})
        await db.execute(_sa.text("DELETE FROM repetitor_subjects WHERE teacher_id = :uid"), {"uid": uid})
        await db.execute(_sa.text("DELETE FROM repetitor_students WHERE teacher_id = :uid"), {"uid": uid})

    # Bütün userləri sil
    await db.execute(_sa.text("DELETE FROM users WHERE tenant_id = :tid"), {"tid": tenant_id})

    # Tenant-ə birbaşa bağlı cədvəllər (user vasitəsilə deyil)
    await db.execute(_sa.text("DELETE FROM classes WHERE tenant_id = :tid"), {"tid": tenant_id})
    await db.execute(_sa.text("DELETE FROM announcement_history WHERE tenant_id = :tid"), {"tid": tenant_id})

    try:
        await audit(db, actor, "delete_tenant", "tenant", tenant.id, tenant.name,
                    f"{len(user_ids)} user(s) and all related data deleted")
    except Exception:
        pass  # audit xətası silinməni bloklamamalıdır

    await db.execute(_sa.text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    await db.commit()


def _build_user_out(u: User, tenant_name: Optional[str] = None) -> UserOut:
    return UserOut(
        id=u.id,
        tenant_id=u.tenant_id,
        tenant_name=tenant_name,
        name=u.name,
        email=u.email,
        role=u.role,
        is_active=u.is_active,
        student_limit=u.student_limit or 0,
        created_at=u.created_at,
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(
    role: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """List users with pagination, role/tenant filter, and optional name/email search."""

    q = (
        select(User, Tenant.name.label("t_name"))
        .outerjoin(Tenant, User.tenant_id == Tenant.id)
        .where(User.role != "superadmin")  # superadmin-i gizlət
        .order_by(User.created_at.desc())
    )
    if role:
        q = q.where(User.role == role)
    if tenant_id:
        q = q.where(User.tenant_id == tenant_id)
    if search:
        q = q.where(User.name.ilike(f"%{search}%") | User.email.ilike(f"%{search}%"))

    result = await db.execute(q.offset(skip).limit(limit))
    rows = result.all()
    return [_build_user_out(u, t_name) for u, t_name in rows]


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(
    user_id: str,
    body: UserPatch,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Activate or deactivate a user account."""

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="İstifadəçi tapılmadı")

    send_activation_notif = body.is_active is True and not user.is_active

    if body.is_active is not None:
        action = "activate_user" if body.is_active else "deactivate_user"
        await audit(db, actor, action, "user", user.id, user.name,
                    f"is_active → {body.is_active}")
        user.is_active = body.is_active
    if body.student_limit is not None:
        user.student_limit = body.student_limit

    if send_activation_notif:
        await send_notification(
            db, user.id,
            "Hesabınız aktivləşdirildi",
            "Artıq bütün funksionallıqdan istifadə edə bilərsiniz.",
            "success",
        )

    await db.commit()
    await db.refresh(user)

    t_res = await db.execute(select(Tenant.name).where(Tenant.id == user.tenant_id))
    t_name = t_res.scalar_one_or_none()
    return _build_user_out(user, t_name)


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: str   # "teacher" | "student" | "parent" | "admin"
    tenant_id: str


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user in the given tenant."""
    from app.services.auth_service import hash_password
    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Bu email artıq qeydiyyatdan keçib")
    # Check tenant exists
    tenant_res = await db.execute(select(Tenant).where(Tenant.id == body.tenant_id))
    if not tenant_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")

    user = User(
        tenant_id=body.tenant_id,
        name=body.name,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.flush()

    if body.role == "student":
        from app.models.student import Student
        stu = Student(user_id=user.id)
        db.add(stu)

    await db.commit()
    await db.refresh(user)

    t_res2 = await db.execute(select(Tenant.name).where(Tenant.id == user.tenant_id))
    t_name2 = t_res2.scalar_one_or_none()
    return _build_user_out(user, t_name2)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user account permanently — cascades all related records."""
    import sqlalchemy as _sa

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="İstifadəçi tapılmadı")

    await audit(db, actor, "delete_user", "user", user.id, user.name, f"email: {user.email}")

    # ── 1. exam_results → students (FK zənciri) ──────────────────────────────
    # students.user_id → user
    stud_res = await db.execute(_sa.text("SELECT id FROM students WHERE user_id = :uid"), {"uid": user_id})
    stud_ids = [r[0] for r in stud_res.fetchall()]
    for sid in stud_ids:
        await db.execute(_sa.text("DELETE FROM exam_results WHERE student_id = :sid"), {"sid": sid})
    await db.execute(_sa.text("DELETE FROM students WHERE user_id = :uid"), {"uid": user_id})
    # parent_id reference
    await db.execute(_sa.text("DELETE FROM students WHERE parent_id = :uid"), {"uid": user_id})

    # ── 2. Müəllimə bağlı cədvəllər ─────────────────────────────────────────
    # exams + exam_results
    exam_res = await db.execute(_sa.text("SELECT id FROM exams WHERE teacher_id = :uid"), {"uid": user_id})
    exam_ids = [r[0] for r in exam_res.fetchall()]
    for eid in exam_ids:
        await db.execute(_sa.text("DELETE FROM exam_results WHERE exam_id = :eid"), {"eid": eid})
    await db.execute(_sa.text("DELETE FROM exams WHERE teacher_id = :uid"), {"uid": user_id})

    # classes
    await db.execute(_sa.text("DELETE FROM classes WHERE teacher_id = :uid"), {"uid": user_id})

    # homeworks
    await db.execute(_sa.text("DELETE FROM homeworks WHERE teacher_id = :uid"), {"uid": user_id})

    # invitations
    await db.execute(_sa.text("DELETE FROM invitations WHERE created_by = :uid"), {"uid": user_id})

    # ── 3. Ümumi user cədvəlləri ─────────────────────────────────────────────
    await db.execute(_sa.text("DELETE FROM ai_logs WHERE user_id = :uid"), {"uid": user_id})
    await db.execute(_sa.text("DELETE FROM notifications WHERE user_id = :uid"), {"uid": user_id})
    await db.execute(_sa.text("DELETE FROM messages WHERE from_user_id = :uid OR to_user_id = :uid"), {"uid": user_id})

    # ── 4. Repetitor cədvəlləri ──────────────────────────────────────────────
    rep_stud_res = await db.execute(_sa.text("SELECT id FROM repetitor_students WHERE teacher_id = :uid"), {"uid": user_id})
    rep_stud_ids = [r[0] for r in rep_stud_res.fetchall()]
    for rsid in rep_stud_ids:
        await db.execute(_sa.text("DELETE FROM repetitor_sessions WHERE student_id = :sid"), {"sid": rsid})
        await db.execute(_sa.text("DELETE FROM repetitor_payments WHERE student_id = :sid"), {"sid": rsid})
    await db.execute(_sa.text("DELETE FROM repetitor_sessions WHERE teacher_id = :uid"), {"uid": user_id})
    await db.execute(_sa.text("DELETE FROM repetitor_payments WHERE teacher_id = :uid"), {"uid": user_id})
    await db.execute(_sa.text("DELETE FROM repetitor_subjects WHERE teacher_id = :uid"), {"uid": user_id})
    await db.execute(_sa.text("DELETE FROM repetitor_students WHERE teacher_id = :uid"), {"uid": user_id})

    # ── 5. Users cədvəlindən sil ─────────────────────────────────────────────
    await db.delete(user)
    await db.commit()


# ── Subscription / Revenue ──────────────────────────────────────────────────

PLAN_FEES = {
    "free": 0, "basic": 4900, "pro": 9900,
    "repetitor": 2500, "musessise": 20000,  # 25 AZN, 200 AZN
}
PLAN_LABELS = {
    "free": "Pulsuz", "basic": "Basic", "pro": "Pro",
    "repetitor": "Repititor", "musessise": "Müəssisə",
}
VALID_PLANS = frozenset(PLAN_FEES.keys())


class SubscriptionOut(BaseModel):
    id: str
    name: str
    slug: str
    type: str
    plan: str
    plan_expires_at: Optional[str] = None
    monthly_fee: int   # qəpik
    user_count: int
    is_active: bool
    created_at: datetime


class SubscriptionPatch(BaseModel):
    plan: Optional[str] = None              # free | repetitor | musessise | basic | pro
    plan_expires_at: Optional[str] = None   # ISO date string YYYY-MM-DD
    monthly_fee: Optional[int] = None       # qəpik


class RevenueSummary(BaseModel):
    mrr: int                       # monthly recurring revenue (qəpik)
    active_subscriptions: int
    free_tenants: int
    basic_tenants: int
    pro_tenants: int


@router.get("/subscriptions/summary", response_model=RevenueSummary)
async def subscription_summary(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant))
    tenants = result.scalars().all()

    free_count  = sum(1 for t in tenants if (t.plan or "free") == "free")
    rep_count   = sum(1 for t in tenants if (t.plan or "free") == "repetitor")
    mus_count   = sum(1 for t in tenants if (t.plan or "free") == "musessise")
    # backward-compat counts
    basic_count = sum(1 for t in tenants if (t.plan or "free") == "basic")
    pro_count   = sum(1 for t in tenants if (t.plan or "free") == "pro")
    mrr = sum((t.monthly_fee or 0) for t in tenants if (t.plan or "free") != "free")
    active_subs = rep_count + mus_count + basic_count + pro_count

    return RevenueSummary(
        mrr=mrr,
        active_subscriptions=active_subs,
        free_tenants=free_count,
        basic_tenants=basic_count,
        pro_tenants=pro_count,
    )


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    user_count_sq = (
        select(User.tenant_id, func.count(User.id).label("user_count"))
        .group_by(User.tenant_id)
        .subquery()
    )
    result = await db.execute(
        select(Tenant, func.coalesce(user_count_sq.c.user_count, 0).label("user_count"))
        .outerjoin(user_count_sq, Tenant.id == user_count_sq.c.tenant_id)
        .order_by(Tenant.created_at.desc())
    )
    rows = result.all()
    return [
        SubscriptionOut(
            id=t.id, name=t.name, slug=t.slug, type=t.type,
            plan=t.plan or "free",
            plan_expires_at=t.plan_expires_at,
            monthly_fee=t.monthly_fee or 0,
            user_count=uc,
            is_active=t.is_active,
            created_at=t.created_at,
        )
        for t, uc in rows
    ]


@router.patch("/subscriptions/{tenant_id}", response_model=SubscriptionOut)
async def patch_subscription(
    tenant_id: str,
    body: SubscriptionPatch,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")

    old_plan = tenant.plan or "free"
    if body.plan is not None:
        if body.plan not in VALID_PLANS:
            raise HTTPException(status_code=400, detail=f"Plan {' | '.join(sorted(VALID_PLANS))} olmalıdır")
        tenant.plan = body.plan
        # Auto-set monthly_fee if not explicitly provided
        if body.monthly_fee is None:
            tenant.monthly_fee = PLAN_FEES[body.plan]
    if body.plan_expires_at is not None:
        tenant.plan_expires_at = body.plan_expires_at or None
    if body.monthly_fee is not None:
        tenant.monthly_fee = max(0, body.monthly_fee)

    new_plan = tenant.plan or "free"
    await audit(db, actor, "update_subscription", "tenant", tenant.id, tenant.name,
                f"plan: {old_plan} → {new_plan}, fee: {tenant.monthly_fee}")
    await db.commit()
    await db.refresh(tenant)

    uc_res = await db.execute(select(func.count(User.id)).where(User.tenant_id == tenant_id))
    user_count = uc_res.scalar_one()

    return SubscriptionOut(
        id=tenant.id, name=tenant.name, slug=tenant.slug, type=tenant.type,
        plan=tenant.plan or "free",
        plan_expires_at=tenant.plan_expires_at,
        monthly_fee=tenant.monthly_fee or 0,
        user_count=user_count,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
    )


# ── Announcements / Broadcast ────────────────────────────────────────────────

class AnnouncementCreate(BaseModel):
    title: str
    message: str
    notif_type: str = "info"        # info | success | warning | error
    target: str = "all"             # all | tenant
    tenant_id: Optional[str] = None  # required when target == "tenant"
    roles: Optional[list[str]] = None  # None = all roles; ["teacher"] = teachers only


class AnnouncementResult(BaseModel):
    id: str
    sent_to: int


class AnnouncementHistoryOut(BaseModel):
    id: str
    actor_name: str
    title: str
    message: str
    notif_type: str
    target: str
    tenant_id: Optional[str] = None
    tenant_name: Optional[str] = None
    roles: Optional[str] = None        # raw JSON string e.g. '["teacher"]'
    sent_to: int
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


@router.get("/announcements", response_model=list[AnnouncementHistoryOut])
async def list_announcements(
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Return the sent-announcement history from the database."""
    from sqlalchemy import desc as sa_desc
    result = await db.execute(
        select(AnnouncementHistory)
        .order_by(sa_desc(AnnouncementHistory.created_at))
        .limit(limit)
    )
    return result.scalars().all()


@router.post("/announcements", response_model=AnnouncementResult)
async def send_announcement(
    body: AnnouncementCreate,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Broadcast an in-app notification to all users or a specific tenant."""
    import json as _json

    q = select(User).where(User.is_active == True)  # noqa: E712

    if body.target == "tenant":
        if not body.tenant_id:
            raise HTTPException(status_code=400, detail="tenant_id tələb olunur")
        q = q.where(User.tenant_id == body.tenant_id)

    if body.roles:
        q = q.where(User.role.in_(body.roles))

    result = await db.execute(q)
    users = result.scalars().all()

    for u in users:
        await send_notification(db, u.id, body.title, body.message, body.notif_type)

    # Resolve tenant name for history
    t_name: Optional[str] = None
    if body.tenant_id:
        t_res = await db.execute(select(Tenant.name).where(Tenant.id == body.tenant_id))
        t_name = t_res.scalar_one_or_none()

    # Persist to history
    history_entry = AnnouncementHistory(
        actor_id=actor.id,
        actor_name=actor.name,
        title=body.title,
        message=body.message,
        notif_type=body.notif_type,
        target=body.target,
        tenant_id=body.tenant_id,
        tenant_name=t_name,
        roles=_json.dumps(body.roles, ensure_ascii=False) if body.roles else None,
        sent_to=len(users),
    )
    db.add(history_entry)
    await db.commit()
    await db.refresh(history_entry)

    return AnnouncementResult(id=history_entry.id, sent_to=len(users))


class BulkImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[str]


@router.post("/users/bulk-import", response_model=BulkImportResult)
async def bulk_import_users(
    file: UploadFile = File(...),
    tenant_id: str = Query(...),
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-create users from an uploaded CSV file into the given tenant."""
    from app.models.student import Student
    from app.services.auth_service import hash_password

    # Verify tenant exists
    tenant_res = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    if not tenant_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")

    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    VALID_ROLES = {"teacher", "student", "parent", "admin"}
    created = 0
    skipped = 0
    errors: list[str] = []

    for i, row in enumerate(reader, start=2):  # row 1 is header
        name = (row.get("name") or "").strip()
        email = (row.get("email") or "").strip()
        password = (row.get("password") or "").strip()
        role = (row.get("role") or "").strip().lower()

        # Skip blank rows
        if not name and not email and not password and not role:
            skipped += 1
            continue

        # Validate required fields
        if not name or not email or not password or not role:
            errors.append(f"Sətir {i}: ad, email, şifrə və rol mütləqdir")
            skipped += 1
            continue

        # Validate role
        if role not in VALID_ROLES:
            errors.append(f"Sətir {i}: '{role}' düzgün rol deyil (teacher/student/parent/admin)")
            skipped += 1
            continue

        # Check email uniqueness
        existing_res = await db.execute(select(User).where(User.email == email))
        if existing_res.scalar_one_or_none():
            errors.append(f"Sətir {i}: '{email}' artıq mövcuddur, buraxıldı")
            skipped += 1
            continue

        user = User(
            tenant_id=tenant_id,
            name=name,
            email=email,
            hashed_password=hash_password(password),
            role=role,
        )
        db.add(user)
        await db.flush()

        if role == "student":
            stu = Student(user_id=user.id)
            db.add(stu)

        created += 1

    await db.commit()

    return BulkImportResult(created=created, skipped=skipped, errors=errors)


# ── Export endpoints ─────────────────────────────────────────────────────────

from fastapi.responses import StreamingResponse


@router.get("/export/users")
async def export_users_csv(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Export all users as a CSV file."""
    result = await db.execute(
        select(User, Tenant.name.label("t_name"))
        .outerjoin(Tenant, User.tenant_id == Tenant.id)
        .order_by(User.created_at.desc())
    )
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Ad", "Email", "Rol", "Müəssisə", "Aktiv", "Qeydiyyat tarixi"])
    for u, t_name in rows:
        writer.writerow([
            u.id, u.name, u.email, u.role,
            t_name or "—",
            "Bəli" if u.is_active else "Xeyr",
            str(u.created_at)[:10] if u.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="users.csv"'},
    )


@router.get("/export/tenants")
async def export_tenants_csv(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Export all tenants as a CSV file."""
    user_count_sq = (
        select(User.tenant_id, func.count(User.id).label("user_count"))
        .group_by(User.tenant_id)
        .subquery()
    )
    result = await db.execute(
        select(Tenant, func.coalesce(user_count_sq.c.user_count, 0).label("user_count"))
        .outerjoin(user_count_sq, Tenant.id == user_count_sq.c.tenant_id)
        .order_by(Tenant.created_at.desc())
    )
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Ad", "Slug", "Növ", "Plan", "Aktiv", "İstifadəçi sayı", "Şagird limiti", "Müəllim limiti", "Yaradılma tarixi"])
    for t, uc in rows:
        writer.writerow([
            t.id, t.name, t.slug, t.type,
            t.plan or "free",
            "Bəli" if t.is_active else "Xeyr",
            uc, t.student_limit or 0, t.teacher_limit or 0,
            str(t.created_at)[:10] if t.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="tenants.csv"'},
    )


@router.get("/export/invoices")
async def export_invoices_csv(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Export all invoices as a CSV file."""
    from app.models.invoice import Invoice as InvoiceModel
    result = await db.execute(
        select(InvoiceModel).order_by(InvoiceModel.created_at.desc())
    )
    rows = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Müəssisə", "Dövr", "Məbləğ (AZN)", "Status", "Yaradılma", "Ödəniş tarixi", "Qeyd"])
    for inv in rows:
        writer.writerow([
            inv.id,
            inv.tenant_name,
            inv.period,
            f"{(inv.amount or 0) / 100:.2f}",
            inv.status,
            str(inv.created_at)[:10] if inv.created_at else "",
            str(inv.paid_at)[:10] if inv.paid_at else "",
            inv.notes or "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="invoices.csv"'},
    )


@router.get("/ai-logs", response_model=AILogPage)
async def list_ai_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    provider: str = Query(""),
    purpose: str = Query(""),
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Paginated list of all AI request logs."""

    offset = (page - 1) * limit

    count_q = select(func.count(AILog.id))
    if provider:
        count_q = count_q.where(AILog.provider == provider)
    if purpose:
        count_q = count_q.where(AILog.purpose == purpose)

    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    q = (
        select(AILog, User, Tenant)
        .outerjoin(User, User.id == AILog.user_id)
        .outerjoin(Tenant, Tenant.id == AILog.tenant_id)
        .order_by(AILog.created_at.desc())
    )
    if provider:
        q = q.where(AILog.provider == provider)
    if purpose:
        q = q.where(AILog.purpose == purpose)
    q = q.offset(offset).limit(limit)

    logs_result = await db.execute(q)
    rows = logs_result.all()

    pages = (total + limit - 1) // limit  # ceiling division

    import re as _re
    _uuid_re = _re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', _re.I)

    def _tenant_display(t) -> str:
        if not t:
            return "—"
        # UUID-ə bənzəyirsə slug göstər
        if _uuid_re.match(t.name or ''):
            return t.slug or t.name
        return t.name or t.slug or "—"

    items = [
        AILogOut(
            id=log.id,
            tenant_name=_tenant_display(tenant),
            user_name=user.name if user else "—",
            provider=log.provider,
            purpose=log.purpose,
            tokens_used=log.tokens_used,
            latency_ms=log.latency_ms,
            success=log.was_accepted,
            created_at=log.created_at,
        )
        for log, user, tenant in rows
    ]

    return AILogPage(
        items=items,
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )


@router.get("/ai-logs/stats", response_model=AIStats)
async def get_ai_stats(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """AI usage statistics broken down by provider and purpose."""

    total_calls_result = await db.execute(select(func.count(AILog.id)))
    total_tokens_result = await db.execute(select(func.coalesce(func.sum(AILog.tokens_used), 0)))
    success_count_result = await db.execute(
        select(func.count(AILog.id)).where(AILog.was_accepted == True)  # noqa: E712
    )
    avg_latency_result = await db.execute(select(func.coalesce(func.avg(AILog.latency_ms), 0)))

    prov_rows = await db.execute(
        select(AILog.provider, func.count(AILog.id), func.coalesce(func.sum(AILog.tokens_used), 0))
        .group_by(AILog.provider)
    )

    purp_rows = await db.execute(
        select(AILog.purpose, func.count(AILog.id))
        .where(AILog.purpose != None)  # noqa: E711
        .group_by(AILog.purpose)
    )

    total_c = total_calls_result.scalar_one()
    success_count = success_count_result.scalar_one()
    success_rate = (success_count / total_c * 100) if total_c > 0 else 0.0

    return AIStats(
        total_calls=total_c,
        total_tokens=total_tokens_result.scalar_one(),
        success_rate=round(success_rate, 1),
        avg_latency_ms=round(avg_latency_result.scalar_one(), 1),
        by_provider=[
            ProviderBreakdown(provider=r[0], calls=r[1], tokens=r[2])
            for r in prov_rows.all()
        ],
        by_purpose=[
            PurposeBreakdown(purpose=r[0] or "other", calls=r[1])
            for r in purp_rows.all()
        ],
    )


# ── Platform Settings ────────────────────────────────────────────────────────

import json
import os

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "..", "platform_settings.json")


def _load_settings() -> dict:
    defaults = {
        "app_name": "EduAI",
        "debug_mode": False,
        "maintenance": False,
        "providers": {
            "Cerebras":   {"active": True, "priority": 1, "daily_limit": 10000},
            "Groq":       {"active": True, "priority": 2, "daily_limit": 8000},
            "Gemini":     {"active": True, "priority": 3, "daily_limit": 5000},
            "OpenRouter": {"active": True, "priority": 4, "daily_limit": 3000},
        },
        "email_notifs": True,
        "threshold_alerts": True,
        "threshold_pct": 80,
        "contact_phone": "+994 50 000 00 00",
        "contact_email": "info@eduai.az",
        "contact_whatsapp": "",
        "contact_message": "Hesabınızı aktivləşdirmək üçün bizimlə əlaqəyə keçin.",
    }
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)
                defaults.update(stored)
    except Exception:
        pass
    return defaults


def _save_settings(data: dict):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class ProviderCfg(BaseModel):
    active: bool
    priority: int
    daily_limit: int


class PlatformSettingsOut(BaseModel):
    app_name: str
    debug_mode: bool
    maintenance: bool
    providers: dict[str, ProviderCfg]
    email_notifs: bool
    threshold_alerts: bool
    threshold_pct: int
    contact_phone: str = "+994 50 000 00 00"
    contact_email: str = "info@eduai.az"
    contact_whatsapp: str = ""
    contact_message: str = "Hesabınızı aktivləşdirmək üçün bizimlə əlaqəyə keçin."


class PlatformSettingsPatch(BaseModel):
    app_name: Optional[str] = None
    debug_mode: Optional[bool] = None
    maintenance: Optional[bool] = None
    providers: Optional[dict[str, ProviderCfg]] = None
    email_notifs: Optional[bool] = None
    threshold_alerts: Optional[bool] = None
    threshold_pct: Optional[int] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    contact_whatsapp: Optional[str] = None
    contact_message: Optional[str] = None


# ── System Health ─────────────────────────────────────────────────────────────

class SystemHealth(BaseModel):
    status: str           # "healthy" | "degraded" | "down"
    db_ok: bool
    db_latency_ms: float
    total_users: int
    total_tenants: int
    total_ai_calls: int
    uptime_note: str


@router.get("/health", response_model=SystemHealth)
async def system_health(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Quick system health snapshot."""
    import time as _time

    t0 = _time.monotonic()
    try:
        user_res = await db.execute(select(func.count(User.id)))
        total_users = user_res.scalar_one()
        tenant_res = await db.execute(select(func.count(Tenant.id)))
        total_tenants = tenant_res.scalar_one()
        ai_res = await db.execute(select(func.count(AILog.id)))
        total_ai_calls = ai_res.scalar_one()
        db_ok = True
    except Exception:
        total_users = total_tenants = total_ai_calls = 0
        db_ok = False

    db_latency_ms = round((_time.monotonic() - t0) * 1000, 2)
    status = "healthy" if db_ok and db_latency_ms < 500 else "degraded" if db_ok else "down"

    return SystemHealth(
        status=status,
        db_ok=db_ok,
        db_latency_ms=db_latency_ms,
        total_users=total_users,
        total_tenants=total_tenants,
        total_ai_calls=total_ai_calls,
        uptime_note="FastAPI + SQLite",
    )


@router.get("/settings", response_model=PlatformSettingsOut)
async def get_platform_settings(
    _: User = Depends(require_superadmin),
):
    data = _load_settings()
    return PlatformSettingsOut(
        app_name=data["app_name"],
        debug_mode=data["debug_mode"],
        maintenance=data["maintenance"],
        providers={k: ProviderCfg(**v) for k, v in data["providers"].items()},
        email_notifs=data["email_notifs"],
        threshold_alerts=data["threshold_alerts"],
        threshold_pct=data["threshold_pct"],
        contact_phone=data.get("contact_phone", "+994 50 000 00 00"),
        contact_email=data.get("contact_email", "info@eduai.az"),
        contact_whatsapp=data.get("contact_whatsapp", ""),
        contact_message=data.get("contact_message", "Hesabınızı aktivləşdirmək üçün bizimlə əlaqəyə keçin."),
    )


@router.patch("/settings", response_model=PlatformSettingsOut)
async def patch_platform_settings(
    body: PlatformSettingsPatch,
    _: User = Depends(require_superadmin),
):
    data = _load_settings()
    if body.app_name is not None:
        data["app_name"] = body.app_name
    if body.debug_mode is not None:
        data["debug_mode"] = body.debug_mode
    if body.maintenance is not None:
        data["maintenance"] = body.maintenance
    if body.providers is not None:
        data["providers"] = {k: v.model_dump() for k, v in body.providers.items()}
    if body.email_notifs is not None:
        data["email_notifs"] = body.email_notifs
    if body.threshold_alerts is not None:
        data["threshold_alerts"] = body.threshold_alerts
    if body.threshold_pct is not None:
        data["threshold_pct"] = body.threshold_pct
    if body.contact_phone is not None:
        data["contact_phone"] = body.contact_phone
    if body.contact_email is not None:
        data["contact_email"] = body.contact_email
    if body.contact_whatsapp is not None:
        data["contact_whatsapp"] = body.contact_whatsapp
    if body.contact_message is not None:
        data["contact_message"] = body.contact_message
    _save_settings(data)
    return PlatformSettingsOut(
        app_name=data["app_name"],
        debug_mode=data["debug_mode"],
        maintenance=data["maintenance"],
        providers={k: ProviderCfg(**v) for k, v in data["providers"].items()},
        email_notifs=data["email_notifs"],
        threshold_alerts=data["threshold_alerts"],
        threshold_pct=data["threshold_pct"],
        contact_phone=data.get("contact_phone", "+994 50 000 00 00"),
        contact_email=data.get("contact_email", "info@eduai.az"),
        contact_whatsapp=data.get("contact_whatsapp", ""),
        contact_message=data.get("contact_message", "Hesabınızı aktivləşdirmək üçün bizimlə əlaqəyə keçin."),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 1 — AI Limit per tenant
# ═══════════════════════════════════════════════════════════════════════════════

class AILimitPatch(BaseModel):
    ai_daily_limit: int   # 0 = unlimited


@router.patch("/tenants/{tenant_id}/ai-limit")
async def patch_ai_limit(
    tenant_id: str,
    body: AILimitPatch,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")
    old = tenant.ai_daily_limit or 0
    tenant.ai_daily_limit = max(0, body.ai_daily_limit)
    await audit(db, actor, "update_ai_limit", "tenant", tenant.id, tenant.name,
                f"ai_daily_limit: {old} → {tenant.ai_daily_limit}")
    await db.commit()
    return {"tenant_id": tenant_id, "ai_daily_limit": tenant.ai_daily_limit}


@router.get("/tenants/{tenant_id}/ai-usage")
async def get_tenant_ai_usage(
    tenant_id: str,
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Return today's AI call count for a tenant."""
    from datetime import date
    today = date.today().isoformat()
    result = await db.execute(
        select(func.count(AILog.id)).where(
            AILog.tenant_id == tenant_id,
            func.strftime('%Y-%m-%d', AILog.created_at) == today,
        )
    )
    count = result.scalar_one()
    t_res = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = t_res.scalar_one_or_none()
    limit = (tenant.ai_daily_limit or 0) if tenant else 0
    return {"today_calls": count, "daily_limit": limit, "unlimited": limit == 0}


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 2 — Feature Flags per tenant
# ═══════════════════════════════════════════════════════════════════════════════

ALL_FEATURES = ["ai_tutor", "exams", "homework", "timetable", "messages", "leaderboard"]

class FeatureFlagsPatch(BaseModel):
    features: dict[str, bool]   # e.g. {"ai_tutor": True, "flashcards": False}


@router.get("/tenants/{tenant_id}/features")
async def get_tenant_features(
    tenant_id: str,
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")
    stored = json.loads(tenant.features or '{}')
    # Merge with defaults (all True)
    flags = {f: stored.get(f, True) for f in ALL_FEATURES}
    return {"tenant_id": tenant_id, "features": flags}


@router.patch("/tenants/{tenant_id}/features")
async def patch_tenant_features(
    tenant_id: str,
    body: FeatureFlagsPatch,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")
    stored = json.loads(tenant.features or '{}')
    stored.update(body.features)
    tenant.features = json.dumps(stored, ensure_ascii=False)
    await audit(db, actor, "update_features", "tenant", tenant.id, tenant.name,
                json.dumps(body.features, ensure_ascii=False))
    await db.commit()
    return {"tenant_id": tenant_id, "features": stored}


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 3 — Support Ticket System
# ═══════════════════════════════════════════════════════════════════════════════

class TicketCreate(BaseModel):
    tenant_id: str
    author_name: str
    author_email: str
    subject: str
    body: str
    priority: str = "medium"   # low | medium | high


class TicketReply(BaseModel):
    reply: str
    status: str = "closed"   # in_progress | closed


class TicketOut(BaseModel):
    id: str
    tenant_id: str
    tenant_name: Optional[str] = None
    author_name: str
    author_email: str
    subject: str
    body: str
    status: str
    priority: str
    reply: Optional[str] = None
    replied_at: Optional[str] = None
    replied_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"from_attributes": True}


@router.get("/tickets", response_model=list[TicketOut])
async def list_tickets(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import desc as sa_desc
    q = select(SupportTicket).order_by(sa_desc(SupportTicket.created_at))
    if status:
        q = q.where(SupportTicket.status == status)
    if priority:
        q = q.where(SupportTicket.priority == priority)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/tickets", response_model=TicketOut, status_code=201)
async def create_ticket(
    body: TicketCreate,
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    t_res = await db.execute(select(Tenant.name).where(Tenant.id == body.tenant_id))
    t_name = t_res.scalar_one_or_none()
    ticket = SupportTicket(
        tenant_id=body.tenant_id,
        tenant_name=t_name,
        author_name=body.author_name,
        author_email=body.author_email,
        subject=body.subject,
        body=body.body,
        priority=body.priority,
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return ticket


@router.patch("/tickets/{ticket_id}", response_model=TicketOut)
async def reply_ticket(
    ticket_id: str,
    body: TicketReply,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tapılmadı")
    ticket.reply = body.reply
    ticket.status = body.status
    ticket.replied_at = datetime.now(timezone.utc).isoformat()
    ticket.replied_by = actor.name
    ticket.updated_at = datetime.now(timezone.utc).isoformat()
    await db.commit()
    await db.refresh(ticket)
    return ticket


@router.delete("/tickets/{ticket_id}", status_code=204)
async def delete_ticket(
    ticket_id: str,
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Tiket tapılmadı")
    await db.delete(ticket)
    await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 4 — Bulk Actions
# ═══════════════════════════════════════════════════════════════════════════════

class BulkUserAction(BaseModel):
    action: str          # activate | deactivate | delete
    user_ids: list[str]


class BulkTenantAction(BaseModel):
    action: str          # activate | deactivate | delete
    tenant_ids: list[str]


class BulkResult(BaseModel):
    affected: int
    errors: list[str]


@router.post("/bulk/users", response_model=BulkResult)
async def bulk_user_action(
    body: BulkUserAction,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    if body.action not in ("activate", "deactivate", "delete"):
        raise HTTPException(status_code=400, detail="action: activate | deactivate | delete")
    affected = 0
    errors: list[str] = []
    for uid in body.user_ids:
        res = await db.execute(select(User).where(User.id == uid))
        user = res.scalar_one_or_none()
        if not user:
            errors.append(f"{uid}: tapılmadı")
            continue
        if body.action == "delete":
            await audit(db, actor, "delete_user", "user", user.id, user.name, "bulk delete")
            await db.delete(user)
        else:
            new_active = body.action == "activate"
            action_name = "activate_user" if new_active else "deactivate_user"
            await audit(db, actor, action_name, "user", user.id, user.name, "bulk action")
            user.is_active = new_active
        affected += 1
    await db.commit()
    return BulkResult(affected=affected, errors=errors)


@router.post("/bulk/tenants", response_model=BulkResult)
async def bulk_tenant_action(
    body: BulkTenantAction,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    if body.action not in ("activate", "deactivate", "delete"):
        raise HTTPException(status_code=400, detail="action: activate | deactivate | delete")
    affected = 0
    errors: list[str] = []
    for tid in body.tenant_ids:
        res = await db.execute(select(Tenant).where(Tenant.id == tid))
        tenant = res.scalar_one_or_none()
        if not tenant:
            errors.append(f"{tid}: tapılmadı")
            continue
        if body.action == "delete":
            users_res = await db.execute(select(User).where(User.tenant_id == tid))
            for u in users_res.scalars().all():
                await db.delete(u)
            await audit(db, actor, "delete_tenant", "tenant", tenant.id, tenant.name, "bulk delete")
            await db.delete(tenant)
        else:
            tenant.is_active = body.action == "activate"
        affected += 1
    await db.commit()
    return BulkResult(affected=affected, errors=errors)


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 5 — Scheduled Announcements (process due ones)
# ═══════════════════════════════════════════════════════════════════════════════

class ScheduledAnnouncementCreate(BaseModel):
    title: str
    message: str
    notif_type: str = "info"
    target: str = "all"
    tenant_id: Optional[str] = None
    roles: Optional[list[str]] = None
    scheduled_at: str   # ISO datetime string


@router.post("/announcements/scheduled", response_model=AnnouncementResult)
async def create_scheduled_announcement(
    body: ScheduledAnnouncementCreate,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Save a scheduled announcement without sending it yet."""
    import json as _json
    t_name: Optional[str] = None
    if body.tenant_id:
        t_res = await db.execute(select(Tenant.name).where(Tenant.id == body.tenant_id))
        t_name = t_res.scalar_one_or_none()
    entry = AnnouncementHistory(
        actor_id=actor.id,
        actor_name=actor.name,
        title=body.title,
        message=body.message,
        notif_type=body.notif_type,
        target=body.target,
        tenant_id=body.tenant_id,
        tenant_name=t_name,
        roles=_json.dumps(body.roles, ensure_ascii=False) if body.roles else None,
        sent_to=0,
        scheduled_at=body.scheduled_at,
        is_sent=0,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return AnnouncementResult(id=entry.id, sent_to=0)


@router.post("/announcements/process-scheduled")
async def process_scheduled_announcements(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Send all scheduled announcements whose scheduled_at has passed."""
    now_str = datetime.now(timezone.utc).isoformat()
    result = await db.execute(
        select(AnnouncementHistory).where(
            AnnouncementHistory.is_sent == 0,
            AnnouncementHistory.scheduled_at <= now_str,
        )
    )
    pending = result.scalars().all()
    total_sent = 0
    for ann in pending:
        import json as _json
        q = select(User).where(User.is_active == True)  # noqa: E712
        if ann.target == "tenant" and ann.tenant_id:
            q = q.where(User.tenant_id == ann.tenant_id)
        roles = _json.loads(ann.roles) if ann.roles else None
        if roles:
            q = q.where(User.role.in_(roles))
        users_res = await db.execute(q)
        users = users_res.scalars().all()
        for u in users:
            await send_notification(db, u.id, ann.title, ann.message, ann.notif_type)
        ann.sent_to = len(users)
        ann.is_sent = 1
        total_sent += len(users)
    await db.commit()
    return {"processed": len(pending), "total_sent": total_sent}


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 6 — Invoice System
# ═══════════════════════════════════════════════════════════════════════════════

class InvoiceCreate(BaseModel):
    tenant_id: str
    period: str              # YYYY-MM
    amount: int              # qəpik
    notes: Optional[str] = None
    status: Optional[str] = None   # 'paid' | 'unpaid' (default: 'unpaid')


class InvoicePatch(BaseModel):
    status: Optional[str] = None    # paid | unpaid | cancelled
    notes: Optional[str] = None
    amount: Optional[int] = None


class InvoiceOut(BaseModel):
    id: str
    tenant_id: str
    tenant_name: str
    period: str
    amount: int
    status: str
    notes: Optional[str] = None
    created_at: Optional[str] = None
    paid_at: Optional[str] = None

    model_config = {"from_attributes": True}


@router.get("/invoices", response_model=list[InvoiceOut])
async def list_invoices(
    tenant_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import desc as sa_desc
    q = select(Invoice).order_by(sa_desc(Invoice.created_at))
    if tenant_id:
        q = q.where(Invoice.tenant_id == tenant_id)
    if status:
        q = q.where(Invoice.status == status)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/invoices", response_model=InvoiceOut, status_code=201)
async def create_invoice(
    body: InvoiceCreate,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    t_res = await db.execute(select(Tenant.name).where(Tenant.id == body.tenant_id))
    t_name = t_res.scalar_one_or_none()
    if not t_name:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")
    inv_status = body.status if body.status in ("paid", "unpaid", "cancelled") else "unpaid"
    invoice = Invoice(
        tenant_id=body.tenant_id,
        tenant_name=t_name,
        period=body.period,
        amount=max(0, body.amount),
        notes=body.notes,
        status=inv_status,
        paid_at=datetime.now(timezone.utc).isoformat() if inv_status == "paid" else None,
    )
    db.add(invoice)
    await audit(db, actor, "create_invoice", "tenant", body.tenant_id, t_name,
                f"period: {body.period}, amount: {body.amount}, status: {inv_status}")
    await db.commit()
    await db.refresh(invoice)
    return invoice


@router.patch("/invoices/{invoice_id}", response_model=InvoiceOut)
async def patch_invoice(
    invoice_id: str,
    body: InvoicePatch,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Faktura tapılmadı")
    if body.status is not None:
        old_status = inv.status
        inv.status = body.status
        if body.status == "paid" and old_status != "paid":
            inv.paid_at = datetime.now(timezone.utc).isoformat()
        elif body.status != "paid":
            inv.paid_at = None
    if body.notes is not None:
        inv.notes = body.notes
    if body.amount is not None:
        inv.amount = max(0, body.amount)
    await audit(db, actor, "update_invoice", "tenant", inv.tenant_id, inv.tenant_name,
                f"status: {inv.status}")
    await db.commit()
    await db.refresh(inv)
    return inv


@router.delete("/invoices/{invoice_id}", status_code=204)
async def delete_invoice(
    invoice_id: str,
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Faktura tapılmadı")
    await db.delete(inv)
    await db.commit()


# Auto-generate invoices for all paid tenants for current month
@router.post("/invoices/generate-monthly")
async def generate_monthly_invoices(
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Create invoices for all paid-plan tenants for the current month (idempotent)."""
    from datetime import date
    period = date.today().strftime("%Y-%m")
    result = await db.execute(
        select(Tenant).where(Tenant.plan.in_(["repetitor", "musessise", "basic", "pro"]))
    )
    tenants = result.scalars().all()
    created = 0
    skipped = 0
    for t in tenants:
        # Check if already exists
        existing = await db.execute(
            select(Invoice).where(Invoice.tenant_id == t.id, Invoice.period == period)
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue
        inv = Invoice(
            tenant_id=t.id,
            tenant_name=t.name,
            period=period,
            amount=t.monthly_fee or 0,
        )
        db.add(inv)
        created += 1
    await db.commit()
    return {"period": period, "created": created, "skipped": skipped}


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 8 — Heatmap (hourly login counts last 7 days)
# ═══════════════════════════════════════════════════════════════════════════════

class HeatmapCell(BaseModel):
    day: int    # 0=Mon … 6=Sun
    hour: int   # 0–23
    count: int


@router.get("/stats/heatmap", response_model=list[HeatmapCell])
async def get_login_heatmap(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Return login counts grouped by weekday × hour for the last 30 days."""
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=30)).isoformat()

    result = await db.execute(
        select(
            func.strftime('%w', LoginLog.created_at).label("dow"),   # 0=Sun…6=Sat
            func.strftime('%H', LoginLog.created_at).label("hour"),
            func.count(LoginLog.id).label("cnt"),
        )
        .where(LoginLog.created_at >= cutoff)
        .group_by("dow", "hour")
    )
    rows = result.all()

    # SQLite %w: 0=Sun, 1=Mon … 6=Sat  →  convert to Mon=0 … Sun=6
    cells: list[HeatmapCell] = []
    for dow_str, hour_str, cnt in rows:
        dow = (int(dow_str) - 1) % 7   # Sun(0)→6, Mon(1)→0 …
        cells.append(HeatmapCell(day=dow, hour=int(hour_str), count=cnt))
    return cells


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 9 — Tenant Comparison stats
# ═══════════════════════════════════════════════════════════════════════════════

class TenantCompareStats(BaseModel):
    id: str
    name: str
    plan: str
    user_count: int
    teacher_count: int
    student_count: int
    ai_calls_total: int
    ai_calls_today: int
    login_count_30d: int
    monthly_fee: int
    ai_daily_limit: int
    features: dict


@router.get("/tenants/{tenant_id}/compare-stats", response_model=TenantCompareStats)
async def get_tenant_compare_stats(
    tenant_id: str,
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    from datetime import date, timedelta
    t_res = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = t_res.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")

    users_res = await db.execute(
        select(User.role, func.count(User.id)).where(User.tenant_id == tenant_id).group_by(User.role)
    )
    role_map = {r: c for r, c in users_res.all()}
    user_count = sum(role_map.values())

    ai_total_res = await db.execute(
        select(func.count(AILog.id)).where(AILog.tenant_id == tenant_id)
    )
    ai_total = ai_total_res.scalar_one()

    today = date.today().isoformat()
    ai_today_res = await db.execute(
        select(func.count(AILog.id)).where(
            AILog.tenant_id == tenant_id,
            func.strftime('%Y-%m-%d', AILog.created_at) == today,
        )
    )
    ai_today = ai_today_res.scalar_one()

    cutoff = (date.today() - timedelta(days=30)).isoformat()
    login_res = await db.execute(
        select(func.count(LoginLog.id)).where(
            LoginLog.tenant_id == tenant_id,
            LoginLog.created_at >= cutoff,
        )
    )
    login_30d = login_res.scalar_one()

    features = json.loads(tenant.features or '{}')
    all_flags = {f: features.get(f, True) for f in ALL_FEATURES}

    return TenantCompareStats(
        id=tenant.id,
        name=tenant.name,
        plan=tenant.plan or "free",
        user_count=user_count,
        teacher_count=role_map.get("teacher", 0),
        student_count=role_map.get("student", 0),
        ai_calls_total=ai_total,
        ai_calls_today=ai_today,
        login_count_30d=login_30d,
        monthly_fee=tenant.monthly_fee or 0,
        ai_daily_limit=tenant.ai_daily_limit or 0,
        features=all_flags,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 10 — Custom Branding per tenant
# ═══════════════════════════════════════════════════════════════════════════════

class BrandingPatch(BaseModel):
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None   # hex e.g. "#2196f3"


@router.patch("/tenants/{tenant_id}/branding")
async def patch_tenant_branding(
    tenant_id: str,
    body: BrandingPatch,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")
    if body.logo_url is not None:
        tenant.logo_url = body.logo_url or None
    if body.primary_color is not None:
        # Validate hex format
        import re as _re
        if body.primary_color and not _re.match(r'^#[0-9a-fA-F]{3,6}$', body.primary_color):
            raise HTTPException(status_code=400, detail="Rəng hex formatında olmalıdır: #RRGGBB")
        tenant.primary_color = body.primary_color or None
    await audit(db, actor, "update_branding", "tenant", tenant.id, tenant.name,
                f"logo={bool(tenant.logo_url)}, color={tenant.primary_color}")
    await db.commit()
    return {
        "tenant_id": tenant_id,
        "logo_url": tenant.logo_url,
        "primary_color": tenant.primary_color,
    }


@router.get("/tenants/{tenant_id}/branding")
async def get_tenant_branding(
    tenant_id: str,
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")
    return {
        "tenant_id": tenant_id,
        "logo_url": tenant.logo_url,
        "primary_color": tenant.primary_color,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TREND & CHARTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/stats/trend")
async def get_stats_trend(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Son 12 ay üzrə aylıq yeni tenant, istifadəçi sayları."""
    import sqlalchemy as _sa
    result = await db.execute(_sa.text("""
        SELECT strftime('%Y-%m', created_at) AS month,
               COUNT(*) AS new_tenants
        FROM tenants
        WHERE created_at >= date('now', '-12 months')
        GROUP BY month ORDER BY month
    """))
    tenant_rows = {r.month: r.new_tenants for r in result.fetchall()}

    result2 = await db.execute(_sa.text("""
        SELECT strftime('%Y-%m', created_at) AS month,
               COUNT(*) AS new_users
        FROM users
        WHERE created_at >= date('now', '-12 months')
        GROUP BY month ORDER BY month
    """))
    user_rows = {r.month: r.new_users for r in result2.fetchall()}

    from datetime import date
    months = []
    for i in range(11, -1, -1):
        d = date.today().replace(day=1)
        month = (d.replace(month=((d.month - 1 - i) % 12) + 1,
                           year=d.year + ((d.month - 1 - i) // 12
                                          if (d.month - 1 - i) >= 0
                                          else d.year - 1))
                 if False else None)
        # Simple approach: use f-string
        import calendar
        y = d.year - (i // 12)
        m = ((d.month - 1 - (i % 12)) % 12) + 1
        if d.month - 1 - (i % 12) < 0:
            y -= 1
        label = f"{y}-{m:02d}"
        months.append(label)

    return [
        {
            "month": m,
            "new_tenants": tenant_rows.get(m, 0),
            "new_users": user_rows.get(m, 0),
        }
        for m in months
    ]


@router.get("/stats/revenue-trend")
async def get_revenue_trend(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Son 12 ay üzrə aylıq gəlir (aktiv abunəliklərdən)."""
    import sqlalchemy as _sa
    result = await db.execute(_sa.text("""
        SELECT strftime('%Y-%m', created_at) AS month,
               SUM(monthly_fee) AS revenue
        FROM tenants
        WHERE plan != 'free'
          AND is_active = 1
          AND created_at >= date('now', '-12 months')
        GROUP BY month ORDER BY month
    """))
    rows = {r.month: r.revenue or 0 for r in result.fetchall()}

    from datetime import date
    months = []
    d = date.today()
    for i in range(11, -1, -1):
        m = ((d.month - 1 - i) % 12) + 1
        y = d.year + ((d.month - 1 - i) // 12) if (d.month - 1 - i) >= 0 else d.year - 1
        if d.month - 1 - i < 0:
            y = d.year - 1 + (d.month - i) // 12
        label = f"{d.year - (i // 12 + (1 if (d.month - 1 - (i % 12)) < 0 else 0))}-{((d.month - 1 - i) % 12) + 1:02d}"
        months.append(label)

    return [{"month": m, "revenue_qepik": rows.get(m, 0)} for m in months]


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL PLATFORM SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

_GLOBAL_SETTINGS_FILE = "global_settings.json"

def _load_global_settings() -> dict:
    if os.path.exists(_GLOBAL_SETTINGS_FILE):
        with open(_GLOBAL_SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {
        "default_ai_limit": 0,
        "allow_self_register": False,
        "maintenance_mode": False,
        "platform_name": "EduAI",
        "support_email": "support@eduai.az",
    }

def _save_global_settings(s: dict):
    with open(_GLOBAL_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


class GlobalSettingsPatch(BaseModel):
    default_ai_limit: Optional[int] = None
    allow_self_register: Optional[bool] = None
    maintenance_mode: Optional[bool] = None
    platform_name: Optional[str] = None
    support_email: Optional[str] = None


@router.get("/settings/global")
async def get_global_settings(_: User = Depends(require_superadmin)):
    return _load_global_settings()


@router.patch("/settings/global")
async def patch_global_settings(
    body: GlobalSettingsPatch,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    s = _load_global_settings()
    if body.default_ai_limit is not None:
        s["default_ai_limit"] = max(0, body.default_ai_limit)
    if body.allow_self_register is not None:
        s["allow_self_register"] = body.allow_self_register
    if body.maintenance_mode is not None:
        s["maintenance_mode"] = body.maintenance_mode
    if body.platform_name is not None:
        s["platform_name"] = body.platform_name.strip() or "EduAI"
    if body.support_email is not None:
        s["support_email"] = body.support_email.strip()
    _save_global_settings(s)
    await audit(db, actor, "update_global_settings", "platform", "global", "settings",
                str({k: v for k, v in body.model_dump().items() if v is not None}))
    return s


# ═══════════════════════════════════════════════════════════════════════════════
# BACKUP
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/backup")
async def download_backup(
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Bütün platformu ZIP arxivi kimi yüklə (şifrələr xaric)."""
    import zipfile, io, json as _json

    tenants_r = await db.execute(select(Tenant).order_by(Tenant.created_at))
    users_r   = await db.execute(select(User).order_by(User.created_at))

    tenants_data = [
        {c: getattr(t, c) for c in ["id","name","slug","type","is_active","plan",
                                      "monthly_fee","ai_daily_limit","features",
                                      "logo_url","primary_color","created_at"]
         if hasattr(t, c)}
        for t in tenants_r.scalars().all()
    ]
    users_data = [
        {c: getattr(u, c) for c in ["id","tenant_id","name","email","role",
                                      "is_active","created_at"]
         if hasattr(u, c)}
        for u in users_r.scalars().all()
    ]

    now_str   = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
    stamp     = datetime.now().strftime('%Y%m%d_%H%M')

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "platform": "EduAI",
        "version": "1.0",
        "tenants_count": len(tenants_data),
        "users_count": len(users_data),
        "tenants": tenants_data,
        "users": users_data,
    }
    json_bytes = _json.dumps(payload, ensure_ascii=False, default=str, indent=2).encode("utf-8")

    readme = (
        f"EduAI Platform Backup\n"
        f"======================\n"
        f"Tarix      : {now_str}\n"
        f"Müəssisə   : {len(tenants_data)}\n"
        f"İstifadəçi : {len(users_data)}\n\n"
        f"Fayllar:\n"
        f"  data.json  — bütün məlumatlar (şifrələr xaric)\n\n"
        f"QEYD: Bu fayl yalnız məlumatları ehtiva edir.\n"
        f"Verilənlər bazasını bərpa etmək üçün dəstəklə əlaqə saxlayın.\n"
    ).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"eduai_backup_{stamp}/data.json",   json_bytes)
        zf.writestr(f"eduai_backup_{stamp}/README.txt",  readme)
    buf.seek(0)

    await audit(db, actor, "download_backup", "platform", "global", "backup", "")

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=eduai_backup_{stamp}.zip"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# INVITATION LINK
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/tenants/{tenant_id}/invite-link")
async def generate_invite_link(
    tenant_id: str,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Müəssisə üçün bir dəfəlik qeydiyyat linki yarat."""
    import base64, hashlib, time
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")

    # Simple signed token: base64(tenant_id:timestamp:hmac)
    secret = "eduai_invite_secret_2026"
    ts = str(int(time.time()))
    raw = f"{tenant_id}:{ts}"
    sig = hashlib.sha256(f"{raw}:{secret}".encode()).hexdigest()[:16]
    token = base64.urlsafe_b64encode(f"{raw}:{sig}".encode()).decode()

    await audit(db, actor, "generate_invite_link", "tenant", tenant_id, tenant.name, "")
    return {
        "token": token,
        "invite_url": f"https://eduai.az/invite/{token}",
        "expires_in": "48 saat",
        "tenant_name": tenant.name,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BROADCAST ANNOUNCEMENT
# ═══════════════════════════════════════════════════════════════════════════════

class BroadcastBody(BaseModel):
    title: str
    message: str
    target: str = "all"   # all | teachers | students | corporate


@router.post("/broadcast")
async def broadcast_announcement(
    body: BroadcastBody,
    actor: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Bütün aktiv müəssisələrə eyni elanı göndər."""
    tenants_r = await db.execute(select(Tenant).where(Tenant.is_active == True))
    tenants = tenants_r.scalars().all()

    now = datetime.now(timezone.utc).isoformat()
    ann_id_base = f"bc-{int(datetime.now().timestamp())}"

    _ANNOUNCEMENTS_FILE = "announcements_teacher.json"
    if os.path.exists(_ANNOUNCEMENTS_FILE):
        with open(_ANNOUNCEMENTS_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = []

    added = 0
    for tenant in tenants:
        existing.append({
            "id": f"{ann_id_base}-{tenant.id[:8]}",
            "tenant_id": tenant.id,
            "title": body.title,
            "message": body.message,
            "target": body.target,
            "created_at": now,
            "scheduled_at": None,
            "is_sent": 1,
        })
        added += 1

    with open(_ANNOUNCEMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    await audit(db, actor, "broadcast", "platform", "global", "broadcast",
                f"title={body.title!r}, tenants={added}")
    return {"ok": True, "sent_to": added, "title": body.title}


# ═══════════════════════════════════════════════════════════════════════════════
# ROLES OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/stats/roles")
async def get_roles_stats(
    _: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Bütün platformda hər rola görə istifadəçi sayı."""
    import sqlalchemy as _sa
    result = await db.execute(_sa.text("""
        SELECT role, COUNT(*) as cnt,
               SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) as active_cnt
        FROM users GROUP BY role ORDER BY cnt DESC
    """))
    return [
        {"role": r.role, "total": r.cnt, "active": r.active_cnt}
        for r in result.fetchall()
    ]
