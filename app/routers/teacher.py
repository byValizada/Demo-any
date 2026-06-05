"""
Teacher Router
--------------
/teacher/* — müəllim dashboard-u üçün API endpoint-lər
"""

import json
import os
import re
import random
import string
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List
from app.database import get_db
from app.dependencies import require_role, require_not_demo_repetitor
from app.models.user import User
from app.models.student import Student
from app.models.class_model import Class
from app.models.exam import Exam, Question, ExamResult
from app.models.homework import Homework
from app.models.tenant import Tenant
from app.models.repetitor import RepetitorSubject
from app.models.notification import Notification
from app.services.notification_service import send_notification
from app.services.auth_service import hash_password

router = APIRouter(prefix="/teacher", tags=["Teacher"], dependencies=[Depends(require_not_demo_repetitor)])
require_teacher = require_role("teacher", "admin", "superadmin")


def _require_active(user):
    """Raises 403 with ACCOUNT_PENDING if teacher account is not yet activated."""
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="ACCOUNT_PENDING"
        )


# ── Schemas ────────────────────────────────────────────────────────────────

class ClassInfo(BaseModel):
    id: str
    name: str
    subject: str
    student_count: int


class StudentInfo(BaseModel):
    id: str
    name: str
    email: str
    class_name: Optional[str]
    xp: int
    streak: int
    level: int
    avg_score: float = 0.0
    exam_count: int = 0


