"""
Parent Router
-------------
/parent/* — valideyn dashboard-u üçün API endpoint-lər
"""

import json
import os
import uuid as uuid_mod
from datetime import datetime as dt_cls

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.dependencies import require_role
from app.models.user import User
from app.models.student import Student
from app.models.class_model import Class
from app.models.exam import ExamResult, Exam

router = APIRouter(prefix="/parent", tags=["Parent"])
require_parent = require_role("parent", "admin", "superadmin")


# ── Schemas ────────────────────────────────────────────────────────────────

class ChildInfo(BaseModel):
    id: str
    name: str
    email: str
    class_name: Optional[str]
    class_subject: Optional[str]
    xp: int
    streak: int
    level: int
    exam_count: int
    avg_score: Optional[float]


class ParentDashboard(BaseModel):
    parent_name: str
    tenant_name: str
    children: list[ChildInfo]


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=ParentDashboard)
async def get_parent_dashboard(
    current_user: User = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
):
    """Valideyn dashboard-u — uşaqların məlumatları"""

    # Find children: students where parent_id == current_user.id
    children_result = await db.execute(
        select(Student, User)
        .join(User, User.id == Student.user_id)
        .where(Student.parent_id == current_user.id)
    )
    rows = children_result.all()

    children_out = []
    for stu, child_user in rows:
        # Class info
        class_name = None
        class_subject = None
        if stu.class_id:
            cls_result = await db.execute(
                select(Class).where(Class.id == stu.class_id)
            )
            cls = cls_result.scalar_one_or_none()
            if cls:
                class_name = cls.name
                class_subject = cls.subject

        # Exam results
        results_result = await db.execute(
            select(ExamResult)
            .where(ExamResult.student_id == stu.id)
        )
        results = results_result.scalars().all()
        exam_count = len(results)
        avg_score = None
        if results:
            avg_score = round(sum(r.percentage for r in results) / len(results), 1)

        children_out.append(ChildInfo(
            id=child_user.id,
            name=child_user.name,
            email=child_user.email,
            class_name=class_name,
            class_subject=class_subject,
            xp=stu.xp,
            streak=stu.streak,
            level=stu.level,
            exam_count=exam_count,
            avg_score=avg_score,
        ))

    # Tenant name
    from app.models.tenant import Tenant
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id)
    )
    tenant = tenant_result.scalar_one_or_none()
    tenant_name = tenant.name if tenant else ""

    return ParentDashboard(
        parent_name=current_user.name,
        tenant_name=tenant_name,
        children=children_out,
    )


class RecentExamOut(BaseModel):
    exam_title: str
    subject: str
    percentage: float
    submitted_at: str


class ChildDetailOut(BaseModel):
    id: str
    name: str
    email: str
    class_name: Optional[str]
    class_subject: Optional[str]
    xp: int
    streak: int
    level: int
    exam_count: int
    avg_score: Optional[float]
    recent_exams: list[RecentExamOut]


@router.get("/children", response_model=list[ChildDetailOut])
async def get_parent_children(
    current_user: User = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
):
    children_result = await db.execute(
        select(Student, User)
        .join(User, User.id == Student.user_id)
        .where(Student.parent_id == current_user.id)
    )
    rows = children_result.all()

    out = []
    for stu, child_user in rows:
        class_name = None
        class_subject = None
        if stu.class_id:
            cls_res = await db.execute(select(Class).where(Class.id == stu.class_id))
            cls = cls_res.scalar_one_or_none()
            if cls:
                class_name = cls.name
                class_subject = cls.subject

        results_res = await db.execute(
            select(ExamResult, Exam)
            .join(Exam, Exam.id == ExamResult.exam_id)
            .where(ExamResult.student_id == stu.id)
            .order_by(ExamResult.submitted_at.desc())
            .limit(5)
        )
        result_rows = results_res.all()
        exam_count = len(result_rows)
        avg_score = round(sum(r.percentage for r, _ in result_rows) / exam_count, 1) if exam_count else None

        recent_exams = [
            RecentExamOut(
                exam_title=e.title,
                subject=e.subject,
                percentage=r.percentage,
                submitted_at=r.submitted_at.strftime("%d.%m.%Y") if r.submitted_at else "",
            )
            for r, e in result_rows
        ]

        out.append(ChildDetailOut(
            id=child_user.id,
            name=child_user.name,
            email=child_user.email,
            class_name=class_name,
            class_subject=class_subject,
            xp=stu.xp,
            streak=stu.streak,
            level=stu.level,
            exam_count=exam_count,
            avg_score=avg_score,
            recent_exams=recent_exams,
        ))
    return out


