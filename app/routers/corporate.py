"""
Corporate Router
----------------
/corporate/* — EduAI-dən lisenziya alan təhsil müəssisəsinin admin paneli.
Müəssisənin öz müəllimləri, şagirdləri və sinifləri üzərində idarəetmə.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
import csv
import io
import json
import os
import uuid
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List
from app.database import get_db
from app.dependencies import require_role
from app.models.user import User
from app.models.tenant import Tenant
from app.models.student import Student
from app.models.class_model import Class
from app.models.exam import Exam, ExamResult
from app.services.auth_service import hash_password

router = APIRouter(prefix="/corporate", tags=["Corporate"])
require_corporate = require_role("corporate", "superadmin")


# ── Schemas ────────────────────────────────────────────────────────────────────

class CorporateDashboard(BaseModel):
    institution_name: str
    tenant_slug: str
    admin_name: str
    admin_email: str
    admin_avatar_url: Optional[str] = None
    total_teachers: int
    total_students: int
    total_classes: int
    active_users: int
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None


class TeacherOut(BaseModel):
    id: str
    name: str
    email: str
    is_active: bool
    class_count: int


class TeacherCreate(BaseModel):
    name: str
    email: str
    password: str


class StudentOut(BaseModel):
    id: str
    name: str
    email: str
    is_active: bool
    class_name: Optional[str]
    xp: int
    level: int


class StudentCreate(BaseModel):
    name: str
    email: str
    password: str
    class_id: Optional[str] = None


class ClassOut(BaseModel):
    id: str
    name: str
    subject: str
    teacher_name: str
    student_count: int


class ClassCreate(BaseModel):
    name: str
    subject: str
    teacher_id: str


class ClassUpdate(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    teacher_id: Optional[str] = None


class UserStatusUpdate(BaseModel):
    is_active: bool


class AssignClassBody(BaseModel):
    class_id: Optional[str] = None


class ClassStudentOut(BaseModel):
    id: str
    name: str
    email: str
    xp: int
    level: int


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=CorporateDashboard)
async def get_corporate_dashboard(
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Müəssisə idarəçisinin əsas göstəriciləri"""
    import sqlalchemy as _sa

    # Single query: tenant info + all user aggregates in one round-trip
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id)
    )
    tenant = tenant_result.scalar_one_or_none()

    agg = await db.execute(_sa.text("""
        SELECT
            SUM(CASE WHEN role = 'teacher' THEN 1 ELSE 0 END) AS teachers,
            SUM(CASE WHEN role = 'student' THEN 1 ELSE 0 END) AS students,
            SUM(CASE WHEN is_active = 1     THEN 1 ELSE 0 END) AS active
        FROM users WHERE tenant_id = :tid
    """), {"tid": current_user.tenant_id})
    row = agg.fetchone()

    cls_count = await db.execute(
        select(func.count(Class.id)).where(Class.tenant_id == current_user.tenant_id)
    )

    return CorporateDashboard(
        institution_name=tenant.name if tenant else "Müəssisə",
        tenant_slug=tenant.slug if tenant else "",
        admin_name=current_user.name,
        admin_email=current_user.email,
        admin_avatar_url=current_user.avatar_url,
        total_teachers=row.teachers or 0,
        total_students=row.students or 0,
        total_classes=cls_count.scalar_one() or 0,
        active_users=row.active or 0,
        logo_url=tenant.logo_url if tenant else None,
        primary_color=tenant.primary_color if tenant else None,
    )