class TeacherDashboard(BaseModel):
    teacher_name: str
    tenant_name: str
    student_count: int
    class_count: int
    exam_count: int
    classes: list[ClassInfo]
    recent_students: list[StudentInfo]


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=TeacherDashboard)
async def get_teacher_dashboard(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Müəllim dashboard stats-ı"""

    # Get classes for this teacher
    cls_result = await db.execute(
        select(Class).where(Class.teacher_id == current_user.id)
    )
    classes_db = cls_result.scalars().all()
    class_ids = [c.id for c in classes_db]

    # Count students per class
    class_infos = []
    for cls in classes_db:
        stu_count_result = await db.execute(
            select(func.count(Student.id)).where(Student.class_id == cls.id)
        )
        count = stu_count_result.scalar() or 0
        class_infos.append(ClassInfo(
            id=cls.id,
            name=cls.name,
            subject=cls.subject,
            student_count=count,
        ))

    # Total students — UNİKAL şagird (bir şagird bir neçə sinifdə ola bilər)
    total_students_result = await db.execute(
        select(func.count(func.distinct(Student.user_id)))
        .join(User, User.id == Student.user_id)
        .where(User.tenant_id == current_user.tenant_id)
    )
    total_students = total_students_result.scalar() or 0

    # Count exams
    exam_count_result = await db.execute(
        select(func.count(Exam.id)).where(Exam.teacher_id == current_user.id)
    )
    exam_count = exam_count_result.scalar() or 0

    # Recent students — user_id-yə görə dedup, sinifləri birləşdir
    stu_result = await db.execute(
        select(Student, User)
        .join(User, User.id == Student.user_id)
        .where(User.tenant_id == current_user.tenant_id)
        .order_by(User.name)
    )
    grouped: dict[str, dict] = {}
    for stu, user in stu_result.all():
        cls_match = next((c for c in classes_db if c.id == stu.class_id), None)
        if user.id not in grouped:
            grouped[user.id] = {"user": user, "classes": [], "xp": stu.xp, "streak": stu.streak, "level": stu.level}
        if cls_match and cls_match.name not in grouped[user.id]["classes"]:
            grouped[user.id]["classes"].append(cls_match.name)

    recent_students = [
        StudentInfo(
            id=d["user"].id,
            name=d["user"].name,
            email=d["user"].email,
            class_name=", ".join(d["classes"]) if d["classes"] else None,
            xp=d["xp"],
            streak=d["streak"],
            level=d["level"],
        )
        for d in list(grouped.values())[:5]
    ]

    # Get tenant name from user's tenant
    from app.models.tenant import Tenant
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id)
    )
    tenant = tenant_result.scalar_one_or_none()
    tenant_name = tenant.name if tenant else ""

    return TeacherDashboard(
        teacher_name=current_user.name,
        tenant_name=tenant_name,
        student_count=total_students,
        class_count=len(classes_db),
        exam_count=exam_count,
        classes=class_infos,
        recent_students=recent_students,
    )


class AtRiskStudent(BaseModel):
    student_name: str
    student_id: str
    subject: str
    last_percentage: float
    prev_avg: float
    trend: str          # "low" | "declining" | "critical"
    last_exam_title: str
    submitted_at: str


@router.get("/at-risk-students", response_model=list[AtRiskStudent])
async def get_at_risk_students(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Son imtahanlarda risk əlamətləri göstərən şagirdlər."""
    from app.models.exam import ExamResult, Exam
    from app.models.student import Student

    # Bu müəllimin imtahanlarına verilmiş son nəticələr
    rows = (await db.execute(
        select(ExamResult, Exam, Student, User)
        .join(Exam, Exam.id == ExamResult.exam_id)
        .join(Student, Student.id == ExamResult.student_id)
        .join(User, User.id == Student.user_id)
        .where(Exam.teacher_id == current_user.id)
        .order_by(ExamResult.submitted_at.desc())
    )).all()

    # Şagird başına son nəticələri qrupla
    from collections import defaultdict
    student_results: dict[str, list] = defaultdict(list)
    for er, ex, stu, u in rows:
        student_results[u.id].append({
            "er": er, "ex": ex, "stu": stu, "u": u,
        })

    risk_list: list[AtRiskStudent] = []
    seen = set()

    for uid, results in student_results.items():
        if uid in seen:
            continue
        # Son 3-ü al
        last3 = results[:3]
        last = last3[0]
        last_pct = last["er"].percentage

        prev_avg = (sum(r["er"].percentage for r in last3[1:]) / len(last3[1:])) if len(last3) > 1 else last_pct

        trend = None
        if last_pct < 40:
            trend = "critical"
        elif last_pct < 55 and prev_avg < 65:
            trend = "low"
        elif prev_avg - last_pct >= 25:
            trend = "declining"

        if trend:
            seen.add(uid)
            risk_list.append(AtRiskStudent(
                student_name=last["u"].name,
                student_id=uid,
                subject=last["ex"].subject,
                last_percentage=round(last_pct, 1),
                prev_avg=round(prev_avg, 1),
                trend=trend,
                last_exam_title=last["ex"].title,
                submitted_at=last["er"].submitted_at.strftime("%d.%m.%Y") if last["er"].submitted_at else "",
            ))

    # Ən kritikdən başlayaraq sırala
    order = {"critical": 0, "declining": 1, "low": 2}
    risk_list.sort(key=lambda r: order.get(r.trend, 3))
    return risk_list


@router.get("/classes", response_model=list[ClassInfo])
async def get_teacher_classes(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Müəllimin siniflərini qaytar"""
    cls_result = await db.execute(
        select(Class).where(
            Class.teacher_id == current_user.id,
            Class.tenant_id == current_user.tenant_id,
        )
    )
    classes_db = cls_result.scalars().all()

    result = []
    for cls in classes_db:
        count_result = await db.execute(
            select(func.count(Student.id)).where(Student.class_id == cls.id)
        )
        count = count_result.scalar() or 0
        result.append(ClassInfo(id=cls.id, name=cls.name, subject=cls.subject, student_count=count))

    return result


@router.get("/students", response_model=list[StudentInfo])
async def get_teacher_students(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Eyni tenant-dakı şagirdləri qaytar — user_id-yə görə dedup, bütün sinifləri birləşdir."""
    stu_result = await db.execute(
        select(Student, User, Class)
        .join(User, User.id == Student.user_id)
        .outerjoin(Class, Class.id == Student.class_id)
        .where(User.tenant_id == current_user.tenant_id)
        .order_by(User.name)
    )
    rows = stu_result.all()

    # user_id → aggreqat məlumat
    grouped: dict[str, dict] = {}
    student_ids_by_user: dict[str, list[str]] = {}

    for stu, user, cls in rows:
        if user.id not in grouped:
            grouped[user.id] = {
                "user": user,
                "classes": [],
                "xp": stu.xp,           # ilk qeydin xp-si (eyni şagird üçün)
                "streak": stu.streak,
                "level": stu.level,
            }
            student_ids_by_user[user.id] = []
        if cls and cls.name not in grouped[user.id]["classes"]:
            grouped[user.id]["classes"].append(cls.name)
        student_ids_by_user[user.id].append(stu.id)

    students = []
    for uid, data in grouped.items():
        user = data["user"]
        # Orta bal — bu şagirdin bütün Student qeydləri üzrə
        res_result = await db.execute(
            select(ExamResult.percentage)
            .join(Exam, Exam.id == ExamResult.exam_id)
            .where(
                ExamResult.student_id.in_(student_ids_by_user[uid]),
                Exam.teacher_id == current_user.id,
            )
        )
        percs = [r[0] for r in res_result.all()]
        avg = round(sum(percs) / len(percs), 1) if percs else 0.0

        students.append(StudentInfo(
            id=user.id,
            name=user.name,
            email=user.email,
            class_name=", ".join(data["classes"]) if data["classes"] else None,
            xp=data["xp"],
            streak=data["streak"],
            level=data["level"],
            avg_score=avg,
            exam_count=len(percs),
        ))

    return students


# ── E-poçt dəvəti (invite) ────────────────────────────────────────────────────

class InviteBody(BaseModel):
    emails: list[str]
    class_name: Optional[str] = None


class InviteResult(BaseModel):
    email: str
    name: str
    temp_password: str
    status: str  # "created" | "already_exists"


@router.post("/students/invite", response_model=list[InviteResult], status_code=201)
async def invite_students_by_email(
    body: InviteBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """E-poçt siyahısı üzrə şagird hesabları yarat."""
    import uuid as _uuid
    _require_active(current_user)

    # Sinif tapılır (istəyə bağlı)
    target_class = None
    if body.class_name:
        cls_res = await db.execute(
            select(Class).where(Class.teacher_id == current_user.id, Class.name == body.class_name)
        )
        target_class = cls_res.scalar_one_or_none()

    results = []
    for raw_email in body.emails:
        email = raw_email.strip().lower()
        if not email:
            continue

        # Mövcud hesabı yoxla
        existing = await db.execute(select(User).where(User.email == email))
        ex_user = existing.scalar_one_or_none()
        if ex_user:
            results.append(InviteResult(email=email, name=ex_user.name, temp_password="(mövcud hesab)", status="already_exists"))
            continue

        # Ad: e-poçtun @ öncəsi hissəsi
        name_part = email.split("@")[0].replace(".", " ").title()
        temp_pw = f"Sagird{_uuid.uuid4().hex[:4].upper()}"
        new_user = User(
            tenant_id=current_user.tenant_id,
            name=name_part,
            email=email,
            hashed_password=hash_password(temp_pw),
            role="student",
            is_active=True,
        )
        db.add(new_user)
        await db.flush()

        if target_class:
            stu = Student(user_id=new_user.id, class_id=target_class.id, tenant_id=current_user.tenant_id)
            db.add(stu)

        results.append(InviteResult(email=email, name=name_part, temp_password=temp_pw, status="created"))

    await db.commit()
    return results


# ── Toplu CSV import ──────────────────────────────────────────────────────────

class BulkRow(BaseModel):
    name: str
    email: Optional[str] = None
    class_name: Optional[str] = None


class BulkImportBody(BaseModel):
    rows: list[BulkRow]


class BulkImportResult(BaseModel):
    created: int
    skipped: int
    students: list[dict]


@router.post("/students/bulk", response_model=BulkImportResult, status_code=201)
async def bulk_import_students(
    body: BulkImportBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """CSV/Excel satırları üzrə kütləvi şagird əlavəsi."""
    import uuid as _uuid
    _require_active(current_user)

    created = 0
    skipped = 0
    students_out = []

    # Teacher's class name → id map
    cls_res = await db.execute(select(Class).where(Class.teacher_id == current_user.id))
    classes = {c.name: c for c in cls_res.scalars().all()}

    for row in body.rows:
        if not row.name.strip():
            skipped += 1
            continue

        email = (row.email or "").strip().lower() or f"student_{_uuid.uuid4().hex[:8]}@temp.local"
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        temp_pw = f"Sagird{_uuid.uuid4().hex[:4].upper()}"
        new_user = User(
            tenant_id=current_user.tenant_id,
            name=row.name.strip(),
            email=email,
            hashed_password=hash_password(temp_pw),
            role="student",
            is_active=True,
        )
        db.add(new_user)
        await db.flush()

        cls_obj = classes.get(row.class_name or "")
        if cls_obj:
            stu = Student(user_id=new_user.id, class_id=cls_obj.id, tenant_id=current_user.tenant_id)
            db.add(stu)

        students_out.append({"name": row.name.strip(), "email": email if row.email else "", "temp_password": temp_pw})
        created += 1

    await db.commit()
    return BulkImportResult(created=created, skipped=skipped, students=students_out)


# ── Sinif qoşulma kodu ────────────────────────────────────────────────────────

@router.get("/classes/{class_id}/join-code")
async def get_join_code(
    class_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Sinifin unikal qoşulma kodunu qaytarır."""
    _require_active(current_user)
    cls_res = await db.execute(select(Class).where(Class.id == class_id, Class.teacher_id == current_user.id))
    cls = cls_res.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Sinif tapılmadı")

    # Deterministic: sinif adı (hərflər) + ID-nin ilk 6 simvolu
    safe_name = re.sub(r"[^A-Z0-9]", "", cls.name.upper())[:4]
    code_suffix = cls.id.replace("-", "")[:6].upper()
    join_code = f"{safe_name}-{code_suffix}"
    return {"class_id": class_id, "class_name": cls.name, "join_code": join_code}


class ClassCreate(BaseModel):
    name: str
    subject: str


@router.post("/classes", response_model=ClassInfo, status_code=201)
async def create_class(
    body: ClassCreate,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    if current_user.student_limit > 0:
        existing_count_result = await db.execute(
            select(func.count(Student.id))
            .join(Class, Class.id == Student.class_id)
            .where(Class.teacher_id == current_user.id)
        )
        existing_count = existing_count_result.scalar() or 0
        if existing_count >= current_user.student_limit:
            raise HTTPException(
                status_code=400,
                detail=f"STUDENT_LIMIT_REACHED:{current_user.student_limit}"
            )

    # ── Fənn limiti: müəllim maksimum 2 fərqli fənn tədris edə bilər ──
    MAX_SUBJECTS = 2
    new_subject = (body.subject or "").strip()
    if new_subject:
        subj_res = await db.execute(
            select(Class.subject).where(Class.teacher_id == current_user.id)
        )
        existing_subjects = {
            (s or "").strip().lower()
            for (s,) in subj_res.all()
            if (s or "").strip()
        }
        # Yeni fənn mövcud deyilsə və artıq 2 fərqli fənn varsa → rədd et
        if new_subject.lower() not in existing_subjects and len(existing_subjects) >= MAX_SUBJECTS:
            raise HTTPException(
                status_code=400,
                detail=f"SUBJECT_LIMIT_REACHED:{MAX_SUBJECTS}",
            )

    new_cls = Class(
        tenant_id=current_user.tenant_id,
        teacher_id=current_user.id,
        name=body.name,
        subject=body.subject,
    )
    db.add(new_cls)
    await db.commit()
    await db.refresh(new_cls)
    return ClassInfo(id=new_cls.id, name=new_cls.name, subject=new_cls.subject, student_count=0)


class ManualStudentCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    class_name: Optional[str] = None


class ManualStudentOut(BaseModel):
    id: str
    name: str
    email: str
    temp_password: str
    class_name: Optional[str] = None


def _gen_temp_password() -> str:
    """Sagird + 4 rəqəm"""
    digits = ''.join(random.choices(string.digits, k=4))
    return f"Sagird{digits}"


@router.post("/students/manual", response_model=ManualStudentOut, status_code=201)
async def add_student_manually(
    body: ManualStudentCreate,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Ad Soyad mütləqdir")

    # E-poçt: verilmişsə istifadə et, yoxsa unikal placeholder yarat
    import uuid as _uuid
    email = (body.email or "").strip().lower() or f"noemail_{_uuid.uuid4().hex[:8]}@temp.local"

    # E-poçt artıq mövcuddurmu?
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Bu e-poçt artıq mövcuddur")

    temp_pw = _gen_temp_password()

    new_user = User(
        tenant_id=current_user.tenant_id,
        name=body.name.strip(),
        email=email,
        hashed_password=hash_password(temp_pw),
        role="student",
        is_active=True,
    )
    db.add(new_user)
    await db.flush()

    # Sinif tapılması
    class_name = None
    class_id = None
    if body.class_name:
        cls_res = await db.execute(
            select(Class).where(
                Class.name == body.class_name,
                Class.tenant_id == current_user.tenant_id,
            )
        )
        cls = cls_res.scalar_one_or_none()
        if cls:
            class_id = cls.id
            class_name = cls.name

    new_student = Student(
        user_id=new_user.id,
        class_id=class_id,
    )
    db.add(new_student)
    await db.commit()

    return ManualStudentOut(
        id=new_user.id,
        name=new_user.name,
        email=email if body.email else "",
        temp_password=temp_pw,
        class_name=class_name,
    )


class AddParentBody(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None


class AddParentOut(BaseModel):
    parent_id: str
    name: str
    email: str
    temp_password: str


@router.post("/students/{user_id}/add-parent", response_model=AddParentOut, status_code=201)
async def add_parent_to_student(
    user_id: str,
    body: AddParentBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdə valideyn hesabı yarat və əlaqələndir."""
    import uuid as _uuid

    # Şagirdi tap
    stu_res = await db.execute(
        select(Student).where(Student.user_id == user_id)
    )
    stu = stu_res.scalar_one_or_none()
    if not stu:
        raise HTTPException(status_code=404, detail="Şagird tapılmadı")

    # E-poçt varsa mövcud user-i yoxla
    email = (body.email or "").strip().lower() or f"parent_{_uuid.uuid4().hex[:8]}@temp.local"
    existing = await db.execute(select(User).where(User.email == email))
    existing_user = existing.scalar_one_or_none()

    if existing_user:
        # Mövcud hesabı valideyn kimi əlaqələndir
        stu.parent_id = existing_user.id
        await db.commit()
        return AddParentOut(
            parent_id=existing_user.id,
            name=existing_user.name,
            email=existing_user.email,
            temp_password="(mövcud hesab)",
        )

    temp_pw = f"Valideyn{_uuid.uuid4().hex[:4].upper()}"
    parent_user = User(
        tenant_id=current_user.tenant_id,
        name=body.name.strip(),
        email=email,
        hashed_password=hash_password(temp_pw),
        role="parent",
        is_active=True,
    )
    db.add(parent_user)
    await db.flush()

    stu.parent_id = parent_user.id
    await db.commit()

    return AddParentOut(
        parent_id=parent_user.id,
        name=parent_user.name,
        email=email if body.email else "",
        temp_password=temp_pw,
    )


class LinkParentBody(BaseModel):
    parent_id: str


@router.get("/parents", response_model=list[dict])
async def list_parents(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Tenant-dakı bütün valideynləri qaytarır (mövcud hesabı əlaqələndirmək üçün)."""
    _require_active(current_user)
    res = await db.execute(
        select(User).where(
            User.tenant_id == current_user.tenant_id,
            User.role == "parent",
            User.is_active == True,
        )
    )
    parents = res.scalars().all()

    # Hər valideynin uşaqlarının adlarını da əlavə edirik
    out = []
    for p in parents:
        stu_res = await db.execute(
            select(User.name)
            .join(Student, Student.user_id == User.id)
            .where(Student.parent_id == p.id)
        )
        children = [r[0] for r in stu_res.all()]
        out.append({
            "id": p.id,
            "name": p.name,
            "email": p.email,
            "children": children,
        })
    return out


@router.post("/students/{user_id}/link-parent", response_model=AddParentOut)
async def link_existing_parent(
    user_id: str,
    body: LinkParentBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Mövcud valideyn hesabını şagirdə əlaqələndir."""
    _require_active(current_user)

    stu_res = await db.execute(select(Student).where(Student.user_id == user_id))
    stu = stu_res.scalar_one_or_none()
    if not stu:
        raise HTTPException(status_code=404, detail="Şagird tapılmadı")

    p_res = await db.execute(select(User).where(User.id == body.parent_id, User.role == "parent"))
    parent = p_res.scalar_one_or_none()
    if not parent:
        raise HTTPException(status_code=404, detail="Valideyn tapılmadı")

    stu.parent_id = parent.id
    await db.commit()

    return AddParentOut(
        parent_id=parent.id,
        name=parent.name,
        email=parent.email,
        temp_password="(mövcud hesab)",
    )


class NotifyParentBody(BaseModel):
    message: str


@router.post("/students/{user_id}/notify-parent", status_code=200)
async def notify_parent(
    user_id: str,
    body: NotifyParentBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdin valideyninə bildiriş göndər."""
    stu_res = await db.execute(
        select(Student).where(Student.user_id == user_id)
    )
    stu = stu_res.scalar_one_or_none()
    if not stu:
        raise HTTPException(status_code=404, detail="Şagird tapılmadı")
    if not stu.parent_id:
        raise HTTPException(status_code=404, detail="Bu şagirdin valideyni qeydiyyatda deyil")
    await send_notification(
        db, stu.parent_id,
        f"Müəllim bildirişi — {current_user.name}",
        body.message.strip(),
        "info",
    )
    return {"ok": True}


@router.delete("/students/{user_id}", status_code=204)
async def delete_student(
    user_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdi sil: Student profilini və User hesabını bazadan çıxar."""
    result = await db.execute(
        select(Student).where(Student.user_id == user_id)
    )
    stu = result.scalar_one_or_none()
    if stu:
        await db.delete(stu)

    user_result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Şagird tapılmadı")
    await db.delete(user)
    await db.commit()


class ClassUpdate(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None


@router.patch("/classes/{class_id}", response_model=ClassInfo)
async def update_class(
    class_id: str,
    body: ClassUpdate,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == current_user.id)
    )
    cls = result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Sinif tapılmadı")
    if body.name is not None:
        cls.name = body.name.strip()
    if body.subject is not None:
        new_subject = body.subject.strip()
        # Fənn limiti: digər siniflərin fənləri + bu yeni fənn ≤ 2 fərqli fənn
        if new_subject:
            other_res = await db.execute(
                select(Class.subject).where(
                    Class.teacher_id == current_user.id, Class.id != class_id
                )
            )
            other_subjects = {
                (s or "").strip().lower()
                for (s,) in other_res.all()
                if (s or "").strip()
            }
            if new_subject.lower() not in other_subjects and len(other_subjects) >= 2:
                raise HTTPException(status_code=400, detail="SUBJECT_LIMIT_REACHED:2")
        cls.subject = new_subject
    await db.commit()
    await db.refresh(cls)
    count_result = await db.execute(
        select(func.count(Student.id)).where(Student.class_id == cls.id)
    )
    count = count_result.scalar() or 0
    return ClassInfo(id=cls.id, name=cls.name, subject=cls.subject, student_count=count)


class ClassNotifyBody(BaseModel):
    title: str
    message: Optional[str] = None


class EmailCheckResult(BaseModel):
    exists: bool
    user_id: Optional[str] = None
    name: Optional[str] = None
    already_in_class: bool = False


@router.get("/classes/{class_id}/check-email")
async def check_email_for_class(
    class_id: str,
    email: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> EmailCheckResult:
    """E-poçtla istifadəçi yoxla: var/yox, bu sinifdədir/deyil"""
    cls_res = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == current_user.id)
    )
    if not cls_res.scalar_one_or_none():
        raise HTTPException(404, "Sinif tapılmadı")

    user_res = await db.execute(
        select(User).where(User.email == email.strip().lower())
    )
    user = user_res.scalar_one_or_none()
    if not user:
        return EmailCheckResult(exists=False)

    # Bu sinifdədirmi?
    stu_res = await db.execute(
        select(Student).where(Student.user_id == user.id, Student.class_id == class_id)
    )
    already = stu_res.scalar_one_or_none() is not None
    return EmailCheckResult(exists=True, user_id=user.id, name=user.name, already_in_class=already)


class AddByEmailBody(BaseModel):
    email: str
    name: Optional[str] = None   # yalnız yeni istifadəçi üçün


@router.post("/classes/{class_id}/add-by-email", status_code=201)
async def add_student_by_email(
    class_id: str,
    body: AddByEmailBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """E-poçtla şagird əlavə et: mövcuddursa əlavə et, yoxdursa yarat"""
    cls_res = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == current_user.id)
    )
    cls = cls_res.scalar_one_or_none()
    if not cls:
        raise HTTPException(404, "Sinif tapılmadı")

    email = body.email.strip().lower()
    user_res = await db.execute(select(User).where(User.email == email))
    user = user_res.scalar_one_or_none()

    if user:
        # Mövcud istifadəçi — bu sinifdə artıq varsa rədd et, yoxdursa YENİ qeyd yarat
        in_class = await db.execute(
            select(Student).where(Student.user_id == user.id, Student.class_id == class_id)
        )
        if in_class.scalar_one_or_none():
            raise HTTPException(400, "Şagird artıq bu sinifdədir")
        # Başqa sinifdə varsa parent_id-ni miras al
        other = await db.execute(
            select(Student).where(Student.user_id == user.id).limit(1)
        )
        other_stu = other.scalar_one_or_none()
        parent_id = other_stu.parent_id if other_stu else None
        stu = Student(user_id=user.id, class_id=class_id, parent_id=parent_id)
        db.add(stu)
        await db.commit()
        return {"created": False, "user_id": user.id, "name": user.name}
    else:
        # Yeni istifadəçi yarat
        if not body.name or not body.name.strip():
            raise HTTPException(400, "Yeni şagird üçün ad mütləqdir")
        temp_pw = _gen_temp_password()
        new_user = User(
            tenant_id=current_user.tenant_id,
            name=body.name.strip(),
            email=email,
            hashed_password=hash_password(temp_pw),
            role="student",
            is_active=True,
        )
        db.add(new_user)
        await db.flush()
        stu = Student(user_id=new_user.id, class_id=class_id)
        db.add(stu)
        await db.commit()
        return {"created": True, "user_id": new_user.id, "name": new_user.name, "temp_password": temp_pw}


class AvailableStudent(BaseModel):
    user_id: str
    name: str
    email: str
    current_class: Optional[str] = None   # hal-hazırda hansı sinifdədir (varsa)


@router.get("/classes/{class_id}/available-students", response_model=list[AvailableStudent])
async def get_available_students(
    class_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Bu sinifdə olmayan, tenant-dəki bütün şagirdləri qaytar (dedup edilmiş)."""
    cls_res = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == current_user.id)
    )
    if not cls_res.scalar_one_or_none():
        raise HTTPException(404, "Sinif tapılmadı")

    # Bu sinifdəki user_id-ləri
    in_class_res = await db.execute(
        select(Student.user_id).where(Student.class_id == class_id)
    )
    in_class_ids = {row[0] for row in in_class_res.all()}

    # Eyni tenant-dəki bütün şagirdlər + onların aid olduğu siniflər
    all_stu_res = await db.execute(
        select(User, Student, Class)
        .join(Student, Student.user_id == User.id)
        .outerjoin(Class, Class.id == Student.class_id)
        .where(User.tenant_id == current_user.tenant_id)
    )

    # user_id → ən son sinif adı (dedup)
    seen: dict[str, dict] = {}
    for user, _, cls2 in all_stu_res.all():
        if user.id in in_class_ids:
            continue
        if user.id not in seen:
            seen[user.id] = {
                "user_id": user.id,
                "name": user.name,
                "email": user.email if not user.email.endswith("@temp.local") else "",
                "classes": [],
            }
        if cls2 and cls2.name not in seen[user.id]["classes"]:
            seen[user.id]["classes"].append(cls2.name)

    return [
        AvailableStudent(
            user_id=d["user_id"],
            name=d["name"],
            email=d["email"],
            current_class=", ".join(d["classes"]) if d["classes"] else None,
        )
        for d in seen.values()
    ]


class AddStudentToClassBody(BaseModel):
    user_id: str


@router.post("/classes/{class_id}/students", status_code=201)
async def add_student_to_class(
    class_id: str,
    body: AddStudentToClassBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Mövcud şagirdi bu sinifə əlavə et — bir şagird müxtəlif siniflərdə iştirak edə bilər."""
    cls_res = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == current_user.id)
    )
    cls = cls_res.scalar_one_or_none()
    if not cls:
        raise HTTPException(404, "Sinif tapılmadı")

    # Bu şagird artıq HƏMİN sinfin üzvüdürmü?
    existing = await db.execute(
        select(Student).where(
            Student.user_id == body.user_id,
            Student.class_id == class_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Şagird artıq bu sinifdədir")

    # Başqa siniflərdəki Student qeydlərindən parent_id-ni miras al
    other = await db.execute(
        select(Student).where(Student.user_id == body.user_id).limit(1)
    )
    other_stu = other.scalar_one_or_none()
    parent_id = other_stu.parent_id if other_stu else None

    # YENİ Student qeydi yarat — eyni şagird, fərqli sinif
    stu = Student(user_id=body.user_id, class_id=class_id, parent_id=parent_id)
    db.add(stu)
    await db.commit()
    return {"ok": True}


@router.delete("/classes/{class_id}/students/{user_id}", status_code=204)
async def remove_student_from_class(
    class_id: str,
    user_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdi YALNIZ bu sinifdən çıxar (digər siniflərdə qalır, hesab silinmir)."""
    cls_res = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == current_user.id)
    )
    if not cls_res.scalar_one_or_none():
        raise HTTPException(404, "Sinif tapılmadı")

    res = await db.execute(
        select(Student).where(Student.user_id == user_id, Student.class_id == class_id)
    )
    stu = res.scalar_one_or_none()
    if not stu:
        raise HTTPException(404, "Bu sinifdə şagird tapılmadı")

    await db.delete(stu)
    await db.commit()


@router.post("/classes/{class_id}/notify")
async def notify_class_students(
    class_id: str,
    body: ClassNotifyBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Sinifin bütün şagirdlərinə in-app bildiriş göndər"""
    # Sinif müəlliminə aiddir?
    cls_res = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == current_user.id)
    )
    cls = cls_res.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Sinif tapılmadı")

    # Sinifdəki şagirdlərin user_id-lərini al
    stu_res = await db.execute(
        select(Student.user_id).where(Student.class_id == class_id)
    )
    user_ids = [row[0] for row in stu_res.all()]

    if not user_ids:
        return {"sent": 0, "message": "Sinifdə şagird yoxdur"}

    # Hər şagird üçün notification yarat
    for uid in user_ids:
        notif = Notification(
            user_id=uid,
            title=body.title,
            description=body.message,
            type="info",
        )
        db.add(notif)
    await db.commit()

    return {"sent": len(user_ids)}


@router.delete("/classes/{class_id}", status_code=204)
async def delete_class(
    class_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    import sqlalchemy as sa
    from app.models.student import Student
    from app.models.exam import Exam, Question, ExamResult
    from app.models.homework import Homework, HomeworkSubmission

    result = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == current_user.id)
    )
    cls = result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Sinif tapılmadı")

    # 1. Şagirdlərin class_id-ni NULL et (onları silmə)
    await db.execute(
        sa.update(Student).where(Student.class_id == class_id).values(class_id=None)
    )

    # 2. İmtahan nəticələrini, sualları, imtahanları sil
    exams_r = await db.execute(select(Exam).where(Exam.class_id == class_id))
    for exam in exams_r.scalars().all():
        await db.execute(sa.delete(ExamResult).where(ExamResult.exam_id == exam.id))
        await db.execute(sa.delete(Question).where(Question.exam_id == exam.id))
        await db.delete(exam)

    # 3. Tapşırıqları sil
    homeworks_r = await db.execute(select(Homework).where(Homework.class_id == class_id))
    for hw in homeworks_r.scalars().all():
        await db.execute(sa.delete(HomeworkSubmission).where(HomeworkSubmission.homework_id == hw.id))
        await db.delete(hw)

    await db.flush()
    await db.delete(cls)
    await db.commit()


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None    # single (legacy)
    subjects: Optional[list[str]] = None  # multi-subject array


class ProfileOut(BaseModel):
    id: str
    name: str
    email: str
    role: str
    avatar_url: Optional[str] = None
    school: Optional[str] = None      # Tenant.name
    subjects: list[str] = []          # Müəllimin bütün fənləri


def _parse_subjects(user: User) -> list[str]:
    """subjects_json sütunundan fənlər siyahısını oxu."""
    if user.subjects_json:
        try:
            parsed = json.loads(user.subjects_json)
            if isinstance(parsed, list):
                return [s for s in parsed if s and isinstance(s, str)]
        except Exception:
            pass
    return []


async def _build_profile_out(user: User, db: AsyncSession) -> ProfileOut:
    """Profil məlumatlarını tenant + subjects_json-dan yığır."""
    # Məktəb adı
    tenant_res = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = tenant_res.scalar_one_or_none()
    school = tenant.name if tenant else None

    # Fənlər: əvvəlcə subjects_json-dan oxu
    subjects = _parse_subjects(user)
    if not subjects:
        # Repetitor: repetitor_subjects cədvəlindən götür
        rep_res = await db.execute(
            select(RepetitorSubject.name)
            .where(RepetitorSubject.teacher_id == user.id)
            .order_by(RepetitorSubject.name)
        )
        rep_subjects = [r[0] for r in rep_res.all() if r[0]]
        if rep_subjects:
            subjects = rep_subjects
            # subjects_json-a da yaz ki növbəti dəfə sinxron olsun
            user.subjects_json = json.dumps(subjects, ensure_ascii=False)
            await db.commit()
        else:
            # Teacher: siniflərdən götür
            cls_res = await db.execute(
                select(Class.subject).where(Class.teacher_id == user.id)
            )
            subjects = list(dict.fromkeys(r[0] for r in cls_res.all() if r[0]))

    return ProfileOut(
        id=user.id, name=user.name, email=user.email,
        role=user.role, avatar_url=user.avatar_url,
        school=school, subjects=subjects,
    )


@router.patch("/profile", response_model=ProfileOut)
async def update_teacher_profile(
    body: ProfileUpdate,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    if body.name:
        current_user.name = body.name

    # Multi-subject array gəlibsə subjects_json-a yaz (maks. 2 fənn)
    if body.subjects is not None:
        cleaned = list(dict.fromkeys(s.strip() for s in body.subjects if s.strip()))
        if len(cleaned) > 2:
            raise HTTPException(status_code=400, detail="SUBJECT_LIMIT_REACHED:2")
        current_user.subjects_json = json.dumps(cleaned, ensure_ascii=False)
    elif body.subject:
        # Legacy: single subject — mövcud siyahıya əlavə et (dublikat yoxla)
        existing = _parse_subjects(current_user)
        s = body.subject.strip()
        if s and s not in existing:
            existing.append(s)
        if len(existing) > 2:
            raise HTTPException(status_code=400, detail="SUBJECT_LIMIT_REACHED:2")
        current_user.subjects_json = json.dumps(existing, ensure_ascii=False)

    # Repetitor üçün: subjects_json dəyişibsə repetitor_subjects cədvəlini də sinxronlaşdır
    if body.subjects is not None:
        tenant_res = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
        tenant = tenant_res.scalar_one_or_none()
        if tenant and tenant.type == 'repetitor':
            cleaned = list(dict.fromkeys(s.strip() for s in body.subjects if s.strip()))
            # Mövcud repetitor_subjects-ı sil, yenilərini əlavə et
            old_subs = await db.execute(
                select(RepetitorSubject).where(RepetitorSubject.teacher_id == current_user.id)
            )
            for old in old_subs.scalars().all():
                await db.delete(old)
            for name in cleaned:
                db.add(RepetitorSubject(teacher_id=current_user.id, name=name))

    await db.commit()
    await db.refresh(current_user)
    return await _build_profile_out(current_user, db)


@router.get("/profile", response_model=ProfileOut)
async def get_teacher_profile(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    return await _build_profile_out(current_user, db)


@router.post("/avatar", response_model=ProfileOut)
async def upload_teacher_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Store avatar as base64 data-URL so no static server needed."""
    import base64
    _require_active(current_user)
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Yalnız şəkil faylı qəbul edilir")
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:  # 2 MB limit
        raise HTTPException(status_code=400, detail="Şəkil 2 MB-dan böyük ola bilməz")
    b64 = base64.b64encode(data).decode()
    current_user.avatar_url = f"data:{file.content_type};base64,{b64}"
    await db.commit()
    await db.refresh(current_user)
    return ProfileOut(id=current_user.id, name=current_user.name, email=current_user.email,
                      role=current_user.role, avatar_url=current_user.avatar_url)


@router.delete("/avatar")
async def delete_teacher_avatar(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Avatarı sil."""
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    if user:
        user.avatar_url = None
        await db.commit()
    return {"ok": True}


class ActivityItem(BaseModel):
    type: str          # "exam_submit" | "exam_created" | "homework_created"
    text: str
    sub: str
    time_ago: str      # rough human time: "10 dəq", "1 saat", "2 gün" etc.


@router.get("/recent-activity", response_model=list[ActivityItem])
async def get_recent_activity(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)

    def time_ago(dt):
        if dt is None:
            return "?"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = now - dt
        mins = int(diff.total_seconds() / 60)
        if mins < 60:
            return f"{mins} dəq"
        elif mins < 1440:
            return f"{mins // 60} saat"
        else:
            return f"{mins // 1440} gün"

    activities = []

    # Recent exam submissions
    cls_res = await db.execute(select(Class.id).where(Class.teacher_id == current_user.id))
    class_ids = [r[0] for r in cls_res.all()]

    if class_ids:
        stu_ids_res = await db.execute(
            select(Student.id).where(Student.class_id.in_(class_ids))
        )
        stu_ids = [r[0] for r in stu_ids_res.all()]

        if stu_ids:
            results_res = await db.execute(
                select(ExamResult, Exam, Student, User)
                .join(Exam, Exam.id == ExamResult.exam_id)
                .join(Student, Student.id == ExamResult.student_id)
                .join(User, User.id == Student.user_id)
                .where(ExamResult.student_id.in_(stu_ids), Exam.teacher_id == current_user.id)
                .order_by(ExamResult.submitted_at.desc())
                .limit(5)
            )
            for r, e, _s, u in results_res.all():
                activities.append(ActivityItem(
                    type="exam_submit",
                    text=f"{u.name} imtahanı bitirdi",
                    sub=f"{round(r.percentage)}/100 · {e.subject}",
                    time_ago=time_ago(r.submitted_at),
                ))

        # Recent exams created
        exams_res = await db.execute(
            select(Exam, Class)
            .join(Class, Class.id == Exam.class_id)
            .where(Exam.teacher_id == current_user.id)
            .order_by(Exam.created_at.desc())
            .limit(3)
        )
        for e, c in exams_res.all():
            activities.append(ActivityItem(
                type="exam_created",
                text=f"{e.title} yaradıldı",
                sub=f"{c.name} sinfi",
                time_ago=time_ago(e.created_at),
            ))

        # Recent homework created
        hw_res = await db.execute(
            select(Homework, Class)
            .join(Class, Class.id == Homework.class_id)
            .where(Homework.class_id.in_(class_ids))
            .order_by(Homework.created_at.desc())
            .limit(3)
        )
        for hw, c in hw_res.all():
            activities.append(ActivityItem(
                type="homework_created",
                text=f"{hw.title} tapşırığı verildi",
                sub=f"{c.name} sinfi",
                time_ago=time_ago(hw.created_at),
            ))

    # Sort by recency (they're already somewhat ordered; just trim to 8)
    return activities[:8]


class HomeworkOut(BaseModel):
    id: str
    title: str
    description: Optional[str]
    deadline: str
    is_active: bool
    class_id: str
    class_name: str
    created_at: str
    attachments: list[str] = []   # fayl URL-ləri siyahısı


class HomeworkCreate(BaseModel):
    class_id: str
    title: str
    description: Optional[str] = None
    deadline: str


class HomeworkPatch(BaseModel):
    is_active: Optional[bool] = None
    title: Optional[str] = None
    description: Optional[str] = None


@router.get("/homework", response_model=list[HomeworkOut])
async def get_teacher_homework(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    cls_result = await db.execute(
        select(Class.id).where(Class.teacher_id == current_user.id)
    )
    class_ids = [row[0] for row in cls_result.all()]
    if not class_ids:
        return []

    hw_result = await db.execute(
        select(Homework, Class)
        .join(Class, Class.id == Homework.class_id)
        .where(Homework.class_id.in_(class_ids))
        .order_by(Homework.created_at.desc())
    )
    rows = hw_result.all()
    result = []
    for hw, cls in rows:
        try:
            attachments = json.loads(hw.attachments or "[]")
        except Exception:
            attachments = []
        result.append(HomeworkOut(
            id=hw.id,
            title=hw.title,
            description=hw.description,
            deadline=hw.deadline.isoformat() if hw.deadline else "",
            is_active=hw.is_active,
            class_id=hw.class_id,
            class_name=cls.name,
            created_at=hw.created_at.isoformat() if hw.created_at else "",
            attachments=attachments,
        ))
    return result


@router.post("/homework", response_model=HomeworkOut, status_code=201)
async def create_homework(
    body: HomeworkCreate,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    from datetime import datetime
    from fastapi import HTTPException
    cls_result = await db.execute(
        select(Class).where(Class.id == body.class_id, Class.teacher_id == current_user.id)
    )
    cls = cls_result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=403, detail="Bu sinif sizin deyil")

    deadline_dt = datetime.fromisoformat(body.deadline)
    hw = Homework(
        class_id=body.class_id,
        teacher_id=current_user.id,
        title=body.title,
        description=body.description,
        deadline=deadline_dt,
    )
    db.add(hw)
    await db.flush()

    # Notify all students in the class
    stu_result = await db.execute(
        select(Student).where(Student.class_id == body.class_id)
    )
    students = stu_result.scalars().all()
    deadline_str = deadline_dt.strftime("%d.%m.%Y") if deadline_dt else "—"
    for stu in students:
        await send_notification(
            db, stu.user_id,
            "Yeni tapşırıq",
            f'"{hw.title}" tapşırığı əlavə edildi. Son tarix: {deadline_str}',
            "info",
        )

    await db.commit()
    await db.refresh(hw)
    return HomeworkOut(
        id=hw.id, title=hw.title, description=hw.description,
        deadline=hw.deadline.isoformat(), is_active=hw.is_active,
        class_id=hw.class_id, class_name=cls.name,
        created_at=hw.created_at.isoformat() if hw.created_at else "",
        attachments=[],
    )


@router.post("/homework/{hw_id}/upload")
async def upload_homework_file(
    hw_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Tapşırığa fayl/şəkil yüklə, URL-i attachments siyahısına əlavə et."""
    import shutil
    from pathlib import Path

    hw_result = await db.execute(
        select(Homework).where(Homework.id == hw_id, Homework.teacher_id == current_user.id)
    )
    hw = hw_result.scalar_one_or_none()
    if not hw:
        raise HTTPException(status_code=404, detail="Tapşırıq tapılmadı")

    # Saxla: uploads/homework/<hw_id>_<original_name>
    upload_dir = Path("uploads") / "homework"
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = file.filename.replace(" ", "_") if file.filename else "file"
    import uuid as _uuid
    unique_name = f"{_uuid.uuid4().hex[:8]}_{safe_name}"
    dest = upload_dir / unique_name

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    url = f"/uploads/homework/{unique_name}"

    # attachments siyahısını yenilə
    try:
        attachments: list = json.loads(hw.attachments or "[]")
    except Exception:
        attachments = []
    attachments.append(url)
    hw.attachments = json.dumps(attachments)

    await db.commit()
    return {"url": url, "attachments": attachments}


@router.patch("/homework/{hw_id}", response_model=HomeworkOut)
async def patch_homework(
    hw_id: str,
    body: HomeworkPatch,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    from fastapi import HTTPException
    hw_result = await db.execute(
        select(Homework).where(Homework.id == hw_id, Homework.teacher_id == current_user.id)
    )
    hw = hw_result.scalar_one_or_none()
    if not hw:
        raise HTTPException(status_code=404, detail="Tapşırıq tapılmadı")
    if body.is_active is not None:
        hw.is_active = body.is_active
    if body.title is not None:
        hw.title = body.title
    if body.description is not None:
        hw.description = body.description
    await db.commit()
    await db.refresh(hw)
    cls_result = await db.execute(select(Class).where(Class.id == hw.class_id))
    cls = cls_result.scalar_one_or_none()
    try:
        hw_attachments = json.loads(hw.attachments or "[]")
    except Exception:
        hw_attachments = []
    return HomeworkOut(
        id=hw.id, title=hw.title, description=hw.description,
        deadline=hw.deadline.isoformat(), is_active=hw.is_active,
        class_id=hw.class_id, class_name=cls.name if cls else "",
        created_at=hw.created_at.isoformat() if hw.created_at else "",
        attachments=hw_attachments,
    )


class HomeworkSubmissionOut(BaseModel):
    student_name: str
    content: str
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    submitted_at: str


@router.get("/homework/{homework_id}/submissions", response_model=list[HomeworkSubmissionOut])
async def get_homework_submissions(
    homework_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    from app.models.homework import Homework, HomeworkSubmission

    # Verify teacher owns this homework
    hw_result = await db.execute(
        select(Homework).where(Homework.id == homework_id, Homework.teacher_id == current_user.id)
    )
    hw = hw_result.scalar_one_or_none()
    if not hw:
        raise HTTPException(status_code=404, detail="Tapşırıq tapılmadı")

    subs_result = await db.execute(
        select(HomeworkSubmission, Student, User)
        .join(Student, Student.id == HomeworkSubmission.student_id)
        .join(User, User.id == Student.user_id)
        .where(HomeworkSubmission.homework_id == homework_id)
        .order_by(HomeworkSubmission.submitted_at.desc())
    )
    rows = subs_result.all()

    return [
        HomeworkSubmissionOut(
            student_name=u.name,
            content=sub.answer or "",
            file_url=sub.file_url,
            file_name=sub.file_name,
            submitted_at=sub.submitted_at.strftime("%d.%m.%Y %H:%M") if sub.submitted_at else "",
        )
        for sub, _s, u in rows
    ]


@router.delete("/homework/{hw_id}", status_code=204)
async def delete_homework(
    hw_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    from fastapi import HTTPException
    hw_result = await db.execute(
        select(Homework).where(Homework.id == hw_id, Homework.teacher_id == current_user.id)
    )
    hw = hw_result.scalar_one_or_none()
    if not hw:
        raise HTTPException(status_code=404, detail="Tapşırıq tapılmadı")
    await db.delete(hw)
    await db.commit()


# ═══════════════════════════════════════════════════════════════════════════
# EXAM SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

class ExamCreate(BaseModel):
    class_id: str
    title: str
    subject: str
    duration_minutes: int = 60
    scheduled_at: Optional[str] = None  # ISO 8601 datetime string


class QuestionCreate(BaseModel):
    text: str
    options: Optional[dict] = None   # {"choices": ["A", "B", ...]}
    correct_answer: str
    points: int = 1
    type: str = "mcq"
    difficulty: str = "medium"


class QuestionOut(BaseModel):
    id: str
    text: str
    type: str
    options: Optional[list[str]]
    correct_answer: str
    points: int
    difficulty: str


class ExamOut(BaseModel):
    id: str
    title: str
    subject: str
    class_id: str
    class_name: str
    duration_minutes: int
    is_active: bool
    question_count: int
    scheduled_at: Optional[str] = None
    created_at: str
    submitted_count: int = 0
    total_students: int = 0


class ExamDetailOut(BaseModel):
    id: str
    title: str
    subject: str
    class_id: str
    class_name: str
    duration_minutes: int
    is_active: bool
    questions: list[QuestionOut]
    scheduled_at: Optional[str] = None
    created_at: str


class ExamPatch(BaseModel):
    is_active: Optional[bool] = None
    title: Optional[str] = None
    duration_minutes: Optional[int] = None
    scheduled_at: Optional[str] = None


class ExamResultTeacherOut(BaseModel):
    result_id: str
    student_id: str
    student_name: str
    student_email: str
    score: float
    max_score: float
    percentage: float
    submitted_at: str
    rank: int
    violations: int = 0


@router.get("/exams", response_model=list[ExamOut])
async def get_teacher_exams(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Exam, Class)
        .join(Class, Class.id == Exam.class_id)
        .where(Exam.teacher_id == current_user.id)
        .order_by(Exam.created_at.desc())
    )
    rows = result.all()
    out = []
    for exam, cls in rows:
        q_count = await db.execute(
            select(func.count(Question.id)).where(Question.exam_id == exam.id)
        )
        # İştirakçı: təqdim edənlər / sinifdəki şagird sayı
        submitted = await db.execute(
            select(func.count(ExamResult.id)).where(ExamResult.exam_id == exam.id)
        )
        total_stu = await db.execute(
            select(func.count(Student.id)).where(Student.class_id == exam.class_id)
        )
        out.append(ExamOut(
            id=exam.id, title=exam.title, subject=exam.subject,
            class_id=exam.class_id, class_name=cls.name,
            duration_minutes=exam.duration_minutes,
            is_active=exam.is_active,
            question_count=q_count.scalar_one() or 0,
            scheduled_at=exam.scheduled_at.isoformat() if exam.scheduled_at else None,
            created_at=exam.created_at.isoformat() if exam.created_at else "",
            submitted_count=submitted.scalar_one() or 0,
            total_students=total_stu.scalar_one() or 0,
        ))
    return out


@router.post("/exams", response_model=ExamOut, status_code=201)
async def create_exam(
    body: ExamCreate,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    from fastapi import HTTPException
    cls_result = await db.execute(
        select(Class).where(Class.id == body.class_id, Class.teacher_id == current_user.id)
    )
    cls = cls_result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=403, detail="Bu sinif sizin deyil")

    from datetime import datetime as _dt
    sched = None
    if body.scheduled_at:
        try:
            sched = _dt.fromisoformat(body.scheduled_at)
        except ValueError:
            pass

    exam = Exam(
        class_id=body.class_id,
        teacher_id=current_user.id,
        title=body.title,
        subject=body.subject,
        duration_minutes=body.duration_minutes,
        is_active=False,
        scheduled_at=sched,
    )
    db.add(exam)
    await db.flush()

    # Notify all students in the class
    stu_result = await db.execute(
        select(Student).where(Student.class_id == body.class_id)
    )
    students = stu_result.scalars().all()
    for stu in students:
        await send_notification(
            db, stu.user_id,
            "Yeni imtahan",
            f'"{exam.title}" imtahanı əlavə edildi',
            "info",
        )

    await db.commit()
    await db.refresh(exam)
    return ExamOut(
        id=exam.id, title=exam.title, subject=exam.subject,
        class_id=exam.class_id, class_name=cls.name,
        duration_minutes=exam.duration_minutes,
        is_active=exam.is_active, question_count=0,
        scheduled_at=exam.scheduled_at.isoformat() if exam.scheduled_at else None,
        created_at=exam.created_at.isoformat() if exam.created_at else "",
    )


@router.get("/exams/{exam_id}", response_model=ExamDetailOut)
async def get_exam_detail(
    exam_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException
    result = await db.execute(
        select(Exam, Class)
        .join(Class, Class.id == Exam.class_id)
        .where(Exam.id == exam_id, Exam.teacher_id == current_user.id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="İmtahan tapılmadı")
    exam, cls = row
    q_result = await db.execute(
        select(Question).where(Question.exam_id == exam_id).order_by(Question.id)
    )
    questions = q_result.scalars().all()
    return ExamDetailOut(
        id=exam.id, title=exam.title, subject=exam.subject,
        class_id=exam.class_id, class_name=cls.name,
        duration_minutes=exam.duration_minutes, is_active=exam.is_active,
        scheduled_at=exam.scheduled_at.isoformat() if exam.scheduled_at else None,
        created_at=exam.created_at.isoformat() if exam.created_at else "",
        questions=[
            QuestionOut(
                id=q.id, text=q.text, type=q.type,
                options=(q.options if isinstance(q.options, list)
                         else q.options.get("choices", []) if isinstance(q.options, dict)
                         else []),
                correct_answer=q.correct_answer,
                points=q.points, difficulty=q.difficulty,
            )
            for q in questions
        ],
    )


@router.post("/exams/{exam_id}/questions", response_model=QuestionOut, status_code=201)
async def add_question(
    exam_id: str,
    body: QuestionCreate,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    from fastapi import HTTPException
    exam_result = await db.execute(
        select(Exam).where(Exam.id == exam_id, Exam.teacher_id == current_user.id)
    )
    exam = exam_result.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="İmtahan tapılmadı")

    q = Question(
        exam_id=exam_id,
        text=body.text,
        type=body.type,
        options=body.options,
        correct_answer=body.correct_answer,
        points=body.points,
        difficulty=body.difficulty,
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    # Extract choices from dict format {"choices": [...]} or use as-is if list
    def _choices(opts):
        if isinstance(opts, list): return opts
        if isinstance(opts, dict): return opts.get("choices", [])
        return []

    return QuestionOut(
        id=q.id, text=q.text, type=q.type,
        options=_choices(q.options),
        correct_answer=q.correct_answer, points=q.points, difficulty=q.difficulty,
    )


@router.patch("/exams/{exam_id}", response_model=ExamOut)
async def patch_exam(
    exam_id: str,
    body: ExamPatch,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    from fastapi import HTTPException
    result = await db.execute(
        select(Exam, Class)
        .join(Class, Class.id == Exam.class_id)
        .where(Exam.id == exam_id, Exam.teacher_id == current_user.id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="İmtahan tapılmadı")
    exam, cls = row
    if body.is_active is not None:
        # Sualsız imtahanı aktivləşdirmək olmaz (şagird verə bilməz)
        if body.is_active:
            qc = await db.execute(select(func.count(Question.id)).where(Question.exam_id == exam.id))
            if (qc.scalar_one() or 0) == 0:
                raise HTTPException(status_code=400, detail="NO_QUESTIONS")
        exam.is_active = body.is_active
        # Əl ilə deaktiv → planlaşdırıcı yenidən aktivləşdirməsin (ləğv kimi)
        if body.is_active is False:
            exam.auto_activated = True
    if body.title is not None:
        exam.title = body.title
    if body.duration_minutes is not None:
        exam.duration_minutes = body.duration_minutes
    if body.scheduled_at is not None:
        from datetime import datetime as _dt
        try:
            exam.scheduled_at = _dt.fromisoformat(body.scheduled_at)
        except ValueError:
            pass
    await db.commit()
    await db.refresh(exam)
    q_count = await db.execute(select(func.count(Question.id)).where(Question.exam_id == exam.id))
    return ExamOut(
        id=exam.id, title=exam.title, subject=exam.subject,
        class_id=exam.class_id, class_name=cls.name,
        duration_minutes=exam.duration_minutes, is_active=exam.is_active,
        question_count=q_count.scalar_one() or 0,
        scheduled_at=exam.scheduled_at.isoformat() if exam.scheduled_at else None,
        created_at=exam.created_at.isoformat() if exam.created_at else "",
    )


@router.delete("/exams/{exam_id}", status_code=204)
async def delete_exam(
    exam_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    from fastapi import HTTPException
    import sqlalchemy as _sa
    exam_result = await db.execute(
        select(Exam).where(Exam.id == exam_id, Exam.teacher_id == current_user.id)
    )
    exam = exam_result.scalar_one_or_none()
    if not exam:
        raise HTTPException(status_code=404, detail="İmtahan tapılmadı")

    # Əvvəlcə əlaqəli qeydləri sil (NOT NULL constraint-i pozmamaq üçün)
    await db.execute(_sa.delete(ExamResult).where(ExamResult.exam_id == exam_id))
    await db.execute(_sa.delete(Question).where(Question.exam_id == exam_id))
    await db.delete(exam)
    await db.commit()


class QuestionPatch(BaseModel):
    points: Optional[int] = None


@router.patch("/exams/{exam_id}/questions/{q_id}", response_model=QuestionOut)
async def patch_question(
    exam_id: str,
    q_id: str,
    body: QuestionPatch,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Sualın balını dəyiş."""
    _require_active(current_user)
    from fastapi import HTTPException
    exam_result = await db.execute(
        select(Exam).where(Exam.id == exam_id, Exam.teacher_id == current_user.id)
    )
    if not exam_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="İcazə yoxdur")
    q_result = await db.execute(select(Question).where(Question.id == q_id, Question.exam_id == exam_id))
    q = q_result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Sual tapılmadı")

    if body.points is not None:
        pts = max(1, min(100, int(body.points)))
        q.points = pts
    await db.commit()
    await db.refresh(q)

    def _choices(opts):
        if isinstance(opts, list): return opts
        if isinstance(opts, dict): return opts.get("choices", [])
        return []
    return QuestionOut(
        id=q.id, text=q.text, type=q.type,
        options=_choices(q.options), correct_answer=q.correct_answer,
        points=q.points, difficulty=q.difficulty,
    )


@router.delete("/exams/{exam_id}/questions/{q_id}", status_code=204)
async def delete_question(
    exam_id: str,
    q_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    from fastapi import HTTPException
    exam_result = await db.execute(
        select(Exam).where(Exam.id == exam_id, Exam.teacher_id == current_user.id)
    )
    if not exam_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Icaze yoxdur")
    q_result = await db.execute(select(Question).where(Question.id == q_id, Question.exam_id == exam_id))
    q = q_result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Sual tapılmadı")
    await db.delete(q)
    await db.commit()


# ── Analytics ────────────────────────────────────────────────────────────────

class StudentAnalyticsOut(BaseModel):
    student_id: str
    name: str
    class_name: str
    avg: float
    exam_count: int


class SubjectAnalyticsOut(BaseModel):
    subject: str
    avg: float
    student_count: int
    exam_count: int


class ClassAvgOut(BaseModel):
    class_name: str
    avg: float


class AnalyticsOut(BaseModel):
    avg_score: float
    pass_rate: float
    exam_count: int
    top_student: Optional[str]
    students: list[StudentAnalyticsOut]
    subjects: list[SubjectAnalyticsOut]
    class_avgs: list[ClassAvgOut]


# ── Question bank ──────────────────────────────────────────────────────────

class QuestionBankOut(BaseModel):
    id: str
    text: str
    type: str
    options: Optional[list[str]]
    correct_answer: str
    difficulty: str
    points: int
    exam_title: str
    subject: str


@router.get("/questions", response_model=list[QuestionBankOut])
async def get_teacher_questions(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Get all questions from all of this teacher's exams"""
    result = await db.execute(
        select(Question, Exam)
        .join(Exam, Exam.id == Question.exam_id)
        .where(Exam.teacher_id == current_user.id)
        .order_by(Exam.created_at.desc(), Question.id)
    )
    rows = result.all()
    def _choices(opts):
        if isinstance(opts, list): return opts
        if isinstance(opts, dict): return opts.get("choices", [])
        return []
    return [
        QuestionBankOut(
            id=q.id, text=q.text, type=q.type,
            options=_choices(q.options),
            correct_answer=q.correct_answer,
            difficulty=q.difficulty, points=q.points,
            exam_title=e.title, subject=e.subject,
        )
        for q, e in rows
    ]


@router.get("/analytics", response_model=AnalyticsOut)
async def get_teacher_analytics(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    # Get all classes and their students
    cls_result = await db.execute(
        select(Class).where(Class.teacher_id == current_user.id)
    )
    classes = cls_result.scalars().all()
    if not classes:
        return AnalyticsOut(
            avg_score=0, pass_rate=0, exam_count=0,
            top_student=None, students=[], subjects=[], class_avgs=[],
        )

    class_ids = [c.id for c in classes]
    class_map = {c.id: c.name for c in classes}

    # All students in these classes
    stu_result = await db.execute(
        select(Student, User)
        .join(User, User.id == Student.user_id)
        .where(Student.class_id.in_(class_ids))
    )
    all_students = stu_result.all()
    stu_ids = [s.id for s, _ in all_students]
    stu_name_map = {s.id: (u.name, s.class_id) for s, u in all_students}

    # All exam results
    if not stu_ids:
        return AnalyticsOut(
            avg_score=0, pass_rate=0, exam_count=0,
            top_student=None, students=[], subjects=[], class_avgs=[],
        )

    results_res = await db.execute(
        select(ExamResult, Exam)
        .join(Exam, Exam.id == ExamResult.exam_id)
        .where(ExamResult.student_id.in_(stu_ids))
    )
    result_rows = results_res.all()

    # Count unique exams
    exam_ids = list({e.id for _, e in result_rows})
    exam_count = len(exam_ids)

    # Aggregate per student
    stu_results: dict[str, list[float]] = {}
    for r, _ in result_rows:
        stu_results.setdefault(r.student_id, []).append(r.percentage)

    student_out = []
    for stu_id, percs in stu_results.items():
        name, cls_id = stu_name_map.get(stu_id, ("?", None))
        student_out.append(StudentAnalyticsOut(
            student_id=stu_id,
            name=name,
            class_name=class_map.get(cls_id or "", ""),
            avg=round(sum(percs) / len(percs), 1),
            exam_count=len(percs),
        ))
    student_out.sort(key=lambda s: s.avg, reverse=True)

    # Overall stats
    all_percs = [r.percentage for r, _ in result_rows]
    avg_score = round(sum(all_percs) / len(all_percs), 1) if all_percs else 0
    pass_rate = round(sum(1 for p in all_percs if p >= 60) / len(all_percs) * 100, 1) if all_percs else 0
    top_student = student_out[0].name if student_out else None

    # Per subject
    subj_data: dict[str, dict] = {}
    for r, e in result_rows:
        s = subj_data.setdefault(e.subject, {"percs": [], "stus": set(), "exams": set()})
        s["percs"].append(r.percentage)
        s["stus"].add(r.student_id)
        s["exams"].add(e.id)

    subjects_out = [
        SubjectAnalyticsOut(
            subject=subj,
            avg=round(sum(d["percs"]) / len(d["percs"]), 1),
            student_count=len(d["stus"]),
            exam_count=len(d["exams"]),
        )
        for subj, d in subj_data.items()
    ]

    # Per class avg
    cls_percs: dict[str, list[float]] = {}
    for r, _ in result_rows:
        _, cls_id = stu_name_map.get(r.student_id, (None, None))
        if cls_id:
            cls_percs.setdefault(cls_id, []).append(r.percentage)

    class_avgs = [
        ClassAvgOut(class_name=class_map[cid], avg=round(sum(ps) / len(ps), 1))
        for cid, ps in cls_percs.items()
    ]

    return AnalyticsOut(
        avg_score=avg_score, pass_rate=pass_rate, exam_count=exam_count,
        top_student=top_student, students=student_out, subjects=subjects_out,
        class_avgs=class_avgs,
    )


@router.get("/exams/{exam_id}/results", response_model=list[ExamResultTeacherOut])
async def get_exam_results(
    exam_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException
    exam_result = await db.execute(
        select(Exam).where(Exam.id == exam_id, Exam.teacher_id == current_user.id)
    )
    if not exam_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="İmtahan tapılmadı")

    results = await db.execute(
        select(ExamResult, Student, User)
        .join(Student, Student.id == ExamResult.student_id)
        .join(User, User.id == Student.user_id)
        .where(ExamResult.exam_id == exam_id)
        .order_by(ExamResult.percentage.desc())
    )
    return [
        ExamResultTeacherOut(
            result_id=r.id,
            student_id=s.id, student_name=u.name, student_email=u.email,
            score=r.score, max_score=r.max_score, percentage=r.percentage,
            submitted_at=r.submitted_at.strftime("%d.%m.%Y %H:%M") if r.submitted_at else "",
            rank=idx + 1,
            violations=getattr(r, "violations", 0) or 0,
        )
        for idx, (r, s, u) in enumerate(results.all())
    ]


# ── Sual analizi: hər sual üzrə düzgünlük faizi ──────────────────────────────
def _is_correct(q, ans: str, manual: dict) -> bool:
    if q.type == "open":
        # əl ilə qiymət verilibsə ona görə
        if str(q.id) in manual:
            return manual[str(q.id)] >= q.points
        return (ans or "").strip().lower() == (q.correct_answer or "").strip().lower()
    return (ans or "").strip().lower() == (q.correct_answer or "").strip().lower()


class QuestionAnalysisOut(BaseModel):
    id: str
    text: str
    type: str
    points: int
    answered: int
    correct: int
    wrong: int
    correct_rate: float


@router.get("/exams/{exam_id}/question-analysis", response_model=list[QuestionAnalysisOut])
async def question_analysis(
    exam_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Hər sual üzrə neçə şagird düzgün/səhv cavablandırıb."""
    from fastapi import HTTPException
    exam_res = await db.execute(select(Exam).where(Exam.id == exam_id, Exam.teacher_id == current_user.id))
    if not exam_res.scalar_one_or_none():
        raise HTTPException(404, "İmtahan tapılmadı")

    qs = (await db.execute(select(Question).where(Question.exam_id == exam_id).order_by(Question.id))).scalars().all()
    results = (await db.execute(select(ExamResult).where(ExamResult.exam_id == exam_id))).scalars().all()

    out = []
    for q in qs:
        answered = correct = 0
        for r in results:
            ans = (r.answers or {}).get(q.id)
            manual = r.manual_grades or {}
            if ans is not None and str(ans).strip() != "":
                answered += 1
                if _is_correct(q, str(ans), manual):
                    correct += 1
        wrong = answered - correct
        rate = round(correct / answered * 100, 1) if answered else 0.0
        out.append(QuestionAnalysisOut(
            id=q.id, text=q.text, type=q.type, points=q.points,
            answered=answered, correct=correct, wrong=wrong, correct_rate=rate,
        ))
    return out


# ── Açıq suala əl ilə qiymət ─────────────────────────────────────────────────
class SubmissionAnswerOut(BaseModel):
    question_id: str
    text: str
    type: str
    points: int
    student_answer: str
    correct_answer: str
    awarded: float
    is_open: bool


class SubmissionDetailOut(BaseModel):
    result_id: str
    student_name: str
    score: float
    max_score: float
    percentage: float
    answers: list[SubmissionAnswerOut]


@router.get("/exam-results/{result_id}", response_model=SubmissionDetailOut)
async def get_submission_detail(
    result_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Bir şagirdin təqdimatı — açıq suallara əl ilə qiymət vermək üçün."""
    from fastapi import HTTPException
    row = (await db.execute(
        select(ExamResult, Exam, User)
        .join(Exam, Exam.id == ExamResult.exam_id)
        .join(Student, Student.id == ExamResult.student_id)
        .join(User, User.id == Student.user_id)
        .where(ExamResult.id == result_id, Exam.teacher_id == current_user.id)
    )).first()
    if not row:
        raise HTTPException(404, "Təqdimat tapılmadı")
    r, exam, u = row
    qs = (await db.execute(select(Question).where(Question.exam_id == exam.id).order_by(Question.id))).scalars().all()
    answers_in = r.answers or {}
    manual = r.manual_grades or {}

    out_ans = []
    for q in qs:
        ans = str(answers_in.get(q.id, "") or "")
        if q.type == "open":
            awarded = float(manual.get(str(q.id), q.points if _is_correct(q, ans, manual) else 0))
        else:
            awarded = float(q.points if _is_correct(q, ans, {}) else 0)
        out_ans.append(SubmissionAnswerOut(
            question_id=q.id, text=q.text, type=q.type, points=q.points,
            student_answer=ans, correct_answer=q.correct_answer or "",
            awarded=awarded, is_open=(q.type == "open"),
        ))
    return SubmissionDetailOut(
        result_id=r.id, student_name=u.name,
        score=r.score, max_score=r.max_score, percentage=r.percentage,
        answers=out_ans,
    )


class GradeBody(BaseModel):
    open_grades: dict  # {question_id: verilən_bal}


@router.patch("/exam-results/{result_id}", response_model=SubmissionDetailOut)
async def grade_submission(
    result_id: str,
    body: GradeBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Açıq suallara əl ilə bal ver, ümumi nəticəni yenidən hesabla."""
    from fastapi import HTTPException
    row = (await db.execute(
        select(ExamResult, Exam)
        .join(Exam, Exam.id == ExamResult.exam_id)
        .where(ExamResult.id == result_id, Exam.teacher_id == current_user.id)
    )).first()
    if not row:
        raise HTTPException(404, "Təqdimat tapılmadı")
    r, exam = row
    qs = (await db.execute(select(Question).where(Question.exam_id == exam.id))).scalars().all()
    q_map = {q.id: q for q in qs}

    # Əl ilə qiymətləri yadda saxla (yalnız açıq suallar, 0..points aralığı)
    manual = dict(r.manual_grades or {})
    for qid, pts in (body.open_grades or {}).items():
        q = q_map.get(qid)
        if q and q.type == "open":
            manual[str(qid)] = max(0, min(q.points, float(pts)))
    r.manual_grades = manual

    # Ümumi balı yenidən hesabla
    answers_in = r.answers or {}
    score = 0.0
    for q in qs:
        ans = str(answers_in.get(q.id, "") or "")
        if q.type == "open":
            score += float(manual.get(str(q.id), q.points if _is_correct(q, ans, manual) else 0))
        else:
            score += float(q.points if _is_correct(q, ans, {}) else 0)
    r.score = score
    r.percentage = round(score / r.max_score * 100, 1) if r.max_score > 0 else 0.0
    await db.commit()
    await db.refresh(r)

    # Detalı qaytar
    return await get_submission_detail(result_id, current_user, db)


# ── Student Detail ─────────────────────────────────────────────────────────

class ExamHistoryItem(BaseModel):
    name: str
    date: str
    score: float
    subject: str


class TopicPerf(BaseModel):
    topic: str
    pct: float


class ParentInfo(BaseModel):
    id: str
    name: str
    email: str
    phone: Optional[str] = None


class StudentDetailOut(BaseModel):
    id: str
    name: str
    email: str
    class_name: str
    xp: int
    streak: int
    level: int
    exam_count: int
    pass_rate: float
    avg_score: float
    exam_history: list[ExamHistoryItem]
    subject_performance: list[TopicPerf]
    parent: Optional[ParentInfo] = None


@router.get("/students/{student_id}/detail", response_model=StudentDetailOut)
async def get_student_detail(
    student_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException

    # Verify teacher owns a class containing this student
    cls_result = await db.execute(
        select(Class.id).where(Class.teacher_id == current_user.id)
    )
    class_ids = [row[0] for row in cls_result.all()]

    stu_result = await db.execute(
        select(Student, User, Class)
        .join(User, User.id == Student.user_id)
        .join(Class, Class.id == Student.class_id)
        .where(User.id == student_id, Student.class_id.in_(class_ids))
    )
    row = stu_result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Şagird tapılmadı")
    stu, user, cls = row

    # Get all exam results for this student from teacher's exams
    results_res = await db.execute(
        select(ExamResult, Exam)
        .join(Exam, Exam.id == ExamResult.exam_id)
        .where(ExamResult.student_id == stu.id, Exam.teacher_id == current_user.id)
        .order_by(ExamResult.submitted_at.desc())
    )
    result_rows = results_res.all()

    exam_history = []
    for r, e in result_rows:
        exam_history.append(ExamHistoryItem(
            name=e.title,
            date=r.submitted_at.strftime("%d %b") if r.submitted_at else "",
            score=round(r.percentage),
            subject=e.subject,
        ))

    # Subject-level aggregation
    subj_percs: dict[str, list[float]] = {}
    for r, e in result_rows:
        subj_percs.setdefault(e.subject, []).append(r.percentage)

    subject_performance = [
        TopicPerf(topic=subj, pct=round(sum(ps) / len(ps), 1))
        for subj, ps in subj_percs.items()
    ]
    subject_performance.sort(key=lambda x: x.pct)

    all_percs = [r.percentage for r, _ in result_rows]
    avg_score = round(sum(all_percs) / len(all_percs), 1) if all_percs else 0
    pass_rate = round(sum(1 for p in all_percs if p >= 60) / len(all_percs) * 100, 1) if all_percs else 0

    # Fetch parent if linked
    parent_out = None
    if stu.parent_id:
        p_res = await db.execute(select(User).where(User.id == stu.parent_id))
        p_user = p_res.scalar_one_or_none()
        if p_user:
            parent_out = ParentInfo(
                id=p_user.id,
                name=p_user.name,
                email=p_user.email,
                phone=getattr(p_user, "phone", None),
            )

    return StudentDetailOut(
        id=user.id,
        name=user.name,
        email=user.email,
        class_name=cls.name,
        xp=stu.xp,
        streak=stu.streak,
        level=stu.level,
        exam_count=len(result_rows),
        pass_rate=pass_rate,
        avg_score=avg_score,
        exam_history=exam_history[:10],
        subject_performance=subject_performance,
        parent=parent_out,
    )


# ── Teacher Meetings ──────────────────────────────────────────────────────────

import json as _json
import os as _os

_MEETINGS_FILE = _os.path.join(_os.path.dirname(__file__), "..", "meetings_data.json")


def _load_meetings() -> dict:
    try:
        if _os.path.exists(_MEETINGS_FILE):
            with open(_MEETINGS_FILE, "r", encoding="utf-8") as f:
                return _json.load(f)
    except Exception:
        pass
    return {}


def _save_meetings(data: dict):
    try:
        with open(_MEETINGS_FILE, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass


class TeacherMeetingOut(BaseModel):
    id: str
    parent_id: str
    child_name: str
    subject: str
    preferred_date: str
    note: Optional[str]
    status: str
    created_at: str
    # Canlı görüş
    join_state: str = "not_confirmed"
    can_join: bool = False
    starts_in_minutes: Optional[int] = None
    room_url: Optional[str] = None


class MeetingPatch(BaseModel):
    status: str  # "confirmed" | "cancelled" | "pending"


@router.get("/meetings", response_model=list[TeacherMeetingOut])
async def get_teacher_meetings(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Returns all meeting requests addressed to this teacher (by teacher_id or via class students)."""
    from app.models.repetitor import RepetitorStudent

    # 1) Sinif şagirdlərinin valideyn ID-ləri
    cls_res = await db.execute(select(Class.id).where(Class.teacher_id == current_user.id))
    class_ids = [r[0] for r in cls_res.all()]
    parent_ids: set[str] = set()
    if class_ids:
        stu_res = await db.execute(
            select(Student.parent_id).where(
                Student.class_id.in_(class_ids),
                Student.parent_id.isnot(None)
            )
        )
        parent_ids = set(str(r[0]) for r in stu_res.all())

    # 2) Repetitor şagirdlərinin valideyn ID-ləri
    rep_res = await db.execute(
        select(RepetitorStudent.parent_user_id).where(
            RepetitorStudent.teacher_id == current_user.id,
            RepetitorStudent.parent_user_id.isnot(None)
        )
    )
    for r in rep_res.all():
        if r[0]:
            parent_ids.add(str(r[0]))

    from app.services.meeting_room import join_info

    meetings = _load_meetings()
    result = []
    for m in meetings.values():
        # a) Birbaşa bu müəllimə ünvanlanıb (teacher_id ilə)
        # b) Və ya valideyn bu müəllimin sinfindəki/repetitor şagirdinin valideyndir
        by_teacher = m.get("teacher_id") == current_user.id
        by_parent  = m.get("parent_id") in parent_ids and not m.get("teacher_id")
        if by_teacher or by_parent:
            ji = join_info(m["id"], m.get("preferred_date", ""), m.get("status", "pending"))
            result.append(TeacherMeetingOut(
                id=m["id"],
                parent_id=m.get("parent_id", ""),
                child_name=m.get("child_name", ""),
                subject=m.get("subject", ""),
                preferred_date=m.get("preferred_date", ""),
                note=m.get("note"),
                status=m.get("status", "pending"),
                created_at=m.get("created_at", ""),
                **ji,
            ))

    result.sort(key=lambda x: x.created_at, reverse=True)
    return result


@router.patch("/meetings/{meeting_id}", response_model=TeacherMeetingOut)
async def patch_teacher_meeting(
    meeting_id: str,
    body: MeetingPatch,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    from fastapi import HTTPException
    from app.models.repetitor import RepetitorStudent
    from app.services.meeting_room import join_info

    # İcazə: sinif şagirdləri + repetitor şagirdlərinin valideynləri
    cls_res = await db.execute(select(Class.id).where(Class.teacher_id == current_user.id))
    class_ids = [r[0] for r in cls_res.all()]
    parent_ids: set[str] = set()
    if class_ids:
        stu_res = await db.execute(
            select(Student.parent_id).where(
                Student.class_id.in_(class_ids),
                Student.parent_id.isnot(None)
            )
        )
        parent_ids = set(str(r[0]) for r in stu_res.all())
    rep_res = await db.execute(
        select(RepetitorStudent.parent_user_id).where(
            RepetitorStudent.teacher_id == current_user.id,
            RepetitorStudent.parent_user_id.isnot(None)
        )
    )
    for r in rep_res.all():
        if r[0]:
            parent_ids.add(str(r[0]))

    meetings = _load_meetings()
    m = meetings.get(meeting_id)
    # Birbaşa teacher_id ilə, və ya valideyn əlaqəsi ilə
    allowed = m and (m.get("teacher_id") == current_user.id or m.get("parent_id") in parent_ids)
    if not allowed:
        raise HTTPException(status_code=404, detail="Görüş tapılmadı")

    if body.status not in ("confirmed", "cancelled", "pending"):
        raise HTTPException(status_code=400, detail="Yanlış status")

    m["status"] = body.status
    meetings[meeting_id] = m
    _save_meetings(meetings)

    ji = join_info(m["id"], m.get("preferred_date", ""), m["status"])
    return TeacherMeetingOut(
        id=m["id"],
        parent_id=m.get("parent_id", ""),
        child_name=m.get("child_name", ""),
        subject=m.get("subject", ""),
        preferred_date=m.get("preferred_date", ""),
        note=m.get("note"),
        status=m["status"],
        created_at=m.get("created_at", ""),
        **ji,
    )


# ── Live Room (legacy) ────────────────────────────────────────────────────────

class LiveRoomOut(BaseModel):
    room_name: str
    url: str


@router.get("/live-room", response_model=LiveRoomOut)
async def get_teacher_live_room(
    current_user: User = Depends(require_teacher),
):
    """Returns deterministic Jitsi room name for this teacher based on tenant_id."""
    room_name = f"eduai-{current_user.tenant_id[:8]}"
    return LiveRoomOut(room_name=room_name, url=f"https://meet.jit.si/{room_name}")


# ── Live Sessions ─────────────────────────────────────────────────────────────

class LiveSessionOut(BaseModel):
    id: str
    teacher_id: str
    teacher_name: str
    class_id: Optional[str]
    class_name: Optional[str]
    title: str
    description: Optional[str]
    scheduled_at: Optional[str]
    started_at: Optional[str]
    ended_at: Optional[str]
    status: str          # scheduled | live | ended
    room_name: str
    join_url: str
    created_at: str


class LiveSessionCreate(BaseModel):
    title: str
    class_id: Optional[str] = None
    description: Optional[str] = None
    scheduled_at: Optional[str] = None   # ISO datetime or None for instant


def _session_to_out(s: dict, teacher_name: str, class_name: Optional[str]) -> LiveSessionOut:
    room = s["room_name"]
    return LiveSessionOut(
        id=s["id"],
        teacher_id=s["teacher_id"],
        teacher_name=teacher_name,
        class_id=s.get("class_id"),
        class_name=class_name,
        title=s["title"],
        description=s.get("description"),
        scheduled_at=s.get("scheduled_at"),
        started_at=s.get("started_at"),
        ended_at=s.get("ended_at"),
        status=s["status"],
        room_name=room,
        join_url=f"https://meet.jit.si/{room}",
        created_at=s.get("created_at", ""),
    )


import sqlalchemy as _sa


async def _fetch_session(conn, session_id: str, teacher_id: str):
    r = await conn.execute(
        _sa.text("SELECT * FROM live_sessions WHERE id=:id AND teacher_id=:tid"),
        {"id": session_id, "tid": teacher_id}
    )
    row = r.mappings().one_or_none()
    return dict(row) if row else None


async def _list_sessions_raw(conn, teacher_id: str):
    r = await conn.execute(
        _sa.text("SELECT * FROM live_sessions WHERE teacher_id=:tid ORDER BY created_at DESC"),
        {"tid": teacher_id}
    )
    return [dict(row) for row in r.mappings().all()]


async def _class_name_for(db: AsyncSession, class_id: Optional[str]) -> Optional[str]:
    if not class_id:
        return None
    res = await db.execute(select(Class).where(Class.id == class_id))
    cls = res.scalar_one_or_none()
    return cls.name if cls else None


@router.get("/live-sessions", response_model=list[LiveSessionOut])
async def list_live_sessions(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    from app.database import engine
    async with engine.connect() as conn:
        rows = await _list_sessions_raw(conn, current_user.id)
    result = []
    for s in rows:
        cname = await _class_name_for(db, s.get("class_id"))
        result.append(_session_to_out(s, current_user.name, cname))
    return result


@router.post("/live-sessions", response_model=LiveSessionOut, status_code=201)
async def create_live_session(
    body: LiveSessionCreate,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    import uuid as _uuid
    from datetime import datetime as _dt

    sid = str(_uuid.uuid4())
    room_name = f"va-{sid[:12]}"
    now_iso = _dt.utcnow().isoformat() + "Z"

    # If no scheduled_at, it starts immediately as 'live'
    status = "live" if not body.scheduled_at else "scheduled"
    started_at = now_iso if status == "live" else None

    from app.database import engine
    async with engine.begin() as conn:
        await conn.execute(_sa.text("""
            INSERT INTO live_sessions
              (id, teacher_id, class_id, title, description, scheduled_at,
               started_at, status, room_name, created_at)
            VALUES
              (:id, :tid, :cid, :title, :desc, :sched,
               :started, :status, :room, :created)
        """), {
            "id": sid, "tid": current_user.id, "cid": body.class_id,
            "title": body.title, "desc": body.description,
            "sched": body.scheduled_at, "started": started_at,
            "status": status, "room": room_name, "created": now_iso,
        })

    # Notify students if class specified and session is live now
    if body.class_id and status == "live":
        stu_r = await db.execute(select(Student).where(Student.class_id == body.class_id))
        for stu in stu_r.scalars().all():
            await send_notification(
                db, stu.user_id,
                "🔴 Canlı dərs başladı",
                f'"{body.title}" — dərsiniz başladı, indi qoşulun!',
                "info",
            )
        await db.commit()

    cname = await _class_name_for(db, body.class_id)
    s = {
        "id": sid, "teacher_id": current_user.id, "class_id": body.class_id,
        "title": body.title, "description": body.description,
        "scheduled_at": body.scheduled_at, "started_at": started_at,
        "ended_at": None, "status": status, "room_name": room_name,
        "created_at": now_iso,
    }
    return _session_to_out(s, current_user.name, cname)


@router.patch("/live-sessions/{session_id}/start", response_model=LiveSessionOut)
async def start_live_session(
    session_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    from datetime import datetime as _dt
    from app.database import engine

    async with engine.begin() as conn:
        s = await _fetch_session(conn, session_id, current_user.id)
        if not s:
            raise HTTPException(status_code=404, detail="Sessiya tapılmadı")
        now_iso = _dt.utcnow().isoformat() + "Z"
        await conn.execute(_sa.text("""
            UPDATE live_sessions SET status='live', started_at=:now WHERE id=:id
        """), {"now": now_iso, "id": session_id})
        s["status"] = "live"
        s["started_at"] = now_iso

    # Notify students
    if s.get("class_id"):
        stu_r = await db.execute(select(Student).where(Student.class_id == s["class_id"]))
        for stu in stu_r.scalars().all():
            await send_notification(
                db, stu.user_id,
                "🔴 Canlı dərs başladı",
                f'"{s["title"]}" — dərsiniz başladı, indi qoşulun!',
                "info",
            )
        await db.commit()

    cname = await _class_name_for(db, s.get("class_id"))
    return _session_to_out(s, current_user.name, cname)


@router.patch("/live-sessions/{session_id}/end", response_model=LiveSessionOut)
async def end_live_session(
    session_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    _require_active(current_user)
    from datetime import datetime as _dt
    from app.database import engine

    async with engine.begin() as conn:
        s = await _fetch_session(conn, session_id, current_user.id)
        if not s:
            raise HTTPException(status_code=404, detail="Sessiya tapılmadı")
        now_iso = _dt.utcnow().isoformat() + "Z"
        await conn.execute(_sa.text("""
            UPDATE live_sessions SET status='ended', ended_at=:now WHERE id=:id
        """), {"now": now_iso, "id": session_id})
        s["status"] = "ended"
        s["ended_at"] = now_iso

    cname = await _class_name_for(db, s.get("class_id"))
    return _session_to_out(s, current_user.name, cname)


@router.delete("/live-sessions/{session_id}", status_code=204)
async def delete_live_session(
    session_id: str,
    current_user: User = Depends(require_teacher),
):
    _require_active(current_user)
    from app.database import engine
    async with engine.begin() as conn:
        s = await _fetch_session(conn, session_id, current_user.id)
        if not s:
            raise HTTPException(status_code=404, detail="Sessiya tapılmadı")
        await conn.execute(
            _sa.text("DELETE FROM live_sessions WHERE id=:id"),
            {"id": session_id}
        )


# ── Contact Info ──────────────────────────────────────────────────────────────

class ContactInfo(BaseModel):
    phone: str
    email: str
    whatsapp: str
    message: str


@router.get("/contact-info", response_model=ContactInfo)
async def get_contact_info(
    _current_user: User = Depends(require_teacher),
):
    """Returns platform contact info for pending teachers."""
    import json as _cjson, os as _cos
    _settings_file = _cos.path.join(_cos.path.dirname(__file__), "..", "platform_settings.json")
    defaults = {
        "phone": "+994 50 000 00 00",
        "email": "info@eduai.az",
        "whatsapp": "",
        "message": "Hesabınızı aktivləşdirmək üçün bizimlə əlaqəyə keçin.",
    }
    try:
        if _cos.path.exists(_settings_file):
            with open(_settings_file, "r", encoding="utf-8") as f:
                data = _cjson.load(f)
                defaults["phone"] = data.get("contact_phone", defaults["phone"])
                defaults["email"] = data.get("contact_email", defaults["email"])
                defaults["whatsapp"] = data.get("contact_whatsapp", defaults["whatsapp"])
                defaults["message"] = data.get("contact_message", defaults["message"])
    except Exception:
        pass
    return ContactInfo(**defaults)


# ── Davamiyyət (Attendance) ────────────────────────────────────────────────────
import json as _json
import os as _os
from datetime import date as _date_cls

_ATTENDANCE_FILE = _os.path.join(_os.path.dirname(__file__), "..", "attendance_data.json")


def _load_attendance():
    try:
        if _os.path.exists(_ATTENDANCE_FILE):
            with open(_ATTENDANCE_FILE, "r", encoding="utf-8") as f:
                return _json.load(f)
    except Exception:
        pass
    return {}


def _save_attendance(data):
    try:
        with open(_ATTENDANCE_FILE, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _norm_status(v) -> str:
    """Köhnə bool data ilə uyğunluq: True→present, False→absent, string→olduğu kimi."""
    if v is True:
        return "present"
    if v is False or v is None:
        return "absent"
    if isinstance(v, str) and v in ("present", "absent", "late"):
        return v
    return "absent"


class AttendanceRecord(BaseModel):
    student_id: str
    status: str = "absent"   # present | absent | late


class AttendanceSave(BaseModel):
    class_id: str
    date: str  # YYYY-MM-DD
    records: list[AttendanceRecord]


class AttendanceStudentRow(BaseModel):
    student_id: str
    student_name: str
    status: str   # present | absent | late


@router.get("/attendance", response_model=list[AttendanceStudentRow])
async def get_attendance(
    class_id: str,
    date: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Müəyyən sinif + tarix üçün davamiyyət siyahısını qaytar"""
    _require_active(current_user)

    # Sinfin mövcudluğunu yoxla
    cls_res = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == current_user.id)
    )
    cls = cls_res.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Sinif tapılmadı")

    # Sinif şagirdlərini al
    stu_res = await db.execute(
        select(User, Student)
        .join(Student, Student.user_id == User.id)
        .where(Student.class_id == class_id, User.is_active == True)
        .order_by(User.name)
    )
    rows = stu_res.all()

    # Saxlanmış qeydləri yüklə
    key = f"{current_user.tenant_id}_{class_id}_{date}"
    attendance = _load_attendance()
    saved = attendance.get(key, {})

    return [
        AttendanceStudentRow(
            student_id=u.id,
            student_name=u.name,
            status=_norm_status(saved.get(u.id, "absent")),
        )
        for u, _ in rows
    ]


@router.post("/attendance", response_model=dict)
async def save_attendance(
    body: AttendanceSave,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Davamiyyəti saxla"""
    _require_active(current_user)

    # Sinfin bu müəllimə aid olduğunu yoxla
    cls_res = await db.execute(
        select(Class).where(Class.id == body.class_id, Class.teacher_id == current_user.id)
    )
    if not cls_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Sinif tapılmadı")

    key = f"{current_user.tenant_id}_{body.class_id}_{body.date}"
    attendance = _load_attendance()
    attendance[key] = {r.student_id: _norm_status(r.status) for r in body.records}
    _save_attendance(attendance)

    present = sum(1 for r in body.records if r.status == "present")
    late    = sum(1 for r in body.records if r.status == "late")
    absent  = sum(1 for r in body.records if r.status == "absent")
    return {"saved": True, "present": present, "late": late, "absent": absent}


# ══════════════════════════════════════════════════════════════════════════════
# ELANLAR — Korporativ admin tərəfindən yaradılan elanlar
# ══════════════════════════════════════════════════════════════════════════════

_ANNOUNCEMENTS_FILE_T = os.path.join(os.path.dirname(__file__), "..", "announcements_data.json")


class TeacherAnnouncementOut(BaseModel):
    id: str
    title: str
    message: str
    target: str
    created_at: str


@router.get("/announcements", response_model=List[TeacherAnnouncementOut])
async def get_teacher_announcements(
    current_user: User = Depends(require_teacher),
):
    """Müəllimin müəssisəsinə aid elanlar (target=all veya teachers)"""
    _require_active(current_user)
    if not os.path.exists(_ANNOUNCEMENTS_FILE_T):
        return []
    with open(_ANNOUNCEMENTS_FILE_T, encoding="utf-8") as f:
        all_data = json.load(f)
    return [
        TeacherAnnouncementOut(
            id=a["id"], title=a["title"], message=a["message"],
            target=a["target"], created_at=a["created_at"],
        )
        for a in all_data
        if a["tenant_id"] == current_user.tenant_id
        and a["target"] in ("all", "teachers")
    ]


# ─── Branding ─────────────────────────────────────────────────────────────────

class BrandingPatch(BaseModel):
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None


@router.get("/branding")
async def get_teacher_branding(
    actor: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Müəllimin aid olduğu müəssisənin branding məlumatları"""
    if not actor.tenant_id:
        return {"logo_url": None, "primary_color": None}
    tenant = await db.get(Tenant, actor.tenant_id)
    if not tenant:
        return {"logo_url": None, "primary_color": None}
    return {"logo_url": tenant.logo_url, "primary_color": tenant.primary_color}


@router.patch("/branding")
async def patch_teacher_branding(
    body: BrandingPatch,
    actor: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Repetitor müəllim öz müəssisəsinin branding-ini yeniləyir"""
    if not actor.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant tapılmadı")
    tenant = await db.get(Tenant, actor.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")
    if body.logo_url is not None:
        tenant.logo_url = body.logo_url or None
    if body.primary_color is not None:
        if body.primary_color and not re.match(r'^#[0-9A-Fa-f]{6}$', body.primary_color):
            raise HTTPException(status_code=422, detail="Rəng #RRGGBB formatında olmalıdır")
        tenant.primary_color = body.primary_color or None
    await db.commit()
    return {"logo_url": tenant.logo_url, "primary_color": tenant.primary_color}


@router.post("/branding/logo")
async def upload_teacher_branding_logo(
    file: UploadFile = File(...),
    actor: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Logo şəklini yükləyib base64 data-URL kimi saxla."""
    import base64
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Yalnız şəkil faylı qəbul edilir")
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Şəkil 2 MB-dan böyük ola bilməz")
    b64 = base64.b64encode(data).decode()
    logo_url = f"data:{file.content_type};base64,{b64}"
    if not actor.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant tapılmadı")
    tenant = await db.get(Tenant, actor.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")
    tenant.logo_url = logo_url
    await db.commit()
    return {"logo_url": logo_url}