class ChildHomeworkOut(BaseModel):
    id: str
    title: str
    description: Optional[str]
    deadline: str
    is_active: bool
    class_name: str
    submitted: bool


@router.get("/children/{child_id}/homework", response_model=list[ChildHomeworkOut])
async def get_child_homework(
    child_id: str,
    current_user: User = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException
    from app.models.homework import Homework, HomeworkSubmission

    # Verify this child belongs to this parent
    stu_res = await db.execute(
        select(Student)
        .join(User, User.id == Student.user_id)
        .where(User.id == child_id, Student.parent_id == current_user.id)
    )
    stu = stu_res.scalar_one_or_none()
    if not stu:
        raise HTTPException(403, "Not your child")

    if not stu.class_id:
        return []

    cls_res = await db.execute(select(Class).where(Class.id == stu.class_id))
    cls = cls_res.scalar_one_or_none()

    hw_res = await db.execute(
        select(Homework)
        .where(Homework.class_id == stu.class_id)
        .order_by(Homework.created_at.desc())
    )
    homeworks = hw_res.scalars().all()

    result = []
    for hw in homeworks:
        sub_res = await db.execute(
            select(HomeworkSubmission).where(
                HomeworkSubmission.homework_id == hw.id,
                HomeworkSubmission.student_id == stu.id
            )
        )
        submitted = sub_res.scalar_one_or_none() is not None
        result.append(ChildHomeworkOut(
            id=hw.id, title=hw.title, description=hw.description,
            deadline=hw.deadline.isoformat() if hw.deadline else "",
            is_active=hw.is_active,
            class_name=cls.name if cls else "",
            submitted=submitted,
        ))
    return result


class ProfileUpdate(BaseModel):
    name: Optional[str] = None


class ProfileOut(BaseModel):
    id: str
    name: str
    email: str
    role: str
    avatar_url: Optional[str] = None


@router.patch("/profile", response_model=ProfileOut)
async def update_parent_profile(
    body: ProfileUpdate,
    current_user: User = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
):
    if body.name:
        current_user.name = body.name
        await db.commit()
        await db.refresh(current_user)
    return ProfileOut(id=current_user.id, name=current_user.name, email=current_user.email,
                      role=current_user.role, avatar_url=current_user.avatar_url)


@router.post("/avatar", response_model=ProfileOut)
async def upload_parent_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
):
    import base64
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Yalnız şəkil faylı qəbul edilir")
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Şəkil 2 MB-dan böyük ola bilməz")
    b64 = base64.b64encode(data).decode()
    current_user.avatar_url = f"data:{file.content_type};base64,{b64}"
    await db.commit()
    await db.refresh(current_user)
    return ProfileOut(id=current_user.id, name=current_user.name, email=current_user.email,
                      role=current_user.role, avatar_url=current_user.avatar_url)


