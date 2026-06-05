"""
Repetitor Router
----------------
/repetitor/* — fərdi repetitor müəllimlər üçün API endpoint-lər

Repetitor: plan='repetitor' olan tenant-ın teacher role-lu istifadəçisi.
Şagirdlər, seanslar və ödənişlər bu endpoint-lər vasitəsilə idarə olunur.
"""

import json
import uuid as _uuid
from pathlib import Path as _Path
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List

from app.database import get_db
from app.dependencies import require_role
from app.models.user import User
from app.models.tenant import Tenant
from app.models.repetitor import (
    RepetitorClass, RepetitorSubject, RepetitorTopic, RepetitorStudent, RepetitorSession,
    RepetitorPayment, RepetitorDailyGrade, RepetitorMeeting, RepetitorQuestion,
    RepetitorExam, RepetitorExamQuestion, RepetitorMessage, RepetitorChatClear,
    RepetitorExpense,
)
from app.models.student import Student
from app.models.class_model import Class
from app.models.message import Message
from app.services.auth_service import hash_password

router = APIRouter(prefix="/repetitor", tags=["Repetitor"])
require_teacher = require_role("teacher", "admin", "superadmin")


async def require_active_repetitor(
    current_user: User = Depends(require_role("teacher", "admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Write əməliyyatları üçün — pulsuz (demo) planda olan repetitorlara 403 qaytarır."""
    t_res = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    t = t_res.scalar_one_or_none()
    if not t or t.plan != "repetitor":
        raise HTTPException(
            status_code=403,
            detail="Pulsuz planda yazma əməliyyatları bağlıdır. Davam etmək üçün bizimlə əlaqə saxlayın."
        )
    return current_user


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


# ── Schemas ────────────────────────────────────────────────────────────────

class RepStats(BaseModel):
    total_students: int
    active_students: int
    sessions_today: int
    sessions_this_week: int
    monthly_revenue: int      # qepik
    unpaid_amount: int        # qepik
    avg_score: int
    total_sessions: int


class SessionOut(BaseModel):
    id: str
    student_id: str
    student_name: str
    subject: str
    scheduled_at: str
    duration_min: int
    status: str
    score: Optional[int] = None
    notes: Optional[str] = None


class UnpaidOut(BaseModel):
    student_id: str
    student_name: str
    amount: int
    month: str


class StudentOut(BaseModel):
    id: str
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    subject: Optional[str] = None
    grade: Optional[str] = None
    hourly_rate: Optional[int] = None
    notes: Optional[str] = None
    is_active: int = 1
    total_sessions: int = 0
    avg_score: int = 0
    unpaid_amount: float = 0.0
    has_account: bool = False         # şagird login hesabı varmı
    has_parent_account: bool = False  # valideyn login hesabı varmı
    parent_email: Optional[str] = None


class PaymentOut(BaseModel):
    id: str
    student_id: str
    student_name: str
    amount: int
    paid_amount: int = 0
    method: Optional[str] = None
    month: str
    payment_date: Optional[str] = None
    status: str
    paid_at: Optional[str] = None
    note: Optional[str] = None


def _payment_out(p, name: str) -> "PaymentOut":
    return PaymentOut(
        id=p.id, student_id=p.student_id, student_name=name,
        amount=p.amount, paid_amount=getattr(p, 'paid_amount', 0) or 0,
        method=getattr(p, 'method', None), month=p.month,
        payment_date=getattr(p, 'payment_date', None),
        status=p.status, paid_at=p.paid_at, note=p.note,
    )


# ── Create Schemas ─────────────────────────────────────────────────────────

class StudentCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    subject: str = ""
    grade: Optional[str] = None
    hourly_rate: int = 0
    notes: Optional[str] = None
    password: Optional[str] = None         # verilibsə şagird login hesabı yaradılır
    parent_email: Optional[str] = None     # valideyn hesabı üçün e-poçt
    parent_password: Optional[str] = None  # verilibsə valideyn login hesabı yaradılır


class StudentUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    subject: Optional[str] = None
    grade: Optional[str] = None
    hourly_rate: Optional[int] = None
    notes: Optional[str] = None
    is_active: Optional[int] = None
    password: Optional[str] = None          # şagird parolu yaradılır/yenilənir
    parent_email: Optional[str] = None
    parent_password: Optional[str] = None   # valideyn parolu yaradılır/yenilənir


class SessionCreate(BaseModel):
    student_id: str
    subject: str = ""
    scheduled_at: str
    duration_min: int = 60
    notes: Optional[str] = None


class SessionUpdate(BaseModel):
    status: Optional[str] = None
    score: Optional[int] = None
    notes: Optional[str] = None
    scheduled_at: Optional[str] = None
    duration_min: Optional[int] = None


class PaymentCreate(BaseModel):
    student_id: str
    amount: int
    month: str
    payment_date: Optional[str] = None   # "2026-05-15" — tam tarix (frontend-dən gəlir)
    note: Optional[str] = None


class PaymentBulkClass(BaseModel):
    grade: str                           # sinif/qrup adı (RepetitorStudent.grade)
    amount: int                          # qepik — hər şagird üçün eyni məbləğ
    month: str                           # "2026-05" və ya tam tarix
    payment_date: Optional[str] = None
    note: Optional[str] = None


class PaymentBulkAll(BaseModel):
    amount: int                          # qepik — hər şagird üçün eyni məbləğ
    month: str
    payment_date: Optional[str] = None
    note: Optional[str] = None


class PaymentBulkResult(BaseModel):
    created: int
    skipped: int
    total_students: int
    total_amount: int                    # qepik — yaradılan ödənişlərin cəmi
    month: str


class PaymentMarkPaid(BaseModel):
    paid_at: Optional[str] = None
    amount: Optional[int] = None       # qepik — qismi ödəniş məbləği; None = tam ödəniş
    method: Optional[str] = None       # cash|card|transfer


class DailyGradeCreate(BaseModel):
    student_id: str
    subject: str
    grade: int
    date: str
    note: Optional[str] = None


class DailyGradeOut(BaseModel):
    id: str
    student_id: str
    student_name: str
    subject: str
    grade: int
    date: str
    note: Optional[str] = None


# ── Subject Schemas ────────────────────────────────────────────────────────

class SubjectOut(BaseModel):
    id: str
    name: str

class SubjectCreate(BaseModel):
    name: str

class SubjectBulk(BaseModel):
    names: List[str]   # qeydiyyatdan sonra toplu əlavə üçün


# ── Subjects ───────────────────────────────────────────────────────────────

async def _sync_subjects_json(user: User, db: AsyncSession) -> None:
    """repetitor_subjects cədvəlini oxuyub user.subjects_json-u yenilə."""
    result = await db.execute(
        select(RepetitorSubject)
        .where(RepetitorSubject.teacher_id == user.id)
        .order_by(RepetitorSubject.name)
    )
    names = [s.name for s in result.scalars().all()]
    user.subjects_json = json.dumps(names, ensure_ascii=False)
    await db.commit()


@router.get("/subjects", response_model=List[SubjectOut])
async def list_subjects(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorSubject)
        .where(RepetitorSubject.teacher_id == current_user.id)
        .order_by(RepetitorSubject.name)
    )
    return [SubjectOut(id=s.id, name=s.name) for s in result.scalars().all()]


@router.post("/subjects", response_model=SubjectOut, status_code=201)
async def add_subject(
    body: SubjectCreate,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Subject name required")
    # dublikat yoxla
    existing = await db.execute(
        select(RepetitorSubject).where(
            and_(RepetitorSubject.teacher_id == current_user.id,
                 RepetitorSubject.name == name)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Subject already exists")
    s = RepetitorSubject(teacher_id=current_user.id, name=name)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    await _sync_subjects_json(current_user, db)
    return SubjectOut(id=s.id, name=s.name)


@router.post("/subjects/bulk", response_model=List[SubjectOut], status_code=201)
async def bulk_add_subjects(
    body: SubjectBulk,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Qeydiyyatdan sonra bir anda birdən çox fənn əlavə etmək üçün."""
    added = []
    for name in body.names:
        name = name.strip()
        if not name:
            continue
        existing = await db.execute(
            select(RepetitorSubject).where(
                and_(RepetitorSubject.teacher_id == current_user.id,
                     RepetitorSubject.name == name)
            )
        )
        if existing.scalar_one_or_none():
            continue
        s = RepetitorSubject(teacher_id=current_user.id, name=name)
        db.add(s)
        added.append(s)
    await db.commit()
    for s in added:
        await db.refresh(s)
    await _sync_subjects_json(current_user, db)
    return [SubjectOut(id=s.id, name=s.name) for s in added]


@router.delete("/subjects/{subject_id}", status_code=204)
async def delete_subject(
    subject_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorSubject).where(
            and_(RepetitorSubject.id == subject_id,
                 RepetitorSubject.teacher_id == current_user.id)
        )
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Subject not found")
    await db.delete(s)
    await db.commit()
    await _sync_subjects_json(current_user, db)


# ── Topics ────────────────────────────────────────────────────────────────

class TopicOut(BaseModel):
    id: str
    subject: str
    name: str


class TopicCreate(BaseModel):
    subject: str
    name: str


@router.get("/topics", response_model=List[TopicOut])
async def list_topics(
    subject: Optional[str] = Query(None),
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    q = select(RepetitorTopic).where(RepetitorTopic.teacher_id == current_user.id)
    if subject:
        q = q.where(RepetitorTopic.subject == subject)
    q = q.order_by(RepetitorTopic.name)
    result = await db.execute(q)
    return [TopicOut(id=t.id, subject=t.subject, name=t.name) for t in result.scalars().all()]


@router.post("/topics", response_model=TopicOut, status_code=201)
async def add_topic(
    body: TopicCreate,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    name = body.name.strip()
    subject = body.subject.strip()
    if not name or not subject:
        raise HTTPException(400, "Subject and name are required")
    # dublikat yoxla
    existing = await db.execute(
        select(RepetitorTopic).where(
            and_(RepetitorTopic.teacher_id == current_user.id,
                 RepetitorTopic.subject == subject,
                 RepetitorTopic.name == name)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Topic already exists")
    t = RepetitorTopic(teacher_id=current_user.id, subject=subject, name=name)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return TopicOut(id=t.id, subject=t.subject, name=t.name)


@router.delete("/topics/{topic_id}", status_code=204)
async def delete_topic(
    topic_id: str,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorTopic).where(
            and_(RepetitorTopic.id == topic_id,
                 RepetitorTopic.teacher_id == current_user.id)
        )
    )
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Topic not found")
    await db.delete(t)
    await db.commit()


# ── Classes ────────────────────────────────────────────────────────────────

class RepClassOut(BaseModel):
    id: str
    name: str

class RepClassCreate(BaseModel):
    name: str


@router.get("/classes", response_model=List[RepClassOut])
async def list_rep_classes(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorClass)
        .where(RepetitorClass.teacher_id == current_user.id)
        .order_by(RepetitorClass.name)
    )
    return [RepClassOut(id=c.id, name=c.name) for c in result.scalars().all()]


@router.post("/classes", response_model=RepClassOut, status_code=201)
async def create_rep_class(
    body: RepClassCreate,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Sinif adı boş ola bilməz")
    existing = await db.execute(
        select(RepetitorClass).where(
            RepetitorClass.teacher_id == current_user.id,
            RepetitorClass.name == name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Bu adda sinif artıq mövcuddur")
    c = RepetitorClass(teacher_id=current_user.id, name=name)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return RepClassOut(id=c.id, name=c.name)


@router.delete("/classes/{class_id}", status_code=204)
async def delete_rep_class(
    class_id: str,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorClass).where(
            RepetitorClass.id == class_id,
            RepetitorClass.teacher_id == current_user.id,
        )
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Sinif tapılmadı")
    # Şagirdlərin grade-ini null et
    import sqlalchemy as sa
    await db.execute(
        sa.update(RepetitorStudent)
        .where(RepetitorStudent.teacher_id == current_user.id,
               RepetitorStudent.grade == c.name)
        .values(grade=None)
    )
    await db.delete(c)
    await db.commit()


# ── Stats ──────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=RepStats)
async def get_stats(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    tid = current_user.id
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Week start (Monday)
    now = datetime.now(timezone.utc)
    # B6 fix: use proper timedelta import instead of __import__
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    month = _current_month()

    # Students — RepetitorStudent + platform şagirdləri (users cədvəli), list_students ilə eyni dedup məntiqi
    stu_q = await db.execute(select(RepetitorStudent).where(RepetitorStudent.teacher_id == tid))
    students = stu_q.scalars().all()
    rep_emails = {s.email.strip().lower() for s in students if s.email}

    plat_q = await db.execute(
        select(User).where(
            User.tenant_id == current_user.tenant_id,
            User.role == "student",
        )
    )
    platform_users = plat_q.scalars().all()
    # Artıq RepetitorStudent-də olan e-poçtları platformadan çıxar (dedup)
    unique_platform_count = sum(
        1 for u in platform_users
        if (u.email or "").strip().lower() not in rep_emails
    )

    total_students = len(students) + unique_platform_count
    active_students = sum(1 for s in students if s.is_active) + unique_platform_count

    # Sessions
    ses_q = await db.execute(select(RepetitorSession).where(RepetitorSession.teacher_id == tid))
    sessions = ses_q.scalars().all()
    total_sessions = len(sessions)
    sessions_today = sum(1 for s in sessions if s.scheduled_at.startswith(today))
    sessions_this_week = sum(1 for s in sessions if s.scheduled_at >= week_start)

    # Avg score (completed sessions with score)
    scored = [s.score for s in sessions if s.status == "completed" and s.score is not None]
    avg_score = round(sum(scored) / len(scored)) if scored else 0

    # Payments
    pay_q = await db.execute(select(RepetitorPayment).where(RepetitorPayment.teacher_id == tid))
    payments = pay_q.scalars().all()
    monthly_revenue = sum(p.amount for p in payments if p.status == "paid" and p.month == month)
    unpaid_amount = sum(p.amount for p in payments if p.status == "unpaid")

    return RepStats(
        total_students=total_students,
        active_students=active_students,
        sessions_today=sessions_today,
        sessions_this_week=sessions_this_week,
        monthly_revenue=monthly_revenue,
        unpaid_amount=unpaid_amount,
        avg_score=avg_score,
        total_sessions=total_sessions,
    )


# ── Students ───────────────────────────────────────────────────────────────

@router.get("/students", response_model=List[StudentOut])
async def list_students(
    active_only: bool = Query(False),
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    # ── 1. RepetitorStudent cədvəlindəki şagirdlər (mövcud sistem) ────────────
    q = select(RepetitorStudent).where(RepetitorStudent.teacher_id == current_user.id)
    if active_only:
        q = q.where(RepetitorStudent.is_active == 1)
    q = q.order_by(RepetitorStudent.created_at.desc())
    result = await db.execute(q)
    rep_students = result.scalars().all()

    # RepetitorStudent-dəki e-poçtları topla (dedup üçün)
    rep_emails = {s.email.strip().lower() for s in rep_students if s.email}

    out = []
    for s in rep_students:
        ses_r = await db.execute(
            select(RepetitorSession).where(RepetitorSession.student_id == s.id)
        )
        ses = ses_r.scalars().all()
        total_sessions = len(ses)
        scored = [x.score for x in ses if x.status == "completed" and x.score is not None]
        avg_score = round(sum(scored) / len(scored)) if scored else 0

        pay_r = await db.execute(
            select(RepetitorPayment).where(
                and_(RepetitorPayment.student_id == s.id, RepetitorPayment.status == "unpaid")
            )
        )
        unpaid = pay_r.scalars().all()
        unpaid_amount = sum(p.amount for p in unpaid)

        out.append(StudentOut(
            id=s.id, name=s.name, phone=s.phone, email=s.email,
            subject=s.subject, grade=s.grade, hourly_rate=s.hourly_rate,
            notes=s.notes, is_active=s.is_active,
            total_sessions=total_sessions, avg_score=avg_score, unpaid_amount=unpaid_amount,
            has_account=bool(s.user_id),
            has_parent_account=bool(s.parent_user_id),
            parent_email=await _parent_email_of(s, db),
        ))

    # ── 2. Platform şagirdləri (users cədvəli, role="student", eyni tenant) ───
    # RepetitorStudent-də e-poçtu olmayan və ya olmayan platform şagirdlərini əlavə et
    platform_q = (
        select(User)
        .where(
            User.tenant_id == current_user.tenant_id,
            User.role == "student",
        )
        .order_by(User.created_at.desc())
    )
    platform_res = await db.execute(platform_q)
    platform_users = platform_res.scalars().all()

    for u in platform_users:
        email_key = (u.email or "").strip().lower()
        # Temp e-poçtu olan (noemail_*) və ya artıq RepetitorStudent-də olanları atla
        if email_key in rep_emails:
            continue
        if active_only:
            continue  # platform şagirdlərinin is_active konsepti yoxdur, active_only filtri tətbiq etmə

        # Platform şagirdinin sinif və fənnini tap (students → classes cədvəli vasitəsilə)
        grade_name = None
        subject_name = None
        stu_rec = await db.execute(select(Student).where(Student.user_id == u.id))
        stu_obj = stu_rec.scalar_one_or_none()
        if stu_obj and stu_obj.class_id:
            cls_rec = await db.execute(select(Class).where(Class.id == stu_obj.class_id))
            cls_obj = cls_rec.scalar_one_or_none()
            if cls_obj:
                grade_name = cls_obj.name
                subject_name = cls_obj.subject

        out.append(StudentOut(
            id=u.id,
            name=u.name,
            phone=None,
            email=u.email if not email_key.endswith("@temp.local") else "",
            subject=subject_name,
            grade=grade_name,
            hourly_rate=None,
            notes=None,
            is_active=True,
            total_sessions=0,
            avg_score=0,
            unpaid_amount=0.0,
        ))

    return out


async def _ensure_student_account(
    s: RepetitorStudent, email: Optional[str], password: str,
    teacher: User, db: AsyncSession,
) -> None:
    """Repetitor şagirdi üçün login hesabı (User + Student profil) yaradır və ya parolu yeniləyir.

    - s.user_id varsa → mövcud hesabın parolunu yenilə
    - yoxdursa → yeni User + Student profil yarat, s.user_id təyin et
    """
    if len(password) < 6:
        raise HTTPException(400, "Parol ən azı 6 simvol olmalıdır")

    # Mövcud hesab → parol yenilə
    if s.user_id:
        u_res = await db.execute(select(User).where(User.id == s.user_id))
        u = u_res.scalar_one_or_none()
        if u:
            u.hashed_password = hash_password(password)
            return

    # Yeni hesab → email tələb olunur
    mail = (email or s.email or "").strip().lower()
    if not mail:
        raise HTTPException(400, "Hesab yaratmaq üçün e-poçt mütləqdir")

    # Email başqa istifadəçidə var?
    exists = await db.execute(select(User).where(func.lower(User.email) == mail).limit(1))
    if exists.scalars().first():
        raise HTTPException(409, f"Bu e-poçt artıq istifadə olunur: {mail}")

    u = User(
        tenant_id=teacher.tenant_id,
        name=s.name,
        email=mail,
        hashed_password=hash_password(password),
        role="student",
        is_active=True,
    )
    db.add(u)
    await db.flush()   # u.id almaq üçün

    # Student profil (sinifsiz — repetitor şagirdi)
    profile = Student(user_id=u.id, class_id=None)
    db.add(profile)

    s.user_id = u.id


async def _ensure_parent_account(
    s: RepetitorStudent, email: Optional[str], password: str,
    teacher: User, db: AsyncSession,
) -> None:
    """Repetitor şagirdinin valideyni üçün login hesabı (User, role=parent) yaradır/yeniləyir."""
    if len(password) < 6:
        raise HTTPException(400, "Valideyn parolu ən azı 6 simvol olmalıdır")

    # Mövcud valideyn hesabı → parol yenilə
    if s.parent_user_id:
        u_res = await db.execute(select(User).where(User.id == s.parent_user_id))
        u = u_res.scalar_one_or_none()
        if u:
            u.hashed_password = hash_password(password)
            if email and email.strip():
                u.email = email.strip().lower()
            return

    mail = (email or "").strip().lower()
    if not mail:
        raise HTTPException(400, "Valideyn hesabı üçün e-poçt mütləqdir")

    exists = await db.execute(select(User).where(func.lower(User.email) == mail).limit(1))
    if exists.scalars().first():
        raise HTTPException(409, f"Bu e-poçt artıq istifadə olunur: {mail}")

    u = User(
        tenant_id=teacher.tenant_id,
        name=f"{s.name} (valideyn)",
        email=mail,
        hashed_password=hash_password(password),
        role="parent",
        is_active=True,
    )
    db.add(u)
    await db.flush()
    s.parent_user_id = u.id


async def _parent_email_of(s: RepetitorStudent, db: AsyncSession) -> Optional[str]:
    if not s.parent_user_id:
        return None
    r = await db.execute(select(User.email).where(User.id == s.parent_user_id))
    return r.scalars().first()


async def _ensure_current_month_payment(s: RepetitorStudent, teacher_id: str, db: AsyncSession):
    """Aylıq haqqı olan şagird üçün cari ayın borcunu yarat (yoxdursa)."""
    if not (s.hourly_rate and s.hourly_rate > 0):
        return
    month = _current_month()
    ex = await db.execute(
        select(RepetitorPayment).where(
            and_(RepetitorPayment.teacher_id == teacher_id,
                 RepetitorPayment.student_id == s.id,
                 RepetitorPayment.month == month)
        ).limit(1)
    )
    existing = ex.scalars().first()
    if existing:
        # Cari ay ödənilməmişdirsə — məbləği həmişə yeni tarifə uyğunlaşdır
        # (paid/partial qeydlərə toxunmuruq ki, ödəniş tarixçəsi pozulmasın)
        if existing.status == "unpaid":
            existing.amount = s.hourly_rate
            if not existing.payment_date:
                existing.payment_date = month + "-01"
        return
    db.add(RepetitorPayment(
        teacher_id=teacher_id, student_id=s.id,
        amount=s.hourly_rate, month=month,
        payment_date=month + "-01", status="unpaid",
    ))


@router.post("/students", response_model=StudentOut, status_code=201)
async def create_student(
    body: StudentCreate,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    s = RepetitorStudent(
        teacher_id=current_user.id,
        name=body.name, phone=body.phone, email=body.email,
        subject=body.subject, grade=body.grade,
        hourly_rate=body.hourly_rate, notes=body.notes,
    )
    db.add(s)
    await db.flush()   # s.id

    # Şagird parolu verilibsə login hesabı yarat
    if body.password:
        await _ensure_student_account(s, body.email, body.password, current_user, db)
    # Valideyn parolu verilibsə valideyn hesabı yarat
    if body.parent_password:
        await _ensure_parent_account(s, body.parent_email, body.parent_password, current_user, db)

    # Aylıq haqq verilibsə cari ayın borcunu avtomatik yarat
    await _ensure_current_month_payment(s, current_user.id, db)

    await db.commit()
    await db.refresh(s)
    cm_unpaid = s.hourly_rate if (s.hourly_rate and s.hourly_rate > 0) else 0
    return StudentOut(
        id=s.id, name=s.name, phone=s.phone, email=s.email,
        subject=s.subject, grade=s.grade, hourly_rate=s.hourly_rate,
        notes=s.notes, is_active=s.is_active,
        total_sessions=0, avg_score=0, unpaid_amount=cm_unpaid,
        has_account=bool(s.user_id),
        has_parent_account=bool(s.parent_user_id),
        parent_email=await _parent_email_of(s, db),
    )


@router.patch("/students/{student_id}", response_model=StudentOut)
async def update_student(
    student_id: str,
    body: StudentUpdate,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorStudent).where(
            and_(RepetitorStudent.id == student_id, RepetitorStudent.teacher_id == current_user.id)
        )
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Student not found")

    if body.name is not None:        s.name = body.name
    if body.phone is not None:       s.phone = body.phone
    if body.email is not None:       s.email = body.email
    if body.subject is not None:     s.subject = body.subject
    if body.grade is not None:       s.grade = body.grade
    if body.hourly_rate is not None: s.hourly_rate = body.hourly_rate
    if body.notes is not None:       s.notes = body.notes
    if body.is_active is not None:   s.is_active = body.is_active

    # Şagird parolu verilibsə hesab yarat / parolu yenilə
    if body.password:
        await _ensure_student_account(s, body.email, body.password, current_user, db)
    # Valideyn parolu verilibsə valideyn hesabı yarat / yenilə
    if body.parent_password:
        await _ensure_parent_account(s, body.parent_email, body.parent_password, current_user, db)

    # Adı dəyişdisə bağlı şagird hesabının adını da yenilə
    if body.name is not None and s.user_id:
        u_res = await db.execute(select(User).where(User.id == s.user_id))
        u = u_res.scalar_one_or_none()
        if u:
            u.name = body.name

    # Aylıq haqq təyin/dəyişdirilibsə cari ayın borcunu avtomatik yarat (yoxdursa)
    if body.hourly_rate is not None:
        await _ensure_current_month_payment(s, current_user.id, db)

    await db.commit()
    await db.refresh(s)

    ses_r = await db.execute(select(RepetitorSession).where(RepetitorSession.student_id == s.id))
    ses = ses_r.scalars().all()
    scored = [x.score for x in ses if x.status == "completed" and x.score is not None]
    avg_score = round(sum(scored) / len(scored)) if scored else 0
    pay_r = await db.execute(
        select(RepetitorPayment).where(
            and_(RepetitorPayment.student_id == s.id, RepetitorPayment.status == "unpaid")
        )
    )
    unpaid_amount = sum(p.amount for p in pay_r.scalars().all())

    return StudentOut(
        id=s.id, name=s.name, phone=s.phone, email=s.email,
        subject=s.subject, grade=s.grade, hourly_rate=s.hourly_rate,
        notes=s.notes, is_active=s.is_active,
        total_sessions=len(ses), avg_score=avg_score, unpaid_amount=unpaid_amount,
        has_account=bool(s.user_id),
        has_parent_account=bool(s.parent_user_id),
        parent_email=await _parent_email_of(s, db),
    )


@router.delete("/students/{student_id}", status_code=204)
async def delete_student(
    student_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorStudent).where(
            and_(RepetitorStudent.id == student_id, RepetitorStudent.teacher_id == current_user.id)
        )
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Student not found")
    # Bağlı login hesablarını deaktiv et (silmirik — tarixçə qalsın)
    for uid in (s.user_id, s.parent_user_id):
        if uid:
            u_res = await db.execute(select(User).where(User.id == uid))
            u = u_res.scalar_one_or_none()
            if u:
                u.is_active = False
    await db.delete(s)
    await db.commit()


# ── Sessions ───────────────────────────────────────────────────────────────

@router.get("/sessions", response_model=List[SessionOut])
async def list_sessions(
    status: Optional[str] = Query(None),
    student_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    q = select(RepetitorSession).where(RepetitorSession.teacher_id == current_user.id)
    if status:
        q = q.where(RepetitorSession.status == status)
    if student_id:
        q = q.where(RepetitorSession.student_id == student_id)
    q = q.order_by(RepetitorSession.scheduled_at.asc()).limit(limit)

    result = await db.execute(q)
    sessions = result.scalars().all()

    out = []
    for s in sessions:
        # get student name
        stu_r = await db.execute(select(RepetitorStudent).where(RepetitorStudent.id == s.student_id))
        stu = stu_r.scalar_one_or_none()
        out.append(SessionOut(
            id=s.id,
            student_id=s.student_id,
            student_name=stu.name if stu else "?",
            subject=s.subject,
            scheduled_at=s.scheduled_at,
            duration_min=s.duration_min,
            status=s.status,
            score=s.score,
            notes=s.notes,
        ))
    return out


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(
    body: SessionCreate,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    # verify student belongs to this teacher
    stu_r = await db.execute(
        select(RepetitorStudent).where(
            and_(RepetitorStudent.id == body.student_id, RepetitorStudent.teacher_id == current_user.id)
        )
    )
    stu = stu_r.scalar_one_or_none()
    if not stu:
        raise HTTPException(404, "Student not found")

    s = RepetitorSession(
        teacher_id=current_user.id,
        student_id=body.student_id,
        subject=body.subject or stu.subject,
        scheduled_at=body.scheduled_at,
        duration_min=body.duration_min,
        notes=body.notes,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)

    return SessionOut(
        id=s.id, student_id=s.student_id, student_name=stu.name, subject=s.subject,
        scheduled_at=s.scheduled_at, duration_min=s.duration_min,
        status=s.status, score=s.score, notes=s.notes,
    )


@router.patch("/sessions/{session_id}", response_model=SessionOut)
async def update_session(
    session_id: str,
    body: SessionUpdate,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorSession).where(
            and_(RepetitorSession.id == session_id, RepetitorSession.teacher_id == current_user.id)
        )
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")

    if body.status is not None:       s.status = body.status
    if body.score is not None:        s.score = body.score
    if body.notes is not None:        s.notes = body.notes
    if body.scheduled_at is not None: s.scheduled_at = body.scheduled_at
    if body.duration_min is not None: s.duration_min = body.duration_min

    await db.commit()
    await db.refresh(s)

    stu_r = await db.execute(select(RepetitorStudent).where(RepetitorStudent.id == s.student_id))
    stu = stu_r.scalar_one_or_none()

    return SessionOut(
        id=s.id, student_id=s.student_id, student_name=stu.name if stu else "?", subject=s.subject,
        scheduled_at=s.scheduled_at, duration_min=s.duration_min,
        status=s.status, score=s.score, notes=s.notes,
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorSession).where(
            and_(RepetitorSession.id == session_id, RepetitorSession.teacher_id == current_user.id)
        )
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")
    await db.delete(s)
    await db.commit()


# ── Payments ───────────────────────────────────────────────────────────────

@router.get("/payments", response_model=List[PaymentOut])
async def list_payments(
    status: Optional[str] = Query(None),
    student_id: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    q = select(RepetitorPayment).where(RepetitorPayment.teacher_id == current_user.id)
    if status:
        q = q.where(RepetitorPayment.status == status)
    if student_id:
        q = q.where(RepetitorPayment.student_id == student_id)
    if month:
        q = q.where(RepetitorPayment.month == month)
    q = q.order_by(RepetitorPayment.created_at.desc())

    result = await db.execute(q)
    payments = result.scalars().all()

    # B4 fix: fetch all students in one query instead of N+1
    stu_res = await db.execute(
        select(RepetitorStudent).where(RepetitorStudent.teacher_id == current_user.id)
    )
    stu_map = {s.id: s for s in stu_res.scalars().all()}

    return [
        _payment_out(p, stu_map[p.student_id].name if p.student_id in stu_map else "?")
        for p in payments
    ]


@router.get("/payments/unpaid", response_model=List[UnpaidOut])
async def list_unpaid(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    q = select(RepetitorPayment).where(
        and_(RepetitorPayment.teacher_id == current_user.id, RepetitorPayment.status == "unpaid")
    ).order_by(RepetitorPayment.month.desc())

    result = await db.execute(q)
    payments = result.scalars().all()

    # B5 fix: fetch all students in one query
    stu_res = await db.execute(
        select(RepetitorStudent).where(RepetitorStudent.teacher_id == current_user.id)
    )
    stu_map = {s.id: s for s in stu_res.scalars().all()}

    return [
        UnpaidOut(
            student_id=p.student_id,
            student_name=stu_map[p.student_id].name if p.student_id in stu_map else "?",
            amount=p.amount,
            month=p.month,
        )
        for p in payments
    ]


@router.post("/payments", response_model=PaymentOut, status_code=201)
async def create_payment(
    body: PaymentCreate,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    # B1 fix: amount must be positive
    if body.amount <= 0:
        raise HTTPException(400, "Məbləğ sıfırdan böyük olmalıdır")

    stu_r = await db.execute(
        select(RepetitorStudent).where(
            and_(RepetitorStudent.id == body.student_id, RepetitorStudent.teacher_id == current_user.id)
        )
    )
    stu = stu_r.scalar_one_or_none()
    if not stu:
        raise HTTPException(404, "Student not found")

    # month: frontend tam tarixi göndərirsə (2026-05-15) ilk 7 simvolu götür
    month_val = body.month[:7] if body.month else body.month

    # B2 fix: prevent duplicate payment for same student+month
    # .limit(1) + .scalars().first() — dublikat varsa MultipleResultsFound atmır
    existing = await db.execute(
        select(RepetitorPayment).where(
            and_(
                RepetitorPayment.teacher_id == current_user.id,
                RepetitorPayment.student_id == body.student_id,
                RepetitorPayment.month == month_val,
            )
        ).limit(1)
    )
    if existing.scalars().first():
        raise HTTPException(409, f"{stu.name} üçün {month_val} ayında artıq ödəniş qeydi mövcuddur")

    # payment_date: göndərilmədisə month-dan cari ayın 1-i kimi qoy
    pay_date = body.payment_date or (month_val + "-01" if month_val else None)

    p = RepetitorPayment(
        teacher_id=current_user.id,
        student_id=body.student_id,
        amount=body.amount,
        month=month_val,
        payment_date=pay_date,
        note=body.note,
        status="unpaid",
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)

    return _payment_out(p, stu.name)


@router.post("/payments/bulk-all", response_model=PaymentBulkResult, status_code=201)
async def create_all_payment(
    body: PaymentBulkAll,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    """Bütün aktiv şagirdlərə eyni məbləğdə ödəniş qeydi yaradır.
    Həmin ay üçün artıq ödənişi olan şagird ötürülür (skip)."""
    if body.amount <= 0:
        raise HTTPException(400, "Məbləğ sıfırdan böyük olmalıdır")

    month_val = body.month[:7] if body.month else body.month
    pay_date = body.payment_date or (month_val + "-01" if month_val else None)

    stu_r = await db.execute(
        select(RepetitorStudent).where(
            and_(
                RepetitorStudent.teacher_id == current_user.id,
                RepetitorStudent.is_active == 1,
            )
        )
    )
    students = stu_r.scalars().all()
    if not students:
        raise HTTPException(404, "Aktiv şagird tapılmadı")

    existing_r = await db.execute(
        select(RepetitorPayment.student_id).where(
            and_(
                RepetitorPayment.teacher_id == current_user.id,
                RepetitorPayment.month == month_val,
            )
        )
    )
    already = set(existing_r.scalars().all())

    created = 0
    for stu in students:
        if stu.id in already:
            continue
        db.add(RepetitorPayment(
            teacher_id=current_user.id, student_id=stu.id,
            amount=body.amount, month=month_val, payment_date=pay_date,
            note=body.note, status="unpaid",
        ))
        created += 1

    await db.commit()
    return PaymentBulkResult(
        created=created, skipped=len(students) - created,
        total_students=len(students), total_amount=created * body.amount,
        month=month_val,
    )


@router.post("/payments/bulk-class", response_model=PaymentBulkResult, status_code=201)
async def create_class_payment(
    body: PaymentBulkClass,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    """Bir sinif/qrupdakı bütün aktiv şagirdlərə eyni məbləğdə ödəniş qeydi yaradır.
    Həmin ay üçün artıq ödənişi olan şagird ötürülür (skip)."""
    if body.amount <= 0:
        raise HTTPException(400, "Məbləğ sıfırdan böyük olmalıdır")
    grade = (body.grade or "").strip()
    if not grade:
        raise HTTPException(400, "Sinif/qrup seçilməlidir")

    month_val = body.month[:7] if body.month else body.month
    pay_date = body.payment_date or (month_val + "-01" if month_val else None)

    # Sinifdəki aktiv şagirdlər
    stu_r = await db.execute(
        select(RepetitorStudent).where(
            and_(
                RepetitorStudent.teacher_id == current_user.id,
                RepetitorStudent.grade == grade,
                RepetitorStudent.is_active == 1,
            )
        )
    )
    students = stu_r.scalars().all()
    if not students:
        raise HTTPException(404, f"'{grade}' sinfində aktiv şagird tapılmadı")

    # Bu ay üçün artıq ödənişi olan şagirdlər
    existing_r = await db.execute(
        select(RepetitorPayment.student_id).where(
            and_(
                RepetitorPayment.teacher_id == current_user.id,
                RepetitorPayment.month == month_val,
            )
        )
    )
    already = set(existing_r.scalars().all())

    created = 0
    for stu in students:
        if stu.id in already:
            continue
        db.add(RepetitorPayment(
            teacher_id=current_user.id,
            student_id=stu.id,
            amount=body.amount,
            month=month_val,
            payment_date=pay_date,
            note=body.note,
            status="unpaid",
        ))
        created += 1

    await db.commit()
    return PaymentBulkResult(
        created=created,
        skipped=len(students) - created,
        total_students=len(students),
        total_amount=created * body.amount,
        month=month_val,
    )


@router.patch("/payments/{payment_id}/pay", response_model=PaymentOut)
async def mark_paid(
    payment_id: str,
    body: PaymentMarkPaid = PaymentMarkPaid(),
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorPayment).where(
            and_(RepetitorPayment.id == payment_id, RepetitorPayment.teacher_id == current_user.id)
        )
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Payment not found")

    if body.method:
        p.method = body.method

    if body.amount is not None:
        # Qismi ödəniş: cari ödənilənə əlavə et
        if body.amount <= 0:
            raise HTTPException(400, "Məbləğ sıfırdan böyük olmalıdır")
        p.paid_amount = (getattr(p, 'paid_amount', 0) or 0) + body.amount
        if p.paid_amount >= p.amount:
            p.paid_amount = p.amount
            p.status = "paid"
            p.paid_at = body.paid_at or _now_iso()
        else:
            p.status = "partial"
    else:
        # Tam ödəniş
        p.paid_amount = p.amount
        p.status = "paid"
        p.paid_at = body.paid_at or _now_iso()

    await db.commit()
    await db.refresh(p)

    stu_r = await db.execute(select(RepetitorStudent).where(RepetitorStudent.id == p.student_id))
    stu = stu_r.scalar_one_or_none()
    return _payment_out(p, stu.name if stu else "?")


class RemindOut(BaseModel):
    sent: bool
    to: Optional[str] = None
    detail: str


@router.post("/payments/{payment_id}/remind", response_model=RemindOut)
async def remind_payment(
    payment_id: str,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    """Borclu şagirdə/valideynə e-mail xatırlatma göndər."""
    r = await db.execute(
        select(RepetitorPayment).where(
            and_(RepetitorPayment.id == payment_id, RepetitorPayment.teacher_id == current_user.id)
        )
    )
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Payment not found")

    sr = await db.execute(select(RepetitorStudent).where(RepetitorStudent.id == p.student_id))
    stu = sr.scalar_one_or_none()
    if not stu:
        raise HTTPException(404, "Student not found")

    to = (stu.email or "").strip() or (getattr(stu, "parent_email", "") or "").strip()
    if not to:
        # Valideyn user hesabının e-poçtu
        if stu.parent_user_id:
            pu = await db.execute(select(User).where(User.id == stu.parent_user_id))
            puo = pu.scalar_one_or_none()
            if puo and puo.email:
                to = puo.email
    if not to:
        return RemindOut(sent=False, to=None, detail="Şagird/valideyn üçün e-poçt qeyd olunmayıb")

    paid = getattr(p, "paid_amount", 0) or 0
    debt = max(p.amount - paid, 0)
    azn_debt = f"{debt/100:.2f} ₼"
    month_label = p.month

    try:
        from app.services.email_service import send_event_email
        msg = (f"{month_label} ayı üzrə ödənişiniz gözləyir.<br><br>"
               f"<b>Borc məbləği: {azn_debt}</b><br><br>"
               f"Zəhmət olmasa, müəllimlə əlaqə saxlayıb ödənişi tamamlayın. Təşəkkürlər!")
        sent = await send_event_email(
            to, stu.name, "Ödəniş xatırlatması", msg,
            button_text="", button_url="",
        )
        return RemindOut(sent=bool(sent), to=to,
                         detail="Xatırlatma göndərildi" if sent else "E-mail göndərilə bilmədi")
    except Exception as e:
        return RemindOut(sent=False, to=to, detail=f"Xəta: {e}")


@router.delete("/payments/{payment_id}", status_code=204)
async def delete_payment(
    payment_id: str,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorPayment).where(
            and_(RepetitorPayment.id == payment_id, RepetitorPayment.teacher_id == current_user.id)
        )
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Payment not found")
    await db.delete(p)
    await db.commit()


# ── Xərclər (expenses) ─────────────────────────────────────────────────────

class ExpenseOut(BaseModel):
    id: str
    amount: int
    category: str
    date: str
    note: Optional[str] = None


class ExpenseCreate(BaseModel):
    amount: int
    category: str = "other"
    date: str
    note: Optional[str] = None


@router.get("/expenses", response_model=List[ExpenseOut])
async def list_expenses(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(RepetitorExpense)
        .where(RepetitorExpense.teacher_id == current_user.id)
        .order_by(RepetitorExpense.date.desc())
    )
    return [ExpenseOut(id=e.id, amount=e.amount, category=e.category, date=e.date, note=e.note)
            for e in r.scalars().all()]


@router.post("/expenses", response_model=ExpenseOut, status_code=201)
async def create_expense(
    body: ExpenseCreate,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    if body.amount <= 0:
        raise HTTPException(400, "Məbləğ sıfırdan böyük olmalıdır")
    e = RepetitorExpense(
        teacher_id=current_user.id, amount=body.amount,
        category=body.category or "other", date=body.date, note=body.note,
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return ExpenseOut(id=e.id, amount=e.amount, category=e.category, date=e.date, note=e.note)


@router.delete("/expenses/{expense_id}", status_code=204)
async def delete_expense(
    expense_id: str,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(RepetitorExpense).where(
            and_(RepetitorExpense.id == expense_id, RepetitorExpense.teacher_id == current_user.id)
        )
    )
    e = r.scalar_one_or_none()
    if not e:
        raise HTTPException(404, "Expense not found")
    await db.delete(e)
    await db.commit()


# ── Maliyyə hesabatı (professional summary) ────────────────────────────────

class FinanceSummaryOut(BaseModel):
    income_total: int          # bütün vaxt yığılan (paid_amount cəmi)
    income_month: int          # cari ay yığılan
    income_year: int           # cari il yığılan
    expected_total: int        # bütün gözlənilən (amount cəmi)
    outstanding: int           # qalıq borc (amount - paid_amount)
    overdue: int               # keçmiş aylar üzrə qalıq
    expense_total: int         # bütün xərc
    expense_month: int         # cari ay xərc
    net_profit: int            # income_total - expense_total
    net_profit_month: int      # income_month - expense_month
    collection_rate: float     # yığım faizi (%) = income / expected
    paid_count: int
    partial_count: int
    unpaid_count: int
    expense_by_category: dict   # {category: amount}


@router.get("/finance/summary", response_model=FinanceSummaryOut)
async def finance_summary(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    month = _current_month()
    year = month[:4]

    pr = await db.execute(
        select(RepetitorPayment).where(RepetitorPayment.teacher_id == current_user.id)
    )
    payments = pr.scalars().all()

    er = await db.execute(
        select(RepetitorExpense).where(RepetitorExpense.teacher_id == current_user.id)
    )
    expenses = er.scalars().all()

    def paid(p):  # qismi ödənişlə uyğun: paid_amount, yoxdursa status=paid → amount
        pa = getattr(p, 'paid_amount', 0) or 0
        if pa == 0 and p.status == "paid":
            return p.amount
        return pa

    income_total = sum(paid(p) for p in payments)
    income_month = sum(paid(p) for p in payments if p.month == month)
    income_year  = sum(paid(p) for p in payments if (p.month or "").startswith(year))
    expected_total = sum(p.amount for p in payments)
    outstanding = sum(max(p.amount - paid(p), 0) for p in payments if p.status != "paid")
    overdue = sum(max(p.amount - paid(p), 0) for p in payments if p.status != "paid" and p.month < month)

    expense_total = sum(e.amount for e in expenses)
    expense_month = sum(e.amount for e in expenses if (e.date or "")[:7] == month)

    by_cat: dict = {}
    for e in expenses:
        by_cat[e.category] = by_cat.get(e.category, 0) + e.amount

    collection_rate = round((income_total / expected_total) * 100, 1) if expected_total else 0.0

    return FinanceSummaryOut(
        income_total=income_total, income_month=income_month, income_year=income_year,
        expected_total=expected_total, outstanding=outstanding, overdue=overdue,
        expense_total=expense_total, expense_month=expense_month,
        net_profit=income_total - expense_total,
        net_profit_month=income_month - expense_month,
        collection_rate=collection_rate,
        paid_count=sum(1 for p in payments if p.status == "paid"),
        partial_count=sum(1 for p in payments if p.status == "partial"),
        unpaid_count=sum(1 for p in payments if p.status == "unpaid"),
        expense_by_category=by_cat,
    )


# ── Auto-generate monthly payments ────────────────────────────────────────

class GenerateMonthlyOut(BaseModel):
    created: int     # neçə yeni qeyd yaradıldı
    skipped: int     # artıq mövcud olduğu üçün keçildi
    month: str


@router.post("/payments/generate-monthly", response_model=GenerateMonthlyOut)
async def generate_monthly_payments(
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    """Cari ay üçün bütün aktiv şagirdlərə avtomatik 'unpaid' ödəniş qeydi yarat.
    Artıq qeydi olan şagirdlər skip edilir."""
    month = _current_month()

    # Aktiv şagirdlər
    stu_r = await db.execute(
        select(RepetitorStudent).where(
            and_(RepetitorStudent.teacher_id == current_user.id,
                 RepetitorStudent.is_active == 1)
        )
    )
    students = stu_r.scalars().all()

    created = 0
    skipped = 0
    for stu in students:
        # Bu ay üçün artıq qeyd var?
        # scalar_one_or_none() istifadə etmirik — dublikat ödəniş varsa MultipleResultsFound atır
        ex = await db.execute(
            select(RepetitorPayment).where(
                and_(RepetitorPayment.teacher_id == current_user.id,
                     RepetitorPayment.student_id == stu.id,
                     RepetitorPayment.month == month)
            ).limit(1)
        )
        if ex.scalars().first():
            skipped += 1
            continue

        # hourly_rate-dən standart məbləğ al (0-dırsa 0 qoy, sonra dəyişər)
        amount = stu.hourly_rate if stu.hourly_rate and stu.hourly_rate > 0 else 0

        p = RepetitorPayment(
            teacher_id=current_user.id,
            student_id=stu.id,
            amount=amount,
            month=month,
            payment_date=None,
            status="unpaid",
        )
        db.add(p)
        created += 1

    await db.commit()
    return GenerateMonthlyOut(created=created, skipped=skipped, month=month)


# ── Question Bank ─────────────────────────────────────────────────────────

class QuestionOut(BaseModel):
    id: str
    subject: str
    topic: str = ""
    text: str
    type: str
    options: List[str]
    correct_answer: Optional[str] = None
    difficulty: str
    points: int
    note: Optional[str] = None
    created_at: Optional[str] = None


_VALID_TYPES = ("mcq", "open", "truefalse")
_VALID_DIFFS = ("easy", "medium", "hard")


class QuestionCreate(BaseModel):
    subject: str = ""
    topic: str = ""
    text: str
    type: str = "mcq"
    options: List[str] = []
    correct_answer: Optional[str] = None
    difficulty: str = "medium"
    points: int = 1
    note: Optional[str] = None

    def clean_type(self) -> str:
        return self.type if self.type in _VALID_TYPES else "mcq"

    def clean_difficulty(self) -> str:
        return self.difficulty if self.difficulty in _VALID_DIFFS else "medium"

    def clean_points(self) -> int:
        return max(1, self.points)


class QuestionUpdate(BaseModel):
    subject: Optional[str] = None
    topic: Optional[str] = None
    text: Optional[str] = None
    type: Optional[str] = None
    options: Optional[List[str]] = None
    correct_answer: Optional[str] = None
    difficulty: Optional[str] = None
    points: Optional[int] = None
    note: Optional[str] = None


def _q_to_out(q: RepetitorQuestion) -> QuestionOut:
    import json as _json
    opts: List[str] = []
    if q.options:
        try:
            opts = _json.loads(q.options)
        except Exception:
            pass
    return QuestionOut(
        id=q.id, subject=q.subject, topic=getattr(q, 'topic', '') or '',
        text=q.text, type=q.type,
        options=opts, correct_answer=q.correct_answer,
        difficulty=q.difficulty, points=q.points, note=q.note,
        created_at=str(q.created_at) if q.created_at else None,
    )


@router.get("/questions", response_model=List[QuestionOut])
async def list_questions(
    subject: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),       # #1 fix: added topic filter
    type: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    q = select(RepetitorQuestion).where(RepetitorQuestion.teacher_id == current_user.id)
    if subject:    q = q.where(RepetitorQuestion.subject == subject)
    if topic:      q = q.where(RepetitorQuestion.topic == topic)        # #1
    if type:       q = q.where(RepetitorQuestion.type == type)
    if difficulty: q = q.where(RepetitorQuestion.difficulty == difficulty)
    q = q.order_by(RepetitorQuestion.created_at.desc())
    result = await db.execute(q)
    return [_q_to_out(r) for r in result.scalars().all()]


@router.post("/questions", response_model=QuestionOut, status_code=201)
async def create_question(
    body: QuestionCreate,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    import json as _json
    q = RepetitorQuestion(
        teacher_id=current_user.id,
        subject=body.subject,
        topic=body.topic,
        text=body.text,
        type=body.clean_type(),           # #10 fix: validated enum
        options=_json.dumps(body.options, ensure_ascii=False),
        correct_answer=body.correct_answer,
        difficulty=body.clean_difficulty(),  # #11 fix
        points=body.clean_points(),          # #11 fix
        note=body.note,
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return _q_to_out(q)


@router.post("/questions/bulk", response_model=List[QuestionOut], status_code=201)
async def bulk_create_questions(
    body: List[QuestionCreate],
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    """Excel-dən toplu sual idxalı — dublikat text+topic+subject kombinasiyaları atlanır."""
    import json as _json
    if not body:
        raise HTTPException(400, "Boş siyahı")

    # #2 fix: deduplication — fetch existing texts for this teacher/subject/topic
    created = []
    skipped = 0
    for item in body:
        # Eyni text+subject+topic artıq varsa atla
        dup = await db.execute(
            select(RepetitorQuestion).where(
                and_(
                    RepetitorQuestion.teacher_id == current_user.id,
                    RepetitorQuestion.subject == item.subject,
                    RepetitorQuestion.topic == item.topic,
                    RepetitorQuestion.text == item.text,
                )
            ).limit(1)
        )
        if dup.scalars().first():
            skipped += 1
            continue
        q = RepetitorQuestion(
            teacher_id=current_user.id,
            subject=item.subject,
            topic=item.topic,
            text=item.text,
            type=item.clean_type(),
            options=_json.dumps(item.options, ensure_ascii=False),
            correct_answer=item.correct_answer,
            difficulty=item.clean_difficulty(),
            points=item.clean_points(),
            note=item.note,
        )
        db.add(q)
        created.append(q)

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, f"DB xətası: {str(e)}")

    for q in created:
        await db.refresh(q)
    return [_q_to_out(q) for q in created]


@router.patch("/questions/{question_id}", response_model=QuestionOut)
async def update_question(
    question_id: str,
    body: QuestionUpdate,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    import json as _json
    result = await db.execute(
        select(RepetitorQuestion).where(
            and_(RepetitorQuestion.id == question_id,
                 RepetitorQuestion.teacher_id == current_user.id)
        )
    )
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(404, "Question not found")
    if body.subject is not None:    q.subject = body.subject
    if body.topic is not None:      q.topic = body.topic
    if body.text is not None:       q.text = body.text
    if body.type is not None:       q.type = body.type if body.type in _VALID_TYPES else q.type
    if body.options is not None:    q.options = _json.dumps(body.options, ensure_ascii=False)
    # #9 fix: correct_answer can be explicitly set to None via empty string sentinel
    if body.correct_answer is not None:
        q.correct_answer = body.correct_answer if body.correct_answer != "" else None
    if body.difficulty is not None: q.difficulty = body.difficulty if body.difficulty in _VALID_DIFFS else q.difficulty
    if body.points is not None:     q.points = max(1, body.points)
    if body.note is not None:       q.note = body.note
    await db.commit()
    await db.refresh(q)
    return _q_to_out(q)


@router.delete("/questions/{question_id}", status_code=204)
async def delete_question(
    question_id: str,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorQuestion).where(
            and_(RepetitorQuestion.id == question_id,
                 RepetitorQuestion.teacher_id == current_user.id)
        )
    )
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(404, "Question not found")
    await db.delete(q)
    await db.commit()


# ── Repetitor Exams ────────────────────────────────────────────────────────

class ExamQuestionOut(BaseModel):
    question_id: str
    order_num: int
    subject: str
    topic: str
    text: str
    type: str
    options: List[str]
    correct_answer: Optional[str] = None
    difficulty: str
    points: int
    note: Optional[str] = None


class ExamOut(BaseModel):
    id: str
    title: str
    subject: str
    duration_min: int
    total_points: int
    question_count: int
    created_at: Optional[str] = None
    questions: List[ExamQuestionOut] = []


class ExamCreate(BaseModel):
    title: str
    subject: str = ""
    duration_min: int = 45
    question_ids: List[str]   # ordered list of question IDs


@router.get("/exams", response_model=List[ExamOut])
async def list_exams(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    import json as _json
    result = await db.execute(
        select(RepetitorExam)
        .where(RepetitorExam.teacher_id == current_user.id)
        .order_by(RepetitorExam.created_at.desc())
    )
    exams = result.scalars().all()
    out = []
    for exam in exams:
        # count questions
        cnt_res = await db.execute(
            select(func.count(RepetitorExamQuestion.id)).where(RepetitorExamQuestion.exam_id == exam.id)
        )
        q_count = cnt_res.scalar() or 0
        out.append(ExamOut(
            id=exam.id, title=exam.title, subject=exam.subject,
            duration_min=exam.duration_min, total_points=exam.total_points,
            question_count=q_count,
            created_at=str(exam.created_at) if exam.created_at else None,
            questions=[],
        ))
    return out


@router.get("/exams/{exam_id}", response_model=ExamOut)
async def get_exam(
    exam_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    import json as _json
    res = await db.execute(
        select(RepetitorExam).where(
            and_(RepetitorExam.id == exam_id,
                 RepetitorExam.teacher_id == current_user.id)
        )
    )
    exam = res.scalar_one_or_none()
    if not exam:
        raise HTTPException(404, "Exam not found")

    eq_res = await db.execute(
        select(RepetitorExamQuestion)
        .where(RepetitorExamQuestion.exam_id == exam_id)
        .order_by(RepetitorExamQuestion.order_num)
    )
    eq_rows = eq_res.scalars().all()

    questions_out = []
    for eq in eq_rows:
        qr = await db.execute(select(RepetitorQuestion).where(RepetitorQuestion.id == eq.question_id))
        q = qr.scalar_one_or_none()
        if not q:
            continue
        opts: List[str] = []
        if q.options:
            try:
                opts = _json.loads(q.options)
            except Exception:
                pass
        questions_out.append(ExamQuestionOut(
            question_id=q.id, order_num=eq.order_num,
            subject=q.subject, topic=getattr(q, 'topic', '') or '',
            text=q.text, type=q.type, options=opts,
            correct_answer=q.correct_answer, difficulty=q.difficulty,
            points=q.points, note=q.note,
        ))

    return ExamOut(
        id=exam.id, title=exam.title, subject=exam.subject,
        duration_min=exam.duration_min, total_points=exam.total_points,
        question_count=len(questions_out),
        created_at=str(exam.created_at) if exam.created_at else None,
        questions=questions_out,
    )


@router.post("/exams", response_model=ExamOut, status_code=201)
async def create_exam(
    body: ExamCreate,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    import json as _json
    # #6 fix: validate all question_ids belong to this teacher before inserting
    valid_questions = []
    for qid in body.question_ids:
        qr = await db.execute(
            select(RepetitorQuestion).where(
                and_(RepetitorQuestion.id == qid,
                     RepetitorQuestion.teacher_id == current_user.id)
            )
        )
        q = qr.scalar_one_or_none()
        if not q:
            raise HTTPException(400, f"Sual tapılmadı və ya sizə aid deyil: {qid}")
        valid_questions.append(q)

    total_points = sum(q.points for q in valid_questions)

    exam = RepetitorExam(
        teacher_id=current_user.id,
        title=body.title,
        subject=body.subject,
        duration_min=body.duration_min,
        total_points=total_points,
    )
    db.add(exam)
    await db.flush()  # get exam.id

    for i, q in enumerate(valid_questions):
        eq = RepetitorExamQuestion(exam_id=exam.id, question_id=q.id, order_num=i)
        db.add(eq)

    await db.commit()
    await db.refresh(exam)

    return ExamOut(
        id=exam.id, title=exam.title, subject=exam.subject,
        duration_min=exam.duration_min, total_points=total_points,
        question_count=len(valid_questions),
        created_at=str(exam.created_at) if exam.created_at else None,
        questions=[],
    )


@router.delete("/exams/{exam_id}", status_code=204)
async def delete_exam(
    exam_id: str,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(RepetitorExam).where(
            and_(RepetitorExam.id == exam_id,
                 RepetitorExam.teacher_id == current_user.id)
        )
    )
    exam = res.scalar_one_or_none()
    if not exam:
        raise HTTPException(404, "Exam not found")
    # #8 fix: explicitly delete child rows first (async ORM cascade unreliable)
    await db.execute(
        select(RepetitorExamQuestion).where(RepetitorExamQuestion.exam_id == exam_id)
    )
    from sqlalchemy import delete as sa_delete
    await db.execute(sa_delete(RepetitorExamQuestion).where(RepetitorExamQuestion.exam_id == exam_id))
    await db.delete(exam)
    await db.commit()


# ── Progress (per-student) ─────────────────────────────────────────────────

class StudentProgress(BaseModel):
    student_id: str
    student_name: str
    subject: str
    total_sessions: int
    completed_sessions: int
    avg_score: int
    last_score: Optional[int] = None
    scores: List[int]        # xronoloji sıra ilə
    paid_total: int
    unpaid_total: int


@router.get("/progress", response_model=List[StudentProgress])
async def get_progress(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    stu_r = await db.execute(
        select(RepetitorStudent).where(
            and_(RepetitorStudent.teacher_id == current_user.id, RepetitorStudent.is_active == 1)
        ).order_by(RepetitorStudent.name)
    )
    students = stu_r.scalars().all()

    out = []
    for s in students:
        ses_r = await db.execute(
            select(RepetitorSession).where(
                RepetitorSession.student_id == s.id
            ).order_by(RepetitorSession.scheduled_at)
        )
        sessions = ses_r.scalars().all()
        completed = [x for x in sessions if x.status == "completed"]
        scored = [x.score for x in completed if x.score is not None]
        avg_score = round(sum(scored) / len(scored)) if scored else 0

        pay_r = await db.execute(select(RepetitorPayment).where(RepetitorPayment.student_id == s.id))
        payments = pay_r.scalars().all()
        paid_total = sum(p.amount for p in payments if p.status == "paid")
        unpaid_total = sum(p.amount for p in payments if p.status == "unpaid")

        out.append(StudentProgress(
            student_id=s.id, student_name=s.name, subject=s.subject,
            total_sessions=len(sessions),
            completed_sessions=len(completed),
            avg_score=avg_score,
            last_score=scored[-1] if scored else None,
            scores=scored,
            paid_total=paid_total,
            unpaid_total=unpaid_total,
        ))
    return out


# ── Daily Grades ───────────────────────────────────────────────────────────

@router.get("/daily-grades", response_model=List[DailyGradeOut])
async def list_daily_grades(
    student_id: Optional[str] = Query(None),
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    q = select(RepetitorDailyGrade).where(RepetitorDailyGrade.teacher_id == current_user.id)
    if student_id:
        q = q.where(RepetitorDailyGrade.student_id == student_id)
    q = q.order_by(RepetitorDailyGrade.date.desc())
    result = await db.execute(q)
    grades = result.scalars().all()

    out = []
    for g in grades:
        stu_r = await db.execute(select(RepetitorStudent).where(RepetitorStudent.id == g.student_id))
        stu = stu_r.scalar_one_or_none()
        out.append(DailyGradeOut(
            id=g.id, student_id=g.student_id,
            student_name=stu.name if stu else "?",
            subject=g.subject, grade=g.grade, date=g.date, note=g.note,
        ))
    return out


@router.post("/daily-grades", response_model=DailyGradeOut, status_code=201)
async def create_daily_grade(
    body: DailyGradeCreate,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    if not (1 <= body.grade <= 10):
        raise HTTPException(400, "Qiymət 1-10 arasında olmalıdır")

    # ── 1. RepetitorStudent cədvəlində axtar ────────────────────────────────
    stu_r = await db.execute(
        select(RepetitorStudent).where(
            and_(RepetitorStudent.id == body.student_id,
                 RepetitorStudent.teacher_id == current_user.id)
        )
    )
    stu = stu_r.scalar_one_or_none()

    # ── 2. Platform şagirdi ola bilər (users cədvəlindən) ──────────────────
    if not stu:
        platform_r = await db.execute(
            select(User).where(
                User.id == body.student_id,
                User.tenant_id == current_user.tenant_id,
                User.role == "student",
            )
        )
        platform_user = platform_r.scalar_one_or_none()
        if not platform_user:
            raise HTTPException(404, "Şagird tapılmadı")

        # Platform şagirdini repetitor_students-ə avtomatik əlavə et
        # (sinif və fənni students→classes cədvəlindən al)
        grade_name = None
        subject_name = None
        stu_rec = await db.execute(select(Student).where(Student.user_id == platform_user.id))
        stu_obj = stu_rec.scalar_one_or_none()
        if stu_obj and stu_obj.class_id:
            cls_rec = await db.execute(select(Class).where(Class.id == stu_obj.class_id))
            cls_obj = cls_rec.scalar_one_or_none()
            if cls_obj:
                grade_name = cls_obj.name
                subject_name = cls_obj.subject

        stu = RepetitorStudent(
            id=platform_user.id,   # eyni ID — dedup üçün
            teacher_id=current_user.id,
            name=platform_user.name,
            email=platform_user.email,
            subject=subject_name or "",
            grade=grade_name,
            is_active=1,
        )
        db.add(stu)
        try:
            await db.commit()
            await db.refresh(stu)
        except Exception:
            await db.rollback()
            # Artıq əlavə olunubsa yenidən al
            stu_r2 = await db.execute(
                select(RepetitorStudent).where(RepetitorStudent.id == body.student_id)
            )
            stu = stu_r2.scalar_one_or_none()
            if not stu:
                raise HTTPException(500, "Şagird əlavə edilə bilmədi")

    # ── 3. Eyni gün üçün mövcud qiymət varmı? (upsert) ───────────────────
    existing_r = await db.execute(
        select(RepetitorDailyGrade).where(
            RepetitorDailyGrade.teacher_id == current_user.id,
            RepetitorDailyGrade.student_id == stu.id,
            RepetitorDailyGrade.date == body.date,
        )
    )
    g = existing_r.scalar_one_or_none()

    if g:
        # Artıq var — yenilə
        g.subject = body.subject
        g.grade   = body.grade
        g.note    = body.note
    else:
        # Yeni qiymət yaz
        g = RepetitorDailyGrade(
            teacher_id=current_user.id,
            student_id=stu.id,
            subject=body.subject,
            grade=body.grade,
            date=body.date,
            note=body.note,
        )
        db.add(g)

    await db.commit()
    await db.refresh(g)

    return DailyGradeOut(
        id=g.id, student_id=g.student_id, student_name=stu.name,
        subject=g.subject, grade=g.grade, date=g.date, note=g.note,
    )


@router.delete("/daily-grades/{grade_id}", status_code=204)
async def delete_daily_grade(
    grade_id: str,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorDailyGrade).where(
            and_(RepetitorDailyGrade.id == grade_id, RepetitorDailyGrade.teacher_id == current_user.id)
        )
    )
    g = result.scalar_one_or_none()
    if not g:
        raise HTTPException(404, "Grade not found")
    await db.delete(g)
    await db.commit()


# ── Valideyn Görüşləri ──────────────────────────────────────────────────────

class MeetingIn(BaseModel):
    student_id: str
    title: str
    meeting_date: str          # "2026-06-01T14:00"
    duration_min: int = 30
    location: Optional[str] = None
    note: Optional[str] = None

class MeetingStatusIn(BaseModel):
    status: str                # planned | done | cancelled

class MeetingOut(BaseModel):
    id: str
    student_id: str
    student_name: str
    student_phone: Optional[str]
    title: str
    meeting_date: str
    duration_min: int
    location: Optional[str]
    note: Optional[str]
    status: str
    created_at: str


@router.get("/meetings", response_model=list[MeetingOut])
async def list_meetings(
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorMeeting, RepetitorStudent)
        .join(RepetitorStudent, RepetitorStudent.id == RepetitorMeeting.student_id)
        .where(RepetitorMeeting.teacher_id == current_user.id)
        .order_by(RepetitorMeeting.meeting_date)
    )
    return [
        MeetingOut(
            id=m.id, student_id=s.id, student_name=s.name,
            student_phone=s.phone, title=m.title,
            meeting_date=m.meeting_date, duration_min=m.duration_min,
            location=m.location, note=m.note, status=m.status,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m, s in result.all()
    ]


@router.post("/meetings", response_model=MeetingOut, status_code=201)
async def create_meeting(
    body: MeetingIn,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    # şagird bu müəllimə məxsusdurmu?
    s_res = await db.execute(
        select(RepetitorStudent).where(
            and_(RepetitorStudent.id == body.student_id,
                 RepetitorStudent.teacher_id == current_user.id)
        )
    )
    student = s_res.scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Şagird tapılmadı")

    m = RepetitorMeeting(
        teacher_id=current_user.id,
        student_id=body.student_id,
        title=body.title,
        meeting_date=body.meeting_date,
        duration_min=body.duration_min,
        location=body.location,
        note=body.note,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return MeetingOut(
        id=m.id, student_id=student.id, student_name=student.name,
        student_phone=student.phone, title=m.title,
        meeting_date=m.meeting_date, duration_min=m.duration_min,
        location=m.location, note=m.note, status=m.status,
        created_at=m.created_at.isoformat() if m.created_at else "",
    )


@router.patch("/meetings/{meeting_id}", response_model=MeetingOut)
async def update_meeting_status(
    meeting_id: str,
    body: MeetingStatusIn,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorMeeting, RepetitorStudent)
        .join(RepetitorStudent, RepetitorStudent.id == RepetitorMeeting.student_id)
        .where(RepetitorMeeting.id == meeting_id,
               RepetitorMeeting.teacher_id == current_user.id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(404, "Görüş tapılmadı")
    m, s = row
    if body.status not in ("planned", "done", "cancelled"):
        raise HTTPException(400, "Yanlış status")
    m.status = body.status
    await db.commit()
    return MeetingOut(
        id=m.id, student_id=s.id, student_name=s.name,
        student_phone=s.phone, title=m.title,
        meeting_date=m.meeting_date, duration_min=m.duration_min,
        location=m.location, note=m.note, status=m.status,
        created_at=m.created_at.isoformat() if m.created_at else "",
    )


@router.delete("/meetings/{meeting_id}", status_code=204)
async def delete_meeting(
    meeting_id: str,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RepetitorMeeting).where(
            and_(RepetitorMeeting.id == meeting_id,
                 RepetitorMeeting.teacher_id == current_user.id)
        )
    )
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Görüş tapılmadı")
    await db.delete(m)
    await db.commit()


# ── Messages ───────────────────────────────────────────────────────────────

class MsgOut(BaseModel):
    id: str
    student_id: str
    student_name: str
    direction: str    # out | in
    to_type: str      # student | parent
    content: Optional[str] = None
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    is_read: bool
    edited: bool = False
    created_at: str

class MsgCreate(BaseModel):
    student_id: str
    direction: str = "out"   # out | in
    to_type: str = "student" # student | parent
    content: str

class ConvOut(BaseModel):
    student_id: str
    student_name: str
    student_phone: str | None
    student_subject: str
    last_message: str
    last_time: str
    unread_count: int
    to_type_last: str   # last message to_type (student|parent)
    has_student_account: bool = False
    has_parent_account: bool = False


_MSG_UPLOAD = _Path("uploads") / "messages"
_IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".heic", ".heif"}
_VID_EXT = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v", ".ogg"}


def _classify_file(mime: str, ext: str) -> str:
    if mime.startswith("image/") or ext in _IMG_EXT:
        return "image"
    if mime.startswith("video/") or ext in _VID_EXT:
        return "video"
    return "document"


async def _save_msg_file(file: UploadFile) -> tuple[str, str, str]:
    """Mesaj faylını saxla → (url, original_name, file_type). Hər fayl qəbul olunur."""
    _MSG_UPLOAD.mkdir(parents=True, exist_ok=True)
    ext = _Path(file.filename or "file").suffix.lower()
    ftype = _classify_file(file.content_type or "", ext)
    unique = f"{_uuid.uuid4().hex}{ext}"
    (_MSG_UPLOAD / unique).write_bytes(await file.read())
    return f"/uploads/messages/{unique}", (file.filename or unique), ftype


def _msg_out(m: RepetitorMessage, student_name: str) -> MsgOut:
    return MsgOut(
        id=m.id,
        student_id=m.student_id,
        student_name=student_name,
        direction=m.direction,
        to_type=m.to_type,
        content=m.content or "",
        file_url=m.file_url, file_name=m.file_name, file_type=m.file_type,
        is_read=m.is_read,
        edited=m.edited_at is not None,
        created_at=m.created_at.strftime("%d.%m.%Y %H:%M") if m.created_at else "",
    )


@router.get("/messages", response_model=list[ConvOut])
async def list_conversations(
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    """Söhbət siyahısı — hər şagird üçün son mesaj + oxunmamış sayı."""
    # Bütün mesajları al (ən yeni əvvəl)
    res = await db.execute(
        select(RepetitorMessage)
        .where(RepetitorMessage.teacher_id == current_user.id)
        .order_by(RepetitorMessage.created_at.desc())
    )
    msgs = res.scalars().all()

    # Şagirdləri bir dəfə yüklə
    stu_res = await db.execute(
        select(RepetitorStudent).where(RepetitorStudent.teacher_id == current_user.id)
    )
    students = stu_res.scalars().all()
    # Self-heal: user_id boş, amma email uyğun User varsa avtomatik bağla
    for s in students:
        if not s.user_id and s.email:
            u = await db.execute(
                select(User.id).where(func.lower(User.email) == s.email.strip().lower(), User.role == "student").limit(1)
            )
            uid = u.scalars().first()
            if uid:
                s.user_id = uid
    await db.commit()
    stu_map = {s.id: s for s in students}

    # Söhbətlərə qruplaşdır
    seen: dict[str, ConvOut] = {}
    for m in msgs:
        stu = stu_map.get(m.student_id)
        if not stu:
            continue
        if m.student_id not in seen:
            if m.content:
                msg_preview = m.content[:80]
            elif m.file_type == "image":
                msg_preview = "📷 Şəkil"
            elif m.file_type == "video":
                msg_preview = "🎥 Video"
            else:
                msg_preview = f"📎 {m.file_name or 'Fayl'}"
            seen[m.student_id] = ConvOut(
                student_id=m.student_id,
                student_name=stu.name,
                student_phone=stu.phone,
                student_subject=stu.subject or "",
                last_message=msg_preview,
                last_time=m.created_at.strftime("%d.%m.%Y %H:%M") if m.created_at else "",
                unread_count=0,
                to_type_last=m.to_type,
                has_student_account=bool(stu.user_id),
                has_parent_account=bool(stu.parent_user_id),
            )
        if not m.is_read and m.direction == "in":
            seen[m.student_id].unread_count += 1

    # ── Körpü: bağlı şagird/valideynin platform mesajlarını da daxil et ──
    # (şagird ilk yazsa belə, RepetitorMessage olmasa da söhbət görünsün)
    user_to_student: dict[str, RepetitorStudent] = {}
    for s in stu_map.values():
        if s.user_id:        user_to_student[s.user_id] = s
        if s.parent_user_id: user_to_student[s.parent_user_id] = s

    if user_to_student:
        pm_res = await db.execute(
            select(Message)
            .where(
                and_(Message.to_user_id == current_user.id,
                     Message.from_user_id.in_(list(user_to_student.keys())))
            )
            .order_by(Message.created_at.desc())
        )
        for pm in pm_res.scalars().all():
            s = user_to_student.get(pm.from_user_id)
            if not s:
                continue
            to_type = "parent" if pm.from_user_id == s.parent_user_id else "student"
            ts = pm.created_at.strftime("%d.%m.%Y %H:%M") if pm.created_at else ""
            # Fayl mesajı üçün preview mətni
            if pm.content:
                preview = pm.content[:80]
            elif pm.file_type == "image":
                preview = "📷 Şəkil"
            elif pm.file_type == "video":
                preview = "🎥 Video"
            else:
                preview = f"📎 {pm.file_name or 'Fayl'}"
            if s.id not in seen:
                seen[s.id] = ConvOut(
                    student_id=s.id, student_name=s.name, student_phone=s.phone,
                    student_subject=s.subject or "", last_message=preview,
                    last_time=ts, unread_count=0, to_type_last=to_type,
                    has_student_account=bool(s.user_id),
                    has_parent_account=bool(s.parent_user_id),
                )
            else:
                # Daha yeni mesajdırsa son mesajı yenilə (pm-lər desc sıralı, ilk = ən yeni)
                if ts > seen[s.id].last_time:
                    seen[s.id].last_message = preview
                    seen[s.id].last_time = ts
                    seen[s.id].to_type_last = to_type
            if not pm.is_read:
                seen[s.id].unread_count += 1

    # Son vaxta görə sırala (ən yeni üstdə)
    return sorted(seen.values(), key=lambda c: c.last_time, reverse=True)


@router.get("/messages/{student_id}", response_model=list[MsgOut])
async def get_thread(
    student_id: str,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    """Bir şagirdin bütün mesaj tarixçəsi (köhnədən yeniyə)."""
    # Şagird bu müəllimə aiddir?
    stu_res = await db.execute(
        select(RepetitorStudent).where(
            and_(RepetitorStudent.id == student_id,
                 RepetitorStudent.teacher_id == current_user.id)
        ).limit(1)
    )
    stu = stu_res.scalars().first()
    if not stu:
        raise HTTPException(404, "Şagird tapılmadı")

    # Söhbət təmizlənibsə kəsim nöqtəsi (ondan əvvəlki mesajlar gizlənir)
    clr_res = await db.execute(
        select(RepetitorChatClear.cleared_at).where(
            and_(RepetitorChatClear.teacher_id == current_user.id,
                 RepetitorChatClear.student_id == student_id)
        ).limit(1)
    )
    cleared_at = clr_res.scalars().first()

    msg_conds = [RepetitorMessage.teacher_id == current_user.id,
                 RepetitorMessage.student_id == student_id,
                 RepetitorMessage.hidden == False]
    if cleared_at:
        msg_conds.append(RepetitorMessage.created_at > cleared_at)

    res = await db.execute(
        select(RepetitorMessage).where(and_(*msg_conds))
        .order_by(RepetitorMessage.created_at.asc())
    )
    msgs = res.scalars().all()

    _FMT = "%d.%m.%Y %H:%M"
    # (raw_datetime, MsgOut) — xam datetime ilə sıralayıb sonra göstər
    rows: list = []

    for m in msgs:
        if m.direction == "in" and not m.is_read:
            m.is_read = True
        rows.append((m.created_at, MsgOut(
            id=m.id, student_id=m.student_id, student_name=stu.name,
            direction=m.direction, to_type=m.to_type, content=m.content,
            is_read=m.is_read,
            created_at=m.created_at.strftime(_FMT) if m.created_at else "",
        )))

    # ── Körpü: şagird/valideynin öz panelindən gələn platform cavabları ──
    linked = {stu.user_id: "student", stu.parent_user_id: "parent"}
    linked_ids = [uid for uid in linked if uid]
    if linked_ids:
        pm_conds = [Message.from_user_id.in_(linked_ids),
                    Message.to_user_id == current_user.id]
        if cleared_at:
            pm_conds.append(Message.created_at > cleared_at)
        rep_res = await db.execute(
            select(Message).where(and_(*pm_conds))
            .order_by(Message.created_at.asc())
        )
        for pm in rep_res.scalars().all():
            # Repetitor bu gələn mesajı özü üçün silibsə (alan kimi) göstərmə
            if pm.deleted_by_receiver:
                continue
            if not pm.is_read:
                pm.is_read = True
            rows.append((pm.created_at, MsgOut(
                id=pm.id, student_id=student_id, student_name=stu.name,
                direction="in", to_type=linked.get(pm.from_user_id, "student"),
                content=pm.content or "",
                file_url=pm.file_url, file_name=pm.file_name, file_type=pm.file_type,
                is_read=True, edited=pm.edited_at is not None,
                created_at=pm.created_at.strftime(_FMT) if pm.created_at else "",
            )))

    await db.commit()

    # Xam datetime-a görə sırala (None-ları sona)
    from datetime import datetime as _dt
    rows.sort(key=lambda r: r[0] or _dt.min)
    return [mo for _, mo in rows]


@router.post("/messages", response_model=MsgOut, status_code=201)
async def send_message(
    student_id: str = Form(...),
    content: str = Form(""),
    direction: str = Form("out"),
    to_type: str = Form("student"),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    if direction not in ("out", "in"):
        raise HTTPException(400, "direction 'out' və ya 'in' olmalıdır")
    if to_type not in ("student", "parent"):
        raise HTTPException(400, "to_type 'student' və ya 'parent' olmalıdır")

    stu_res = await db.execute(
        select(RepetitorStudent).where(
            and_(RepetitorStudent.id == student_id,
                 RepetitorStudent.teacher_id == current_user.id)
        ).limit(1)
    )
    stu = stu_res.scalars().first()
    if not stu:
        raise HTTPException(404, "Şagird tapılmadı")

    has_file = bool(file and file.filename)
    if not content.strip() and not has_file:
        raise HTTPException(400, "Mesaj və ya fayl daxil edin")

    # Göndərilən (out) mesaj üçün hədəf hesab mövcud olmalıdır
    if direction == "out":
        if to_type == "student" and not stu.user_id:
            raise HTTPException(400, "Bu şagird üçün login hesabı yoxdur. Şagirdlərim → redaktə et bölməsindən hesab yaradın.")
        if to_type == "parent" and not stu.parent_user_id:
            raise HTTPException(400, "Bu şagird üçün valideyn hesabı yoxdur. Şagirdlərim → redaktə et bölməsindən valideyn hesabı yaradın.")

    file_url = file_name = file_type = None
    if has_file:
        file_url, file_name, file_type = await _save_msg_file(file)

    content_v = content.strip() or None
    m = RepetitorMessage(
        teacher_id=current_user.id,
        student_id=student_id,
        direction=direction,
        to_type=to_type,
        content=content_v,
        file_url=file_url, file_name=file_name, file_type=file_type,
        is_read=direction == "out",
    )
    db.add(m)

    # ── Körpü: göndərilən mesaj (out) bağlı login hesabına platform mesajı kimi çatdırılsın ──
    if direction == "out":
        target_user_id = stu.user_id if to_type == "student" else stu.parent_user_id
        if target_user_id:
            bridge = Message(
                from_user_id=current_user.id,
                to_user_id=target_user_id,
                content=content_v,
                file_url=file_url, file_name=file_name, file_type=file_type,
                is_read=False,
            )
            db.add(bridge)
            await db.flush()
            m.bridge_message_id = bridge.id

    await db.commit()
    await db.refresh(m)
    return _msg_out(m, stu.name)


@router.delete("/messages/{msg_id}", status_code=204)
async def delete_message(
    msg_id: str,
    scope: str = Query("me", regex="^(me|both)$"),   # me = özüm üçün, both = hər ikisindən
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(RepetitorMessage).where(
            and_(RepetitorMessage.id == msg_id,
                 RepetitorMessage.teacher_id == current_user.id)
        ).limit(1)
    )
    m = res.scalars().first()

    # RepetitorMessage tapılmadısa — bu merged platform mesajdır (şagird cavabı = gələn)
    if not m:
        pres = await db.execute(
            select(Message).where(
                and_(Message.id == msg_id, Message.to_user_id == current_user.id)
            ).limit(1)
        )
        pm = pres.scalars().first()
        if not pm:
            raise HTTPException(404, "Mesaj tapılmadı")
        # Gələn mesaj yalnız "özüm üçün" silinə bilər
        if scope == "both":
            raise HTTPException(400, "Gələn mesajı yalnız özünüz üçün silə bilərsiniz")
        pm.deleted_by_receiver = True
        await db.commit()
        return

    if scope == "me":
        # Öz ekranımdan gizlət (bazada qalır)
        m.hidden = True
    else:
        # Hər iki tərəfdən sil — yalnız göndərilən (out) mesaj
        if m.direction != "out":
            raise HTTPException(400, "Gələn mesajı yalnız özünüz üçün silə bilərsiniz")
        if m.bridge_message_id:
            bres = await db.execute(select(Message).where(Message.id == m.bridge_message_id).limit(1))
            bridge = bres.scalars().first()
            if bridge:
                await db.delete(bridge)
        await db.delete(m)

    await db.commit()


class MsgEdit(BaseModel):
    content: str


@router.patch("/messages/{msg_id}", response_model=MsgOut)
async def edit_message(
    msg_id: str,
    body: MsgEdit,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    """Repetitorun göndərdiyi (out) mesajı redaktə et. Körpü platform mesajı da yenilənir."""
    if not body.content.strip():
        raise HTTPException(400, "Mesaj boş ola bilməz")
    res = await db.execute(
        select(RepetitorMessage).where(
            and_(RepetitorMessage.id == msg_id,
                 RepetitorMessage.teacher_id == current_user.id)
        ).limit(1)
    )
    m = res.scalars().first()
    if not m:
        raise HTTPException(404, "Mesaj tapılmadı")
    if m.direction != "out":
        raise HTTPException(403, "Yalnız öz göndərdiyiniz mesajı redaktə edə bilərsiniz")

    content = body.content.strip()
    m.content = content
    m.edited_at = datetime.now(timezone.utc)
    # Körpü platform mesajını da yenilə
    if m.bridge_message_id:
        bres = await db.execute(select(Message).where(Message.id == m.bridge_message_id).limit(1))
        bridge = bres.scalars().first()
        if bridge:
            bridge.content = content
            bridge.edited_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(m)

    stu_res = await db.execute(select(RepetitorStudent).where(RepetitorStudent.id == m.student_id).limit(1))
    stu = stu_res.scalars().first()
    return _msg_out(m, stu.name if stu else "?")


@router.post("/messages/{student_id}/clear", status_code=204)
async def clear_conversation(
    student_id: str,
    current_user: User = Depends(require_active_repetitor),
    db: AsyncSession = Depends(get_db),
):
    """Söhbəti yalnız repetitorun ekranından təmizlə — mesajlar bazada qalır,
    qarşı tərəf görməyə davam edir. Kəsim nöqtəsi (cleared_at) saxlanılır."""
    stu_res = await db.execute(
        select(RepetitorStudent).where(
            and_(RepetitorStudent.id == student_id,
                 RepetitorStudent.teacher_id == current_user.id)
        ).limit(1)
    )
    if not stu_res.scalars().first():
        raise HTTPException(404, "Şagird tapılmadı")

    now = datetime.now(timezone.utc)
    clr_res = await db.execute(
        select(RepetitorChatClear).where(
            and_(RepetitorChatClear.teacher_id == current_user.id,
                 RepetitorChatClear.student_id == student_id)
        ).limit(1)
    )
    clr = clr_res.scalars().first()
    if clr:
        clr.cleared_at = now
    else:
        db.add(RepetitorChatClear(
            teacher_id=current_user.id, student_id=student_id, cleared_at=now,
        ))
    await db.commit()