@router.get("/teachers", response_model=list[TeacherOut])
async def get_teachers(
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Müəssisəyə bağlı bütün müəllimlər"""
    result = await db.execute(
        select(User)
        .where(User.tenant_id == current_user.tenant_id, User.role == "teacher")
        .order_by(User.name)
    )
    teachers = result.scalars().all()

    out = []
    for t in teachers:
        cls_count_result = await db.execute(
            select(func.count(Class.id)).where(Class.teacher_id == t.id)
        )
        cls_count = cls_count_result.scalar_one() or 0
        out.append(TeacherOut(
            id=t.id, name=t.name, email=t.email,
            is_active=t.is_active, class_count=cls_count,
        ))
    return out


@router.post("/teachers", response_model=TeacherOut, status_code=201)
async def create_teacher(
    body: TeacherCreate,
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Yeni müəllim yarat"""
    # Email unikallığını yoxla
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Bu e-poçt artıq istifadə olunur")

    new_user = User(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        name=body.name,
        email=body.email,
        hashed_password=hash_password(body.password),
        role="teacher",
        is_active=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return TeacherOut(
        id=new_user.id, name=new_user.name, email=new_user.email,
        is_active=new_user.is_active, class_count=0,
    )


@router.patch("/users/{user_id}", response_model=dict)
async def update_user_status(
    user_id: str,
    body: UserStatusUpdate,
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Müəllim/şagird aktiv/deaktiv et"""
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="İstifadəçi tapılmadı")

    user.is_active = body.is_active

    # Şagird deaktiv edildikdə sinifdən avtomatik çıxar
    if not body.is_active and user.role == "student":
        stu_res = await db.execute(select(Student).where(Student.user_id == user_id))
        stu = stu_res.scalar_one_or_none()
        if stu and stu.class_id:
            stu.class_id = None

    await db.commit()
    await db.refresh(user)

    return {"id": user.id, "name": user.name, "email": user.email, "is_active": user.is_active}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Müəllim və ya şagirdi sil"""
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="İstifadəçi tapılmadı")

    await db.delete(user)
    await db.commit()


@router.get("/students", response_model=list[StudentOut])
async def get_students(
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Müəssisəyə bağlı bütün şagirdlər"""
    result = await db.execute(
        select(User, Student, Class)
        .join(Student, Student.user_id == User.id, isouter=True)
        .join(Class, Class.id == Student.class_id, isouter=True)
        .where(User.tenant_id == current_user.tenant_id, User.role == "student")
        .order_by(User.name)
    )
    rows = result.all()
    return [
        StudentOut(
            id=u.id, name=u.name, email=u.email, is_active=u.is_active,
            class_name=cls.name if cls else None,
            xp=stu.xp if stu else 0,
            level=stu.level if stu else 1,
        )
        for u, stu, cls in rows
    ]


@router.post("/students", response_model=StudentOut, status_code=201)
async def create_student(
    body: StudentCreate,
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Yeni şagird yarat"""
    # Email unikallığını yoxla
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Bu e-poçt artıq istifadə olunur")

    # User yarat
    new_user = User(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        name=body.name,
        email=body.email,
        hashed_password=hash_password(body.password),
        role="student",
        is_active=True,
    )
    db.add(new_user)
    await db.flush()  # ID-ni al

    # Student profil yarat
    new_student = Student(
        id=str(uuid.uuid4()),
        user_id=new_user.id,
        class_id=body.class_id,
        xp=0,
        streak=0,
        level=1,
    )
    db.add(new_student)
    await db.commit()

    # class_name-i tap
    class_name = None
    if body.class_id:
        cls_result = await db.execute(select(Class).where(Class.id == body.class_id))
        cls = cls_result.scalar_one_or_none()
        class_name = cls.name if cls else None

    return StudentOut(
        id=new_user.id, name=new_user.name, email=new_user.email,
        is_active=new_user.is_active, class_name=class_name,
        xp=0, level=1,
    )


@router.patch("/students/{user_id}/assign-class", response_model=StudentOut)
async def assign_student_class(
    user_id: str,
    body: AssignClassBody,
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdi sinfə yaz"""
    # User-i yoxla
    user_result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Şagird tapılmadı")

    # Student profilini tap
    stu_result = await db.execute(select(Student).where(Student.user_id == user_id))
    student = stu_result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Şagird profili tapılmadı")

    student.class_id = body.class_id
    await db.commit()

    # class_name-i tap
    class_name = None
    if body.class_id:
        cls_result = await db.execute(select(Class).where(Class.id == body.class_id))
        cls = cls_result.scalar_one_or_none()
        class_name = cls.name if cls else None

    return StudentOut(
        id=user.id, name=user.name, email=user.email,
        is_active=user.is_active, class_name=class_name,
        xp=student.xp, level=student.level,
    )


@router.get("/classes", response_model=list[ClassOut])
async def get_classes(
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Müəssisəyə bağlı bütün siniflər"""
    cls_result = await db.execute(
        select(Class, User)
        .join(User, User.id == Class.teacher_id, isouter=True)
        .where(Class.tenant_id == current_user.tenant_id)
        .order_by(Class.name)
    )
    rows = cls_result.all()

    out = []
    for cls, teacher in rows:
        stu_count_result = await db.execute(
            select(func.count(Student.id))
            .join(User, User.id == Student.user_id)
            .where(Student.class_id == cls.id, User.is_active == True)
        )
        stu_count = stu_count_result.scalar_one() or 0
        out.append(ClassOut(
            id=cls.id, name=cls.name, subject=cls.subject,
            teacher_name=teacher.name if teacher else "-",
            student_count=stu_count,
        ))
    return out


@router.post("/classes", response_model=ClassOut, status_code=201)
async def create_class(
    body: ClassCreate,
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Yeni sinif yarat"""
    # teacher_id-nin öz tenant-ında olduğunu yoxla
    teacher_result = await db.execute(
        select(User).where(User.id == body.teacher_id, User.tenant_id == current_user.tenant_id)
    )
    teacher = teacher_result.scalar_one_or_none()
    if not teacher:
        raise HTTPException(status_code=404, detail="Müəllim tapılmadı")

    new_class = Class(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        teacher_id=body.teacher_id,
        name=body.name,
        subject=body.subject,
    )
    db.add(new_class)
    await db.commit()

    return ClassOut(
        id=new_class.id, name=new_class.name, subject=new_class.subject,
        teacher_name=teacher.name, student_count=0,
    )


@router.patch("/classes/{class_id}", response_model=ClassOut)
async def update_class(
    class_id: str,
    body: ClassUpdate,
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Sinifi redaktə et"""
    cls_result = await db.execute(
        select(Class).where(Class.id == class_id, Class.tenant_id == current_user.tenant_id)
    )
    cls = cls_result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Sinif tapılmadı")

    if body.name is not None:
        cls.name = body.name
    if body.subject is not None:
        cls.subject = body.subject
    if body.teacher_id is not None:
        teacher_result = await db.execute(
            select(User).where(User.id == body.teacher_id, User.tenant_id == current_user.tenant_id)
        )
        teacher = teacher_result.scalar_one_or_none()
        if not teacher:
            raise HTTPException(status_code=404, detail="Müəllim tapılmadı")
        cls.teacher_id = body.teacher_id

    await db.commit()

    # teacher_name-i tap
    teacher_result2 = await db.execute(select(User).where(User.id == cls.teacher_id))
    teacher2 = teacher_result2.scalar_one_or_none()

    stu_count_result = await db.execute(
        select(func.count(Student.id))
        .join(User, User.id == Student.user_id)
        .where(Student.class_id == cls.id, User.is_active == True)
    )
    stu_count = stu_count_result.scalar_one() or 0

    return ClassOut(
        id=cls.id, name=cls.name, subject=cls.subject,
        teacher_name=teacher2.name if teacher2 else "-",
        student_count=stu_count,
    )


@router.delete("/classes/{class_id}", status_code=204)
async def delete_class(
    class_id: str,
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Sinifi sil"""
    cls_result = await db.execute(
        select(Class).where(Class.id == class_id, Class.tenant_id == current_user.tenant_id)
    )
    cls = cls_result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Sinif tapılmadı")

    # Sinifdəki şagirdlərin class_id-ni None et
    stu_result = await db.execute(select(Student).where(Student.class_id == class_id))
    students = stu_result.scalars().all()
    for stu in students:
        stu.class_id = None

    await db.delete(cls)
    await db.commit()


@router.get("/classes/{class_id}/students", response_model=list[ClassStudentOut])
async def get_class_students(
    class_id: str,
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Sinif şagirdlərini al"""
    # Sinifin öz tenant-ına aid olduğunu yoxla
    cls_result = await db.execute(
        select(Class).where(Class.id == class_id, Class.tenant_id == current_user.tenant_id)
    )
    if not cls_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Sinif tapılmadı")

    result = await db.execute(
        select(User, Student)
        .join(Student, Student.user_id == User.id)
        .where(Student.class_id == class_id, User.is_active == True)
        .order_by(User.name)
    )
    rows = result.all()
    return [
        ClassStudentOut(
            id=u.id, name=u.name, email=u.email,
            xp=stu.xp, level=stu.level,
        )
        for u, stu in rows
    ]


class BulkImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[str]


@router.post("/users/bulk-import", response_model=BulkImportResult)
async def bulk_import_users(
    file: UploadFile = File(...),
    role: str = Query(..., description="teacher or student"),
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """
    CSV və ya Excel faylı ilə toplu müəllim/şagird yaratma.

    CSV formatı (teacher): name, email, password
    CSV formatı (student): name, email, password, class_name (optional)

    Excel (.xlsx) eyni sütun adları ilə.
    """
    if role not in ("teacher", "student"):
        raise HTTPException(status_code=400, detail="Rol yalnız 'teacher' və ya 'student' ola bilər")

    content = await file.read()
    filename = (file.filename or "").lower()

    rows: list[dict] = []

    # ── CSV oxu ──────────────────────────────────────────────────────────
    if filename.endswith(".csv"):
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            rows.append({k.strip().lower(): (v or "").strip() for k, v in row.items()})

    # ── Excel oxu ─────────────────────────────────────────────────────────
    elif filename.endswith((".xlsx", ".xls")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        if ws is None:
            raise HTTPException(status_code=400, detail="Excel faylı boşdur")
        headers: list[str] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                headers = [str(c).strip().lower() if c else "" for c in row]
            else:
                rows.append({headers[j]: str(v).strip() if v is not None else "" for j, v in enumerate(row)})
        wb.close()
    else:
        raise HTTPException(status_code=400, detail="Yalnız .csv və ya .xlsx faylı qəbul edilir")

    created = 0
    skipped = 0
    errors: list[str] = []

    for i, row in enumerate(rows, start=2):
        name     = row.get("name", "").strip()
        email    = row.get("email", "").strip()
        password = row.get("password", "").strip()
        class_name = row.get("class_name", "").strip() or row.get("sinif", "").strip()

        # Boş sətirləri keç
        if not name and not email:
            skipped += 1
            continue

        if not name or not email or not password:
            errors.append(f"Sətir {i}: ad, email, şifrə mütləqdir")
            skipped += 1
            continue

        if len(password) < 6:
            errors.append(f"Sətir {i}: '{email}' — şifrə ən az 6 simvol olmalıdır")
            skipped += 1
            continue

        # Email unikallığı
        existing_res = await db.execute(select(User).where(User.email == email))
        if existing_res.scalar_one_or_none():
            errors.append(f"Sətir {i}: '{email}' artıq mövcuddur, buraxıldı")
            skipped += 1
            continue

        # User yarat
        new_user = User(
            id=str(uuid.uuid4()),
            tenant_id=current_user.tenant_id,
            name=name,
            email=email,
            hashed_password=hash_password(password),
            role=role,
            is_active=True,
        )
        db.add(new_user)
        await db.flush()

        # Şagird profili + sinif bağlantısı
        if role == "student":
            class_id = None
            if class_name:
                cls_res = await db.execute(
                    select(Class).where(
                        Class.tenant_id == current_user.tenant_id,
                        Class.name == class_name,
                    )
                )
                found_cls = cls_res.scalar_one_or_none()
                if found_cls:
                    class_id = found_cls.id
                else:
                    errors.append(f"Sətir {i}: '{email}' — '{class_name}' sinfi tapılmadı, sinif bağlanmadı")

            db.add(Student(
                id=str(uuid.uuid4()),
                user_id=new_user.id,
                class_id=class_id,
                xp=0, streak=0, level=1,
            ))

        created += 1

    await db.commit()
    return BulkImportResult(created=created, skipped=skipped, errors=errors)


# ══════════════════════════════════════════════════════════════════════════════
# 1. ANALİTİKA
# ══════════════════════════════════════════════════════════════════════════════

class TopStudent(BaseModel):
    name: str
    xp: int
    level: int
    class_name: Optional[str]


class ClassStat(BaseModel):
    class_name: str
    subject: str
    student_count: int
    avg_xp: float


class AnalyticsOut(BaseModel):
    total_exams: int
    total_exam_results: int
    avg_score: float
    top_students: List[TopStudent]
    class_stats: List[ClassStat]


@router.get("/analytics", response_model=AnalyticsOut)
async def get_analytics(
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Müəssisə analitika göstəriciləri"""
    tenant_id = current_user.tenant_id

    # total_exams — bu tenant-a aid siniflər üzərindəki imtahanlar
    exams_result = await db.execute(
        select(func.count(Exam.id))
        .join(Class, Class.id == Exam.class_id)
        .where(Class.tenant_id == tenant_id)
    )
    total_exams = exams_result.scalar_one() or 0

    # total_exam_results
    results_result = await db.execute(
        select(func.count(ExamResult.id))
        .join(Exam, Exam.id == ExamResult.exam_id)
        .join(Class, Class.id == Exam.class_id)
        .where(Class.tenant_id == tenant_id)
    )
    total_exam_results = results_result.scalar_one() or 0

    # avg_score
    avg_result = await db.execute(
        select(func.avg(ExamResult.percentage))
        .join(Exam, Exam.id == ExamResult.exam_id)
        .join(Class, Class.id == Exam.class_id)
        .where(Class.tenant_id == tenant_id)
    )
    avg_score = round(float(avg_result.scalar_one() or 0.0), 2)

    # top 5 şagird XP üzrə
    top_result = await db.execute(
        select(User, Student, Class)
        .join(Student, Student.user_id == User.id)
        .join(Class, Class.id == Student.class_id, isouter=True)
        .where(User.tenant_id == tenant_id, User.role == "student")
        .order_by(Student.xp.desc())
        .limit(5)
    )
    top_rows = top_result.all()
    top_students = [
        TopStudent(
            name=u.name,
            xp=stu.xp,
            level=stu.level,
            class_name=cls.name if cls else None,
        )
        for u, stu, cls in top_rows
    ]

    # sinif statistikası
    classes_result = await db.execute(
        select(Class).where(Class.tenant_id == tenant_id).order_by(Class.name)
    )
    classes = classes_result.scalars().all()

    class_stats: List[ClassStat] = []
    for cls in classes:
        stu_res = await db.execute(
            select(Student)
            .join(User, User.id == Student.user_id)
            .where(Student.class_id == cls.id, User.is_active == True)
        )
        stus = stu_res.scalars().all()
        count = len(stus)
        avg_xp = round(sum(s.xp for s in stus) / count, 2) if count else 0.0
        class_stats.append(ClassStat(
            class_name=cls.name,
            subject=cls.subject,
            student_count=count,
            avg_xp=avg_xp,
        ))

    return AnalyticsOut(
        total_exams=total_exams,
        total_exam_results=total_exam_results,
        avg_score=avg_score,
        top_students=top_students,
        class_stats=class_stats,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. VALİDEYN İDARƏETMƏSİ
# ══════════════════════════════════════════════════════════════════════════════

class ParentOut(BaseModel):
    id: str
    name: str
    email: str
    is_active: bool
    linked_student_name: Optional[str]


class ParentCreate(BaseModel):
    name: str
    email: str
    password: str
    student_id: Optional[str] = None


class LinkStudentBody(BaseModel):
    student_id: Optional[str] = None


@router.get("/parents", response_model=List[ParentOut])
async def get_parents(
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Müəssisəyə bağlı bütün valideynlər"""
    result = await db.execute(
        select(User)
        .where(User.tenant_id == current_user.tenant_id, User.role == "parent")
        .order_by(User.name)
    )
    parents = result.scalars().all()

    out: List[ParentOut] = []
    for p in parents:
        # Bu valideynin student_id-si Student.parent_id sahəsindən gəlir
        stu_res = await db.execute(
            select(User.name)
            .join(Student, Student.user_id == User.id)
            .where(Student.parent_id == p.id)
        )
        student_name = stu_res.scalar_one_or_none()
        out.append(ParentOut(
            id=p.id, name=p.name, email=p.email,
            is_active=p.is_active,
            linked_student_name=student_name,
        ))
    return out


@router.post("/parents", response_model=ParentOut, status_code=201)
async def create_parent(
    body: ParentCreate,
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Yeni valideyn yarat"""
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Bu e-poçt artıq istifadə olunur")

    new_user = User(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        name=body.name,
        email=body.email,
        hashed_password=hash_password(body.password),
        role="parent",
        is_active=True,
    )
    db.add(new_user)
    await db.flush()

    linked_student_name: Optional[str] = None
    if body.student_id:
        stu_res = await db.execute(
            select(Student)
            .join(User, User.id == Student.user_id)
            .where(Student.user_id == body.student_id, User.tenant_id == current_user.tenant_id)
        )
        stu = stu_res.scalar_one_or_none()
        if stu:
            stu.parent_id = new_user.id
            # get student name
            usr_res = await db.execute(select(User).where(User.id == body.student_id))
            usr = usr_res.scalar_one_or_none()
            linked_student_name = usr.name if usr else None

    await db.commit()

    return ParentOut(
        id=new_user.id, name=new_user.name, email=new_user.email,
        is_active=new_user.is_active,
        linked_student_name=linked_student_name,
    )


@router.patch("/parents/{parent_id}/link-student", response_model=ParentOut)
async def link_student_to_parent(
    parent_id: str,
    body: LinkStudentBody,
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Valideynə şagird bağla (və ya bağı aç)"""
    parent_res = await db.execute(
        select(User).where(User.id == parent_id, User.tenant_id == current_user.tenant_id)
    )
    parent = parent_res.scalar_one_or_none()
    if not parent:
        raise HTTPException(status_code=404, detail="Valideyn tapılmadı")

    # Əvvəlki bağlantını sil
    old_stu_res = await db.execute(select(Student).where(Student.parent_id == parent_id))
    for old_stu in old_stu_res.scalars().all():
        old_stu.parent_id = None

    linked_student_name: Optional[str] = None
    if body.student_id:
        stu_res = await db.execute(
            select(Student)
            .join(User, User.id == Student.user_id)
            .where(Student.user_id == body.student_id, User.tenant_id == current_user.tenant_id)
        )
        stu = stu_res.scalar_one_or_none()
        if stu:
            stu.parent_id = parent_id
            usr_res = await db.execute(select(User).where(User.id == body.student_id))
            usr = usr_res.scalar_one_or_none()
            linked_student_name = usr.name if usr else None

    await db.commit()
    return ParentOut(
        id=parent.id, name=parent.name, email=parent.email,
        is_active=parent.is_active,
        linked_student_name=linked_student_name,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 3. BİLDİRİŞ & ELAN
# ══════════════════════════════════════════════════════════════════════════════

_ANNOUNCEMENTS_FILE = os.path.join(os.path.dirname(__file__), "..", "announcements_data.json")


def _load_announcements() -> list:
    if not os.path.exists(_ANNOUNCEMENTS_FILE):
        return []
    with open(_ANNOUNCEMENTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_announcements(data: list) -> None:
    with open(_ANNOUNCEMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class AnnouncementCreate(BaseModel):
    title: str
    message: str
    target: str  # "all" | "teachers" | "students"


class AnnouncementOut(BaseModel):
    id: str
    tenant_id: str
    title: str
    message: str
    target: str
    created_at: str


@router.get("/announcements", response_model=List[AnnouncementOut])
async def get_announcements(
    current_user: User = Depends(require_corporate),
):
    """Bu tenant-ın elanlarını gətir"""
    all_data = _load_announcements()
    return [a for a in all_data if a["tenant_id"] == current_user.tenant_id]


@router.post("/announcements", response_model=AnnouncementOut, status_code=201)
async def create_announcement(
    body: AnnouncementCreate,
    current_user: User = Depends(require_corporate),
):
    """Yeni elan yarat"""
    all_data = _load_announcements()
    new_ann = {
        "id": str(uuid.uuid4()),
        "tenant_id": current_user.tenant_id,
        "title": body.title,
        "message": body.message,
        "target": body.target,
        "created_at": datetime.utcnow().isoformat(),
    }
    all_data.append(new_ann)
    _save_announcements(all_data)
    return AnnouncementOut(**new_ann)


@router.delete("/announcements/{ann_id}", status_code=204)
async def delete_announcement(
    ann_id: str,
    current_user: User = Depends(require_corporate),
):
    """Elanı sil"""
    all_data = _load_announcements()
    new_data = [
        a for a in all_data
        if not (a["id"] == ann_id and a["tenant_id"] == current_user.tenant_id)
    ]
    if len(new_data) == len(all_data):
        raise HTTPException(status_code=404, detail="Elan tapılmadı")
    _save_announcements(new_data)


# ══════════════════════════════════════════════════════════════════════════════
# 4. DAVAMİYYƏT
# ══════════════════════════════════════════════════════════════════════════════

_ATTENDANCE_FILE = os.path.join(os.path.dirname(__file__), "..", "attendance_data.json")


def _load_attendance() -> dict:
    if not os.path.exists(_ATTENDANCE_FILE):
        return {}
    with open(_ATTENDANCE_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_attendance(data: dict) -> None:
    with open(_ATTENDANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class AttendanceRecord(BaseModel):
    student_id: str
    present: bool


class AttendanceSave(BaseModel):
    class_id: str
    date: str  # YYYY-MM-DD
    records: List[AttendanceRecord]


class AttendanceStudentOut(BaseModel):
    student_id: str
    student_name: str
    present: bool


@router.get("/attendance", response_model=List[AttendanceStudentOut])
async def get_attendance(
    class_id: str = Query(...),
    date: str = Query(...),
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Sinif+tarix üzrə davamiyyəti gətir"""
    # Sinifin bu tenant-a aid olduğunu yoxla
    cls_res = await db.execute(
        select(Class).where(Class.id == class_id, Class.tenant_id == current_user.tenant_id)
    )
    if not cls_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Sinif tapılmadı")

    # Şagirdlər siyahısını al
    stu_res = await db.execute(
        select(User, Student)
        .join(Student, Student.user_id == User.id)
        .where(Student.class_id == class_id, User.is_active == True)
        .order_by(User.name)
    )
    rows = stu_res.all()

    att_data = _load_attendance()
    key = f"{current_user.tenant_id}_{class_id}_{date}"
    saved: dict = att_data.get(key, {})

    return [
        AttendanceStudentOut(
            student_id=u.id,
            student_name=u.name,
            present=saved.get(u.id, True),
        )
        for u, _stu in rows
    ]


@router.post("/attendance", status_code=204)
async def save_attendance(
    body: AttendanceSave,
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Davamiyyət məlumatlarını saxla"""
    cls_res = await db.execute(
        select(Class).where(Class.id == body.class_id, Class.tenant_id == current_user.tenant_id)
    )
    if not cls_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Sinif tapılmadı")

    att_data = _load_attendance()
    key = f"{current_user.tenant_id}_{body.class_id}_{body.date}"
    att_data[key] = {r.student_id: r.present for r in body.records}
    _save_attendance(att_data)


# ══════════════════════════════════════════════════════════════════════════════
# 5. ÖDƏNİŞ İZLƏMƏ
# ══════════════════════════════════════════════════════════════════════════════

_PAYMENTS_FILE = os.path.join(os.path.dirname(__file__), "..", "corp_payments_data.json")


def _load_payments() -> list:
    if not os.path.exists(_PAYMENTS_FILE):
        return []
    with open(_PAYMENTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_payments(data: list) -> None:
    with open(_PAYMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class PaymentCreate(BaseModel):
    student_id: str
    student_name: str
    amount: float
    description: str
    month: str  # e.g. "2024-01"
    status: str  # "paid" | "pending"


class PaymentStatusUpdate(BaseModel):
    status: str  # "paid" | "pending"


class PaymentOut(BaseModel):
    id: str
    tenant_id: str
    student_id: str
    student_name: str
    amount: float
    description: str
    month: str
    status: str
    created_at: str


@router.get("/payments", response_model=List[PaymentOut])
async def get_payments(
    student_id: Optional[str] = Query(None),
    current_user: User = Depends(require_corporate),
):
    """Ödənişlər siyahısı (isteğe bağlı şagird filteri)"""
    all_data = _load_payments()
    filtered = [p for p in all_data if p["tenant_id"] == current_user.tenant_id]
    if student_id:
        filtered = [p for p in filtered if p["student_id"] == student_id]
    return filtered


@router.post("/payments", response_model=PaymentOut, status_code=201)
async def create_payment(
    body: PaymentCreate,
    current_user: User = Depends(require_corporate),
):
    """Yeni ödəniş əlavə et"""
    all_data = _load_payments()
    new_pay = {
        "id": str(uuid.uuid4()),
        "tenant_id": current_user.tenant_id,
        "student_id": body.student_id,
        "student_name": body.student_name,
        "amount": body.amount,
        "description": body.description,
        "month": body.month,
        "status": body.status,
        "created_at": datetime.utcnow().isoformat(),
    }
    all_data.append(new_pay)
    _save_payments(all_data)
    return PaymentOut(**new_pay)


@router.patch("/payments/{payment_id}", response_model=PaymentOut)
async def update_payment_status(
    payment_id: str,
    body: PaymentStatusUpdate,
    current_user: User = Depends(require_corporate),
):
    """Ödəniş statusunu dəyişdir"""
    all_data = _load_payments()
    for pay in all_data:
        if pay["id"] == payment_id and pay["tenant_id"] == current_user.tenant_id:
            pay["status"] = body.status
            _save_payments(all_data)
            return PaymentOut(**pay)
    raise HTTPException(status_code=404, detail="Ödəniş tapılmadı")


@router.delete("/payments/{payment_id}", status_code=204)
async def delete_payment(
    payment_id: str,
    current_user: User = Depends(require_corporate),
):
    """Ödənişi sil"""
    all_data = _load_payments()
    new_data = [
        p for p in all_data
        if not (p["id"] == payment_id and p["tenant_id"] == current_user.tenant_id)
    ]
    if len(new_data) == len(all_data):
        raise HTTPException(status_code=404, detail="Ödəniş tapılmadı")
    _save_payments(new_data)


# ══════════════════════════════════════════════════════════════════════════════
# 6. PROFİL YENİLƏMƏ
# ══════════════════════════════════════════════════════════════════════════════

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None  # base64 data-URL


@router.get("/profile")
async def get_corporate_profile(
    current_user: User = Depends(require_corporate),
):
    """Korporativ admin profil məlumatları"""
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
        "avatar_url": current_user.avatar_url,
    }


@router.post("/avatar")
async def upload_corporate_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Avatar şəklini yükləyib base64 data-URL kimi saxla."""
    import base64
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Yalnız şəkil faylı qəbul edilir")
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Şəkil 2 MB-dan böyük ola bilməz")
    b64 = base64.b64encode(data).decode()
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="İstifadəçi tapılmadı")
    user.avatar_url = f"data:{file.content_type};base64,{b64}"
    await db.commit()
    return {"avatar_url": user.avatar_url}


@router.delete("/avatar")
async def delete_corporate_avatar(
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Avatarı sil."""
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="İstifadəçi tapılmadı")
    user.avatar_url = None
    await db.commit()
    return {"ok": True}


@router.patch("/profile")
async def update_corporate_profile(
    body: ProfileUpdate,
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Korporativ admin adını və/və ya avatarını yenilə"""
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="İstifadəçi tapılmadı")
    if body.name:
        user.name = body.name.strip()
    if body.avatar is not None:
        user.avatar_url = body.avatar
    await db.commit()
    return {"ok": True, "name": user.name}


# ══════════════════════════════════════════════════════════════════════════════
# 7. ANALİTİKA İXRACI (CSV)
# ══════════════════════════════════════════════════════════════════════════════

import csv as _csv
import io as _io
from fastapi.responses import StreamingResponse


@router.get("/analytics/export")
async def export_analytics_csv(
    current_user: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Sinif statistikasını CSV formatında ixrac et"""
    tenant_id = current_user.tenant_id

    classes_result = await db.execute(
        select(Class).where(Class.tenant_id == tenant_id).order_by(Class.name)
    )
    classes = classes_result.scalars().all()

    rows = []
    for cls in classes:
        stu_res = await db.execute(
            select(Student)
            .join(User, User.id == Student.user_id)
            .where(Student.class_id == cls.id, User.is_active == True)
        )
        stus = stu_res.scalars().all()
        count = len(stus)
        avg_xp = round(sum(s.xp for s in stus) / count, 2) if count else 0.0

        # Teacher name
        teacher_res = await db.execute(select(User).where(User.id == cls.teacher_id))
        teacher = teacher_res.scalar_one_or_none()

        rows.append({
            "Sinif": cls.name,
            "Fan": cls.subject,
            "Muellim": teacher.name if teacher else "-",
            "Sagird sayi": count,
            "Ortalama XP": avg_xp,
        })

    # Top students
    top_result = await db.execute(
        select(User, Student, Class)
        .join(Student, Student.user_id == User.id)
        .join(Class, Class.id == Student.class_id, isouter=True)
        .where(User.tenant_id == tenant_id, User.role == "student")
        .order_by(Student.xp.desc())
        .limit(20)
    )

    output = _io.StringIO()
    writer = _csv.writer(output)

    # Section 1: Class stats
    writer.writerow(["=== SINIF STATİSTİKASI ==="])
    writer.writerow(["Sinif", "Fan", "Muellim", "Sagird sayi", "Ortalama XP"])
    for r in rows:
        writer.writerow([r["Sinif"], r["Fan"], r["Muellim"], r["Sagird sayi"], r["Ortalama XP"]])

    writer.writerow([])
    writer.writerow(["=== TOP SAGIRDLER ==="])
    writer.writerow(["Ad", "XP", "Seviye", "Sinif"])
    for user, stu, cls in top_result.all():
        writer.writerow([user.name, stu.xp, stu.level, cls.name if cls else "-"])

    output.seek(0)
    bom = u"﻿"
    content = bom + output.getvalue()

    from fastapi.responses import Response
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=analitika.csv"},
    )


# ── Branding ───────────────────────────────────────────────────────────────────

class BrandingPatch(BaseModel):
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None   # hex e.g. "#2196f3"


@router.get("/branding")
async def get_branding(
    actor: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Corporate admin öz müəssisəsinin branding-ini oxusun."""
    result = await db.execute(select(Tenant).where(Tenant.id == actor.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")
    return {
        "logo_url": tenant.logo_url,
        "primary_color": tenant.primary_color,
    }


@router.patch("/branding")
async def patch_branding(
    body: BrandingPatch,
    actor: User = Depends(require_corporate),
    db: AsyncSession = Depends(get_db),
):
    """Corporate admin öz müəssisəsinin loqo və rəngini dəyişsin."""
    result = await db.execute(select(Tenant).where(Tenant.id == actor.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")
    if body.logo_url is not None:
        tenant.logo_url = body.logo_url or None
    if body.primary_color is not None:
        import re as _re
        if body.primary_color and not _re.match(r'^#[0-9a-fA-F]{3,6}$', body.primary_color):
            raise HTTPException(status_code=400, detail="Rəng hex formatında olmalıdır: #RRGGBB")
        tenant.primary_color = body.primary_color or None
    await db.commit()
    return {
        "logo_url": tenant.logo_url,
        "primary_color": tenant.primary_color,
    }


@router.post("/branding/logo")
async def upload_branding_logo(
    file: UploadFile = File(...),
    actor: User = Depends(require_corporate),
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
    result = await db.execute(select(Tenant).where(Tenant.id == actor.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant tapılmadı")
    tenant.logo_url = logo_url
    await db.commit()
    return {"logo_url": logo_url}