@router.get("/attendance")
async def get_parent_attendance(
    current_user: User = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
):
    """Valideynin övladlarının davamiyyətini attendance_data.json-dan qaytar."""
    import json as _json

    # attendance_data.json-u yüklə — müəllim tərəfindən yazılır
    att_file = os.path.join(os.path.dirname(__file__), "..", "attendance_data.json")
    try:
        if os.path.exists(att_file):
            with open(att_file, "r", encoding="utf-8") as f:
                att_data: dict = _json.load(f)
        else:
            att_data = {}
    except Exception:
        att_data = {}

    # Valideynin övladlarını tap
    stu_result = await db.execute(
        select(Student, User, Class)
        .join(User, User.id == Student.user_id)
        .outerjoin(Class, Class.id == Student.class_id)
        .where(Student.parent_id == current_user.id)
    )
    rows = stu_result.all()

    # Tenant ID — açar prefiksi üçün lazımdır
    ten_res = await db.execute(select(User).where(User.id == current_user.id))
    me = ten_res.scalar_one_or_none()
    tenant_id = me.tenant_id if me else ""

    children = []
    for stu, user, cls in rows:
        if not cls:
            # Sinifi yoxdur — davamiyyət məlumatı yoxdur
            children.append({
                "student_id": user.id,
                "student_name": user.name,
                "class_name": "—",
                "total_days": 0,
                "present_days": 0,
                "absent_days": 0,
                "late_days": 0,
                "attendance_rate": 0.0,
            })
            continue

        # Bu şagirdə aid bütün qeydləri tap
        prefix = f"{tenant_id}_{cls.id}_"
        present_days = 0
        absent_days = 0
        late_days = 0
        total_days = 0

        for key, records in att_data.items():
            if not key.startswith(prefix):
                continue
            if user.id not in records:
                continue
            total_days += 1
            v = records.get(user.id)
            # Köhnə bool + yeni string formatı
            if v is True or v == "present":
                present_days += 1
            elif v == "late":
                late_days += 1
            else:
                absent_days += 1

        # Gecikmə tam iştirak sayılır — faizə təsir etmir
        rate = round((present_days + late_days) / total_days * 100, 1) if total_days > 0 else 0.0

        children.append({
            "student_id": user.id,
            "student_name": user.name,
            "class_name": cls.name,
            "total_days": total_days,
            "present_days": present_days,
            "absent_days": absent_days,
            "late_days": late_days,
            "attendance_rate": rate,
        })

    return children


# ── Meetings & Payments ─────────────────────────────────────────────────────

MEETINGS_FILE = os.path.join(os.path.dirname(__file__), "..", "meetings_data.json")
PAYMENTS_FILE = os.path.join(os.path.dirname(__file__), "..", "payments_data.json")


class TeacherOut(BaseModel):
    id: str
    name: str
    subject: str
    type: str   # "Sinif müəllimi" | "Repetitor"


@router.get("/children/{child_id}/teachers", response_model=list[TeacherOut])
async def get_child_teachers(
    child_id: str,
    current_user: User = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
):
    """Övladın bütün müəllimləri — sinif müəllimi + repetitorlar."""
    from app.models.repetitor import RepetitorStudent

    # Övladın bu valideynə aid olduğunu yoxla
    stu_res = await db.execute(
        select(Student).where(Student.user_id == child_id, Student.parent_id == current_user.id)
    )
    student = stu_res.scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Övlad tapılmadı")

    teachers: list[TeacherOut] = []
    seen: set[str] = set()

    # 1) Sinif müəllimi
    if student.class_id:
        cls_res = await db.execute(
            select(Class, User)
            .join(User, User.id == Class.teacher_id)
            .where(Class.id == student.class_id)
        )
        row = cls_res.first()
        if row:
            cls, teacher = row
            if teacher.id not in seen:
                seen.add(teacher.id)
                teachers.append(TeacherOut(
                    id=teacher.id, name=teacher.name,
                    subject=cls.subject or "Fənn məlumatı yoxdur",
                    type="Sinif müəllimi",
                ))

    # 2) Repetitor müəllimlər
    rep_res = await db.execute(
        select(RepetitorStudent, User)
        .join(User, User.id == RepetitorStudent.teacher_id)
        .where(RepetitorStudent.user_id == child_id)
    )
    for rep_stu, teacher in rep_res.all():
        if teacher.id not in seen:
            seen.add(teacher.id)
            teachers.append(TeacherOut(
                id=teacher.id, name=teacher.name,
                subject=rep_stu.subject or "Ümumi",
                type="Repetitor",
            ))

    return teachers


def _load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass


class MeetingCreate(BaseModel):
    child_name: str
    teacher_id: Optional[str] = None
    teacher_name: Optional[str] = None
    subject: str
    preferred_date: str
    note: Optional[str] = None


class MeetingOut(BaseModel):
    id: str
    child_name: str
    teacher_name: Optional[str] = None
    subject: str
    preferred_date: str
    note: Optional[str] = None
    status: str   # "pending" | "confirmed" | "cancelled"
    created_at: str
    source: str = "parent"   # "parent" | "teacher"
    # Canlı görüş
    join_state: str = "not_confirmed"   # not_confirmed|too_early|open|ended
    can_join: bool = False
    starts_in_minutes: Optional[int] = None
    room_url: Optional[str] = None


@router.post("/meetings", response_model=MeetingOut, status_code=201)
async def request_meeting(
    body: MeetingCreate,
    current_user: User = Depends(require_parent),
):
    meetings = _load_json(MEETINGS_FILE, {})
    uid = str(uuid_mod.uuid4())
    meeting = {
        "id": uid,
        "parent_id": current_user.id,
        "teacher_id": body.teacher_id,
        "child_name": body.child_name,
        "teacher_name": body.teacher_name,
        "subject": body.subject,
        "preferred_date": body.preferred_date,
        "note": body.note,
        "status": "pending",
        "created_at": dt_cls.utcnow().isoformat(),
    }
    meetings[uid] = meeting
    _save_json(MEETINGS_FILE, meetings)
    return MeetingOut(**{k: v for k, v in meeting.items() if k != "parent_id"})


@router.get("/meetings", response_model=list[MeetingOut])
async def get_meetings(
    current_user: User = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
):
    from app.models.repetitor import RepetitorStudent, RepetitorMeeting

    result: list[MeetingOut] = []

    from app.services.meeting_room import join_info

    # 1) Valideynin özü yaratdığı görüşlər (meetings_data.json)
    meetings = _load_json(MEETINGS_FILE, {})
    for m in meetings.values():
        if m.get("parent_id") == current_user.id:
            ji = join_info(m["id"], m.get("preferred_date", ""), m.get("status", "pending"))
            result.append(MeetingOut(
                id=m["id"],
                child_name=m.get("child_name", ""),
                teacher_name=m.get("teacher_name"),
                subject=m.get("subject", ""),
                preferred_date=m.get("preferred_date", ""),
                note=m.get("note"),
                status=m.get("status", "pending"),
                created_at=m.get("created_at", ""),
                source="parent",
                **ji,
            ))

    # 2) Repetitor müəllimin təyin etdiyi görüşlər (repetitor_meetings cədvəli)
    # Valideynin övladlarını tap → onlara aid RepetitorStudent-ləri tap
    stu_res = await db.execute(
        select(Student).where(Student.parent_id == current_user.id)
    )
    students = stu_res.scalars().all()
    child_user_ids = [s.user_id for s in students if s.user_id]

    if child_user_ids:
        rep_stu_res = await db.execute(
            select(RepetitorStudent, User)
            .join(User, User.id == RepetitorStudent.teacher_id)
            .where(RepetitorStudent.user_id.in_(child_user_ids))
        )
        rep_students = rep_stu_res.all()  # (RepetitorStudent, teacher_User)

        for rep_stu, teacher in rep_students:
            # Bu repetitor şagirdinə aid görüşlər
            mtg_res = await db.execute(
                select(RepetitorMeeting)
                .where(RepetitorMeeting.student_id == rep_stu.id)
                .order_by(RepetitorMeeting.meeting_date.desc())
            )
            for mtg in mtg_res.scalars().all():
                mstatus = {"planned": "pending", "done": "confirmed", "cancelled": "cancelled"}.get(mtg.status, "pending")
                # Repetitor görüşləri müəllim tərəfindən yaradılıb — valideyn üçün
                # təsdiqlənmiş sayılır (planned = aktiv), beləliklə qoşula bilir
                join_status = "confirmed" if mtg.status == "planned" else mstatus
                ji = join_info(mtg.id, mtg.meeting_date, join_status)
                result.append(MeetingOut(
                    id=mtg.id,
                    child_name=rep_stu.name,
                    teacher_name=teacher.name,
                    subject=mtg.title,
                    preferred_date=mtg.meeting_date,
                    note=mtg.note,
                    status=mstatus,
                    created_at=mtg.created_at.isoformat() if mtg.created_at else "",
                    source="teacher",
                    **ji,
                ))

    # Tarixə görə azalan sırala
    result.sort(key=lambda x: x.created_at, reverse=True)
    return result


@router.delete("/meetings/{meeting_id}", status_code=204)
async def delete_meeting(
    meeting_id: str,
    current_user: User = Depends(require_parent),
):
    """Valideyn öz görüş tələbini silir."""
    meetings = _load_json(MEETINGS_FILE, {})
    m = meetings.get(meeting_id)
    if not m:
        raise HTTPException(404, "Görüş tapılmadı")
    if m.get("parent_id") != current_user.id:
        raise HTTPException(403, "Bu görüşü silmək icazəniz yoxdur")
    del meetings[meeting_id]
    _save_json(MEETINGS_FILE, meetings)


class PaymentCreate(BaseModel):
    amount: float
    card_last4: str   # last 4 digits only — never store full card


class PaymentOut(BaseModel):
    id: str
    amount: float
    card_last4: str
    status: str   # "success"
    created_at: str


@router.post("/payments", response_model=PaymentOut, status_code=201)
async def create_payment(
    body: PaymentCreate,
    current_user: User = Depends(require_parent),
):
    payments = _load_json(PAYMENTS_FILE, {})
    uid = str(uuid_mod.uuid4())
    payment = {
        "id": uid,
        "parent_id": current_user.id,
        "amount": body.amount,
        "card_last4": body.card_last4[-4:],
        "status": "success",
        "created_at": dt_cls.utcnow().isoformat(),
    }
    payments[uid] = payment
    _save_json(PAYMENTS_FILE, payments)
    return PaymentOut(**{k: v for k, v in payment.items() if k != "parent_id"})


@router.get("/payments", response_model=list[PaymentOut])
async def get_payments(
    current_user: User = Depends(require_parent),
):
    payments = _load_json(PAYMENTS_FILE, {})
    return [
        PaymentOut(**{k: v for k, v in p.items() if k != "parent_id"})
        for p in payments.values()
        if p.get("parent_id") == current_user.id
    ]


# ══════════════════════════════════════════════════════════════════════════════
# ELANLAR
# ══════════════════════════════════════════════════════════════════════════════

_ANNOUNCEMENTS_FILE_P = os.path.join(os.path.dirname(__file__), "..", "announcements_data.json")


class ParentAnnouncementOut(BaseModel):
    id: str
    title: str
    message: str
    target: str
    created_at: str


@router.get("/announcements", response_model=list[ParentAnnouncementOut])
async def get_parent_announcements(
    current_user: User = Depends(require_parent),
):
    """Valideynin müəssisəsinə aid elanlar"""
    if not os.path.exists(_ANNOUNCEMENTS_FILE_P):
        return []
    with open(_ANNOUNCEMENTS_FILE_P, encoding="utf-8") as f:
        all_data = json.load(f)
    return [
        ParentAnnouncementOut(
            id=a["id"], title=a["title"], message=a["message"],
            target=a["target"], created_at=a["created_at"],
        )
        for a in all_data
        if a["tenant_id"] == current_user.tenant_id
        and a["target"] in ("all",)
    ]


# ── Repetitor valideyni: uşağın qiymətləri + materialları ───────────────────

class RepGradeOut(BaseModel):
    id: str
    subject: str
    topic: Optional[str]
    grade: int
    date: str


class RepMaterialOut(BaseModel):
    id: str
    title: str
    content_type: str
    url: Optional[str]
    subject: Optional[str]
    topic: Optional[str]
    file_name: Optional[str]
    created_at: str


class RepPaymentOut(BaseModel):
    id: str
    amount: int
    paid_amount: int = 0
    month: str
    status: str
    payment_date: Optional[str] = None


class ParentRepInfoOut(BaseModel):
    has_repetitor: bool
    child_name: Optional[str] = None
    teacher_name: Optional[str] = None
    subject: Optional[str] = None
    daily_grades: list[RepGradeOut] = []
    daily_avg: Optional[float] = None
    materials: list[RepMaterialOut] = []
    payments: list[RepPaymentOut] = []
    outstanding: int = 0            # qepik — ümumi qalıq borc


@router.get("/repetitor/data", response_model=ParentRepInfoOut)
async def get_parent_repetitor_data(
    current_user: User = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
):
    """Valideynin repetitor şagirdi olan övladının qiymətləri və materialları."""
    from app.models.repetitor import RepetitorStudent, RepetitorDailyGrade, RepetitorPayment
    from app.models.content import Content

    rs_res = await db.execute(
        select(RepetitorStudent).where(RepetitorStudent.parent_user_id == current_user.id).limit(1)
    )
    rs = rs_res.scalars().first()
    if not rs:
        return ParentRepInfoOut(has_repetitor=False)

    t_res = await db.execute(select(User).where(User.id == rs.teacher_id))
    teacher = t_res.scalar_one_or_none()

    # Günlük qiymətlər
    g_res = await db.execute(
        select(RepetitorDailyGrade)
        .where(RepetitorDailyGrade.student_id == rs.id)
        .order_by(RepetitorDailyGrade.date.desc())
    )
    grades = g_res.scalars().all()
    grade_out = [
        RepGradeOut(id=g.id, subject=g.subject, topic=g.note, grade=g.grade, date=g.date)
        for g in grades
    ]
    avg = round(sum(g.grade for g in grades) / len(grades), 1) if grades else None

    # Repetitorun materialları
    m_res = await db.execute(
        select(Content)
        .where(Content.teacher_id == rs.teacher_id, Content.is_active == True)
        .order_by(Content.created_at.desc())
    )
    materials = [
        RepMaterialOut(
            id=c.id, title=c.title, content_type=c.content_type, url=c.url,
            subject=c.subject, topic=c.topic, file_name=c.file_name,
            created_at=c.created_at.isoformat() if c.created_at else "",
        )
        for c in m_res.scalars().all()
    ]

    # Ödənişlər
    p_res = await db.execute(
        select(RepetitorPayment)
        .where(RepetitorPayment.student_id == rs.id)
        .order_by(RepetitorPayment.month.desc())
    )
    pays = p_res.scalars().all()
    pay_out = [
        RepPaymentOut(
            id=p.id, amount=p.amount, paid_amount=getattr(p, 'paid_amount', 0) or 0,
            month=p.month, status=p.status, payment_date=getattr(p, 'payment_date', None),
        )
        for p in pays
    ]
    outstanding = sum(
        max(p.amount - (getattr(p, 'paid_amount', 0) or 0), 0)
        for p in pays if p.status != "paid"
    )

    return ParentRepInfoOut(
        has_repetitor=True,
        child_name=rs.name,
        teacher_name=teacher.name if teacher else None,
        subject=rs.subject or None,
        daily_grades=grade_out,
        daily_avg=avg,
        materials=materials,
        payments=pay_out,
        outstanding=outstanding,
    )
