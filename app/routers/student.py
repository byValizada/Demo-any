"""
Student Router
--------------
/student/* — şagird dashboard-u üçün API endpoint-lər
"""

from fastapi import APIRouter, Depends, Query, UploadFile, File, Form, HTTPException
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta, date as date_type
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
import json
from app.database import get_db
from app.dependencies import require_role
from app.models.user import User
from app.models.student import Student
from app.models.class_model import Class
from app.models.exam import ExamResult, Exam

router = APIRouter(prefix="/student", tags=["Student"])
require_student = require_role("student", "admin", "superadmin")

# ── Nişan tərifləri ────────────────────────────────────────────────────────────
BADGE_DEFS = [
    {"id": "first_exam",    "icon": "🎓", "label": "İlk İmtahan",      "desc": "İlk imtahanını tamamladın",         "color": "#2196f3"},
    {"id": "exam_5",        "icon": "📗", "label": "5 İmtahan",         "desc": "5 imtahan verdın",                  "color": "#0891b2"},
    {"id": "exam_10",       "icon": "📚", "label": "İmtahan Ustası",    "desc": "10 imtahan verdin",                 "color": "#0d3b6e"},
    {"id": "perfect_score", "icon": "💯", "label": "Əla Nəticə",        "desc": "İmtahanda 90%+ qazandın",           "color": "#1b7a4a"},
    {"id": "xp_100",        "icon": "⚡", "label": "100 XP",            "desc": "100 XP qazandın",                   "color": "#c75b00"},
    {"id": "xp_500",        "icon": "⭐", "label": "XP Toplayıcı",      "desc": "500 XP qazandın",                   "color": "#7c3aed"},
    {"id": "xp_1000",       "icon": "🌠", "label": "Min XP",            "desc": "1000 XP qazandın",                  "color": "#6b7280"},
    {"id": "streak_3",      "icon": "🔥", "label": "3 Günlük Seriya",   "desc": "3 gün ardıcıl aktiv oldun",         "color": "#c75b00"},
    {"id": "streak_7",      "icon": "🔥", "label": "7 Günlük Seriya",   "desc": "7 gün ardıcıl aktiv oldun",         "color": "#dc2626"},
    {"id": "streak_30",     "icon": "🌟", "label": "30 Günlük Seriya",  "desc": "30 gün ardıcıl aktiv oldun",        "color": "#f59e0b"},
    {"id": "daily_3",       "icon": "📅", "label": "Gündəlik Hərif",    "desc": "3 gündəlik tapşırığı tamamladın",   "color": "#0891b2"},
    {"id": "daily_7",       "icon": "📆", "label": "Həftəlik Tapşırıq", "desc": "7 gündəlik tapşırığı tamamladın",   "color": "#1b7a4a"},
]
BADGE_IDS = {b["id"] for b in BADGE_DEFS}


def _get_badges(stu: Student) -> list[str]:
    """Şagirdin qazandığı nişanlar (JSON list)."""
    raw = stu.earned_badges
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return []
    return []


def _set_badges(stu: Student, badges: list[str]):
    stu.earned_badges = badges


def _update_streak(stu: Student) -> bool:
    """Günlük aktiv olma → streak yenilə. True qaytarırsa streak artdı."""
    today = date_type.today().isoformat()
    last = stu.last_active_date
    if last == today:
        return False   # artıq bu gün sayılıb
    yesterday = (date_type.today() - timedelta(days=1)).isoformat()
    if last == yesterday:
        stu.streak = (stu.streak or 0) + 1
    else:
        stu.streak = 1   # zəncir qırıldı
    stu.last_active_date = today
    return True


async def _check_and_award_badges(
    stu: Student,
    exam_count: int,
    percentage: float,
    daily_count: int,
) -> list[str]:
    """Şərtiləri yoxla, yeni nişanları qazandır. Yeni nişanların id-lərini qaytar."""
    earned = set(_get_badges(stu))
    new_badges: list[str] = []

    def _try(badge_id: str, condition: bool):
        if condition and badge_id not in earned:
            earned.add(badge_id)
            new_badges.append(badge_id)

    _try("first_exam",    exam_count >= 1)
    _try("exam_5",        exam_count >= 5)
    _try("exam_10",       exam_count >= 10)
    _try("perfect_score", percentage >= 90)
    _try("xp_100",        stu.xp >= 100)
    _try("xp_500",        stu.xp >= 500)
    _try("xp_1000",       stu.xp >= 1000)
    _try("streak_3",      (stu.streak or 0) >= 3)
    _try("streak_7",      (stu.streak or 0) >= 7)
    _try("streak_30",     (stu.streak or 0) >= 30)
    _try("daily_3",       daily_count >= 3)
    _try("daily_7",       daily_count >= 7)

    if new_badges:
        _set_badges(stu, list(earned))
    return new_badges


# ── Schemas ────────────────────────────────────────────────────────────────

class ExamResultOut(BaseModel):
    exam_title: str
    subject: str
    percentage: float
    submitted_at: str


class StudentDashboard(BaseModel):
    name: str
    email: str
    tenant_name: str
    class_name: Optional[str]
    class_subject: Optional[str]
    xp: int
    streak: int
    level: int
    exam_count: int
    avg_score: Optional[float]
    recent_exams: list[ExamResultOut]


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=StudentDashboard)
async def get_student_dashboard(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Şagird dashboard stats-ı"""

    # Get student profile
    stu_result = await db.execute(
        select(Student).where(Student.user_id == current_user.id)
    )
    stu = stu_result.scalar_one_or_none()

    # Get class info
    class_name = None
    class_subject = None
    if stu and stu.class_id:
        cls_result = await db.execute(
            select(Class).where(Class.id == stu.class_id)
        )
        cls = cls_result.scalar_one_or_none()
        if cls:
            class_name = cls.name
            class_subject = cls.subject

    # Get exam results
    recent_exams_out = []
    avg_score = None
    exam_count = 0
    if stu:
        results_result = await db.execute(
            select(ExamResult, Exam)
            .join(Exam, Exam.id == ExamResult.exam_id)
            .where(ExamResult.student_id == stu.id)
            .order_by(ExamResult.submitted_at.desc())
            .limit(5)
        )
        rows = results_result.all()
        exam_count = len(rows)

        if rows:
            avg_score = round(sum(r.percentage for r, _ in rows) / len(rows), 1)

        for result, exam in rows:
            recent_exams_out.append(ExamResultOut(
                exam_title=exam.title,
                subject=exam.subject,
                percentage=result.percentage,
                submitted_at=result.submitted_at.strftime("%d.%m.%Y") if result.submitted_at else "",
            ))

    # Tenant name
    from app.models.tenant import Tenant
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id)
    )
    tenant = tenant_result.scalar_one_or_none()
    tenant_name = tenant.name if tenant else ""

    return StudentDashboard(
        name=current_user.name,
        email=current_user.email,
        tenant_name=tenant_name,
        class_name=class_name,
        class_subject=class_subject,
        xp=stu.xp if stu else 0,
        streak=stu.streak if stu else 0,
        level=stu.level if stu else 1,
        exam_count=exam_count,
        avg_score=avg_score,
        recent_exams=recent_exams_out,
    )


class ProfileUpdate(BaseModel):
    name: Optional[str] = None


class ProfileOut(BaseModel):
    id: str
    name: str
    email: str
    role: str
    avatar_url: Optional[str] = None


@router.patch("/profile", response_model=ProfileOut)
async def update_student_profile(
    body: ProfileUpdate,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    if body.name:
        current_user.name = body.name
        await db.commit()
        await db.refresh(current_user)
    return ProfileOut(id=current_user.id, name=current_user.name, email=current_user.email,
                      role=current_user.role, avatar_url=current_user.avatar_url)


@router.post("/avatar", response_model=ProfileOut)
async def upload_student_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(require_student),
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


class HomeworkStudentOut(BaseModel):
    id: str
    title: str
    description: Optional[str]
    deadline: str
    is_active: bool
    class_name: str
    submitted: bool


@router.get("/homework", response_model=list[HomeworkStudentOut])
async def get_student_homework(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    from app.models.homework import Homework, HomeworkSubmission
    stu_result = await db.execute(select(Student).where(Student.user_id == current_user.id))
    stu = stu_result.scalar_one_or_none()
    if not stu or not stu.class_id:
        return []
    cls_result = await db.execute(select(Class).where(Class.id == stu.class_id))
    cls = cls_result.scalar_one_or_none()
    hw_result = await db.execute(
        select(Homework).where(Homework.class_id == stu.class_id).order_by(Homework.created_at.desc())
    )
    homeworks = hw_result.scalars().all()
    result = []
    for hw in homeworks:
        sub_result = await db.execute(
            select(HomeworkSubmission).where(
                HomeworkSubmission.homework_id == hw.id,
                HomeworkSubmission.student_id == stu.id
            )
        )
        submitted = sub_result.scalar_one_or_none() is not None
        result.append(HomeworkStudentOut(
            id=hw.id, title=hw.title, description=hw.description,
            deadline=hw.deadline.isoformat() if hw.deadline else "",
            is_active=hw.is_active, class_name=cls.name if cls else "",
            submitted=submitted,
        ))
    return result


class SubmitHomeworkOut(BaseModel):
    id: str
    homework_id: str
    student_id: str
    content: str
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    submitted_at: str


@router.post("/homework/{homework_id}/submit", response_model=SubmitHomeworkOut, status_code=201)
async def submit_homework(
    homework_id: str,
    content: str = Form(""),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    import uuid as _uuid
    from pathlib import Path as _Path
    from app.models.homework import Homework, HomeworkSubmission

    stu_result = await db.execute(select(Student).where(Student.user_id == current_user.id))
    stu = stu_result.scalar_one_or_none()
    if not stu:
        raise HTTPException(404, "Şagird tapılmadı")

    hw_result = await db.execute(select(Homework).where(Homework.id == homework_id))
    hw = hw_result.scalar_one_or_none()
    if not hw:
        raise HTTPException(404, "Tapşırıq tapılmadı")

    if hw.class_id != stu.class_id:
        raise HTTPException(403, "Bu tapşırıq sizin sinifinizə aid deyil")

    existing_result = await db.execute(
        select(HomeworkSubmission).where(
            HomeworkSubmission.homework_id == homework_id,
            HomeworkSubmission.student_id == stu.id,
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(400, "Artıq göndərilmişdir")

    # Mətn və ya fayldan ən azı biri olmalıdır
    if not content.strip() and not (file and file.filename):
        raise HTTPException(400, "Cavab mətni və ya fayl daxil edin")

    # Faylı saxla (varsa)
    file_url = None
    file_name = None
    if file and file.filename:
        upload_dir = _Path("uploads") / "homework_submissions"
        upload_dir.mkdir(parents=True, exist_ok=True)
        ext = _Path(file.filename).suffix.lower()
        unique_name = f"{_uuid.uuid4().hex}{ext}"
        data = await file.read()
        (upload_dir / unique_name).write_bytes(data)
        file_url = f"/uploads/homework_submissions/{unique_name}"
        file_name = file.filename

    sub = HomeworkSubmission(
        homework_id=homework_id,
        student_id=stu.id,
        answer=content.strip() or None,
        file_url=file_url,
        file_name=file_name,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    return SubmitHomeworkOut(
        id=sub.id,
        homework_id=sub.homework_id,
        student_id=sub.student_id,
        content=sub.answer or "",
        file_url=sub.file_url,
        file_name=sub.file_name,
        submitted_at=sub.submitted_at.isoformat() if sub.submitted_at else "",
    )


class LeaderboardEntry(BaseModel):
    rank: int
    name: str
    xp: int
    level: int
    streak: int
    is_me: bool
    avg_score: Optional[float] = None   # non-null for period-based boards
    exam_count: int = 0


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
async def get_leaderboard(
    period: str = Query("all", regex="^(all|month|week)$"),
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    stu_result = await db.execute(select(Student).where(Student.user_id == current_user.id))
    stu = stu_result.scalar_one_or_none()
    if not stu or not stu.class_id:
        return []

    # ── All-time: rank by XP ──────────────────────────────────────────
    if period == "all":
        all_result = await db.execute(
            select(Student, User)
            .join(User, User.id == Student.user_id)
            .where(Student.class_id == stu.class_id)
            .order_by(Student.xp.desc())
        )
        rows = all_result.all()
        return [
            LeaderboardEntry(
                rank=i + 1, name=u.name, xp=s.xp, level=s.level,
                streak=s.streak, is_me=(u.id == current_user.id)
            )
            for i, (s, u) in enumerate(rows)
        ]

    # ── Period-based: rank by average exam score ──────────────────────
    now = datetime.utcnow()
    since = now - (timedelta(days=7) if period == "week" else timedelta(days=30))

    # Get all students in class
    stu_rows_result = await db.execute(
        select(Student, User)
        .join(User, User.id == Student.user_id)
        .where(Student.class_id == stu.class_id)
    )
    stu_rows = stu_rows_result.all()

    entries = []
    for s, u in stu_rows:
        # Count exam results in period
        res_result = await db.execute(
            select(ExamResult)
            .where(
                and_(
                    ExamResult.student_id == s.id,
                    ExamResult.submitted_at >= since,
                )
            )
        )
        results = res_result.scalars().all()
        count = len(results)
        avg = (sum(r.percentage for r in results) / count) if count > 0 else 0.0
        entries.append({
            "s": s, "u": u,
            "avg": avg, "count": count,
            "is_me": u.id == current_user.id,
        })

    # Sort by avg score desc, then by exam count desc
    entries.sort(key=lambda e: (-e["avg"], -e["count"]))
    return [
        LeaderboardEntry(
            rank=i + 1,
            name=e["u"].name,
            xp=e["s"].xp,
            level=e["s"].level,
            streak=e["s"].streak,
            is_me=e["is_me"],
            avg_score=round(e["avg"], 1),
            exam_count=e["count"],
        )
        for i, e in enumerate(entries)
    ]


# ── Exam endpoints ─────────────────────────────────────────────────────────

class ExamListOut(BaseModel):
    id: str
    title: str
    subject: str
    duration_minutes: int
    question_count: int
    already_taken: bool
    score: Optional[float] = None
    percentage: Optional[float] = None


class QuestionStudentOut(BaseModel):
    id: str
    text: str
    type: str
    options: Optional[dict]
    points: int
    difficulty: str


class ExamDetailStudentOut(BaseModel):
    id: str
    title: str
    subject: str
    duration_minutes: int
    questions: list[QuestionStudentOut]


class SubmitExamBody(BaseModel):
    answers: dict  # {question_id: answer_text}
    violations: int = 0  # köçürmə pozuntu sayı (tab dəyişmə, tam ekran çıxışı)


class SubmitExamOut(BaseModel):
    score: float
    max_score: float
    percentage: float
    xp_gained: int
    correct_count: int
    total_count: int


class StudentResultOut(BaseModel):
    id: str
    exam_id: str
    exam_title: str
    subject: str
    score: float
    max_score: float
    percentage: float
    submitted_at: str
    class_name: str


@router.get("/exams", response_model=list[ExamListOut])
async def get_student_exams(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    from app.models.exam import Exam, Question, ExamResult
    # Şagird bir neçə sinifdə ola bilər — bütün Student qeydlərini götür
    stu_rows = (await db.execute(
        select(Student).where(Student.user_id == current_user.id)
    )).scalars().all()
    class_ids = [s.class_id for s in stu_rows if s.class_id]
    student_row_ids = [s.id for s in stu_rows]
    if not class_ids:
        return []

    exams_result = await db.execute(
        select(Exam)
        .where(Exam.class_id.in_(class_ids), Exam.is_active == True)
        .order_by(Exam.created_at.desc())
    )
    exams = exams_result.scalars().all()

    out = []
    for exam in exams:
        q_count_result = await db.execute(
            select(func.count(Question.id)).where(Question.exam_id == exam.id)
        )
        q_count = q_count_result.scalar_one() or 0

        # Sualı olmayan imtahan verilə bilməz — şagirdə göstərmə
        if q_count == 0:
            continue

        # Şagirdin hər hansı qeydi ilə təqdim edilibmi
        result_result = await db.execute(
            select(ExamResult).where(
                ExamResult.exam_id == exam.id,
                ExamResult.student_id.in_(student_row_ids),
            )
        )
        result = result_result.scalars().first()

        out.append(ExamListOut(
            id=exam.id,
            title=exam.title,
            subject=exam.subject,
            duration_minutes=exam.duration_minutes,
            question_count=q_count,
            already_taken=result is not None,
            score=result.score if result else None,
            percentage=result.percentage if result else None,
        ))
    return out


@router.get("/exams/{exam_id}", response_model=ExamDetailStudentOut)
async def get_student_exam_detail(
    exam_id: str,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException
    from app.models.exam import Exam, Question
    # Şagirdin bütün sinifləri
    stu_rows = (await db.execute(
        select(Student).where(Student.user_id == current_user.id)
    )).scalars().all()
    my_class_ids = {s.class_id for s in stu_rows if s.class_id}

    exam_result = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = exam_result.scalar_one_or_none()
    if not exam:
        raise HTTPException(404, "Exam not found")
    if stu_rows and exam.class_id not in my_class_ids:
        raise HTTPException(403, "Not your class")

    q_result = await db.execute(
        select(Question).where(Question.exam_id == exam_id).order_by(Question.id)
    )
    questions = q_result.scalars().all()

    return ExamDetailStudentOut(
        id=exam.id,
        title=exam.title,
        subject=exam.subject,
        duration_minutes=exam.duration_minutes,
        questions=[
            QuestionStudentOut(
                id=q.id, text=q.text, type=q.type,
                options=q.options, points=q.points, difficulty=q.difficulty
            )
            for q in questions
        ]
    )


@router.post("/exams/{exam_id}/submit", response_model=SubmitExamOut)
async def submit_exam(
    exam_id: str,
    body: SubmitExamBody,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException
    from app.models.exam import Exam, Question, ExamResult

    # Şagirdin bütün sinifləri
    stu_rows = (await db.execute(
        select(Student).where(Student.user_id == current_user.id)
    )).scalars().all()
    if not stu_rows:
        raise HTTPException(404, "Student not found")

    exam_result = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = exam_result.scalar_one_or_none()
    if not exam:
        raise HTTPException(404, "Exam not found")

    # İmtahanın sinfinə uyğun Student qeydini seç (yoxsa ilk qeyd)
    stu = next((s for s in stu_rows if s.class_id == exam.class_id), stu_rows[0])

    # Bütün qeydlər üzrə artıq təqdim edilibmi
    row_ids = [s.id for s in stu_rows]
    existing = await db.execute(
        select(ExamResult).where(
            ExamResult.exam_id == exam_id,
            ExamResult.student_id.in_(row_ids),
        )
    )
    if existing.scalars().first():
        raise HTTPException(400, "Already submitted")

    # Get questions and calculate score
    q_result = await db.execute(
        select(Question).where(Question.exam_id == exam_id)
    )
    questions = q_result.scalars().all()

    score = 0.0
    max_score = 0.0
    correct_count = 0
    for q in questions:
        max_score += q.points
        answer = body.answers.get(q.id, "").strip().lower()
        correct = q.correct_answer.strip().lower()
        if answer == correct:
            score += q.points
            correct_count += 1

    percentage = round((score / max_score * 100) if max_score > 0 else 0, 1)

    # Save result
    er = ExamResult(
        exam_id=exam_id,
        student_id=stu.id,
        score=score,
        max_score=max_score,
        percentage=percentage,
        answers=body.answers,
        violations=max(0, int(body.violations or 0)),
    )
    db.add(er)

    # Risk yoxlaması — imtahandan əvvəl etmək üçün köhnə nəticələri al
    prev_results_res = await db.execute(
        select(ExamResult)
        .where(ExamResult.student_id == stu.id)
        .order_by(ExamResult.submitted_at.desc())
        .limit(3)
    )
    prev_results = prev_results_res.scalars().all()

    # Award XP: 10 base + bonus based on percentage
    xp_gained = 10 + int(percentage / 10)
    stu.xp += xp_gained
    # Update level (every 100 XP = 1 level)
    stu.level = max(1, stu.xp // 100 + 1)

    # Streak yenilə
    _update_streak(stu)

    # Nişanları yoxla
    exam_count_res = await db.execute(
        select(func.count(ExamResult.id)).where(ExamResult.student_id == stu.id)
    )
    exam_count_val = (exam_count_res.scalar_one() or 0) + 1  # bu imtahan da daxil

    from app.models.gamification import DailyChallengeSubmission
    daily_count_res = await db.execute(
        select(func.count(DailyChallengeSubmission.id)).where(
            DailyChallengeSubmission.student_id == stu.id,
            DailyChallengeSubmission.is_correct == True,
        )
    )
    daily_count_val = daily_count_res.scalar_one() or 0

    new_badges = await _check_and_award_badges(stu, exam_count_val, percentage, daily_count_val)

    await db.commit()

    # Auto-notification to student
    from app.models.notification import Notification
    notif = Notification(
        user_id=current_user.id,
        title=f"İmtahan nəticəsi: {exam.title}",
        description=f"{exam.subject} — {round(percentage)}% ({correct_count}/{len(questions)} düzgün)",
        type="success" if percentage >= 60 else "warning",
    )
    db.add(notif)
    # Yeni nişan bildirişi
    for bid in new_badges:
        bdef = next((b for b in BADGE_DEFS if b["id"] == bid), None)
        if bdef:
            db.add(Notification(
                user_id=current_user.id,
                title=f"Yeni nişan: {bdef['icon']} {bdef['label']}",
                description=bdef["desc"],
                type="success",
            ))

    # Risk yoxlaması — müəllimə bildiriş
    await _check_and_notify_risk(
        student_name=current_user.name,
        teacher_id=exam.teacher_id,
        exam_title=exam.title,
        new_pct=percentage,
        prev_results=prev_results,
        db=db,
    )

    await db.commit()

    return SubmitExamOut(
        score=score,
        max_score=max_score,
        percentage=percentage,
        xp_gained=xp_gained,
        correct_count=correct_count,
        total_count=len(questions),
    )


class ReviewQuestionOut(BaseModel):
    id: str
    text: str
    type: str
    options: Optional[dict] = None
    points: int
    your_answer: str
    correct_answer: str
    is_correct: bool


@router.get("/exams/{exam_id}/review", response_model=list[ReviewQuestionOut])
async def review_exam(
    exam_id: str,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdin verdiyi cavablar + düzgün cavablar — səhvlərə baxış."""
    from fastapi import HTTPException
    from app.models.exam import Exam, Question, ExamResult

    stu_rows = (await db.execute(
        select(Student).where(Student.user_id == current_user.id)
    )).scalars().all()
    row_ids = [s.id for s in stu_rows]
    if not row_ids:
        raise HTTPException(404, "Student not found")

    # Bu imtahanın nəticəsi (verilmiş cavablar)
    res = await db.execute(
        select(ExamResult).where(
            ExamResult.exam_id == exam_id,
            ExamResult.student_id.in_(row_ids),
        )
    )
    result = res.scalars().first()
    if not result:
        raise HTTPException(404, "İmtahan hələ verilməyib")

    answers = result.answers or {}

    q_res = await db.execute(
        select(Question).where(Question.exam_id == exam_id).order_by(Question.id)
    )
    questions = q_res.scalars().all()

    out = []
    for q in questions:
        your = str(answers.get(q.id, "") or "").strip()
        correct = str(q.correct_answer or "").strip()
        is_correct = your.lower() == correct.lower() and your != ""
        out.append(ReviewQuestionOut(
            id=q.id, text=q.text, type=q.type,
            options=q.options if isinstance(q.options, dict) else None,
            points=q.points,
            your_answer=your,
            correct_answer=correct,
            is_correct=is_correct,
        ))
    return out


@router.get("/results/{result_id}/certificate-data")
async def get_certificate_data(
    result_id: str,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException
    from app.models.tenant import Tenant

    # Get exam result
    res_result = await db.execute(
        select(ExamResult, Exam)
        .join(Exam, Exam.id == ExamResult.exam_id)
        .where(ExamResult.id == result_id)
    )
    row = res_result.one_or_none()
    if not row:
        raise HTTPException(404, "Nəticə tapılmadı")

    exam_result, exam = row

    # Verify ownership (student must own this result)
    stu_res = await db.execute(select(Student).where(Student.user_id == current_user.id))
    stu = stu_res.scalar_one_or_none()
    if not stu or exam_result.student_id != stu.id:
        raise HTTPException(403, "Bu sizin nəticəniz deyil")

    # Only for 80%+
    if exam_result.percentage < 80:
        raise HTTPException(400, "Sertifikat yalnız 80% və yuxarı nəticə üçün verilir")

    # Get teacher name
    teacher_res = await db.execute(select(User).where(User.id == exam.teacher_id))
    teacher = teacher_res.scalar_one_or_none()

    # Get tenant name
    tenant_res = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = tenant_res.scalar_one_or_none()

    return {
        "student_name": current_user.name,
        "exam_title": exam.title,
        "subject": exam.subject,
        "score": exam_result.score,
        "max_score": exam_result.max_score,
        "percentage": round(exam_result.percentage, 1),
        "submitted_at": exam_result.submitted_at.strftime("%d.%m.%Y") if exam_result.submitted_at else "",
        "teacher_name": teacher.name if teacher else "—",
        "school_name": tenant.name if tenant else "EduAI",
    }


@router.get("/results", response_model=list[StudentResultOut])
async def get_student_results(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    from app.models.exam import Exam, ExamResult
    stu_result = await db.execute(select(Student).where(Student.user_id == current_user.id))
    stu = stu_result.scalar_one_or_none()
    if not stu:
        return []

    rows_result = await db.execute(
        select(ExamResult, Exam, Class)
        .join(Exam, Exam.id == ExamResult.exam_id)
        .join(Class, Class.id == Exam.class_id)
        .where(ExamResult.student_id == stu.id)
        .order_by(ExamResult.submitted_at.desc())
    )
    rows = rows_result.all()

    return [
        StudentResultOut(
            id=r.id,
            exam_id=r.exam_id,
            exam_title=e.title,
            subject=e.subject,
            score=r.score,
            max_score=r.max_score,
            percentage=r.percentage,
            submitted_at=r.submitted_at.strftime("%d.%m.%Y %H:%M") if r.submitted_at else "",
            class_name=c.name,
        )
        for r, e, c in rows
    ]


async def _check_and_notify_risk(
    student_name: str,
    teacher_id: str,
    exam_title: str,
    new_pct: float,
    prev_results: list,
    db,
) -> None:
    """Şagirdin nəticəsi risk həddindədirsə müəllimə bildiriş göndər."""
    from app.models.notification import Notification

    is_risk = False
    reason = ""

    if new_pct < 40:
        is_risk = True
        reason = f"Son imtahanda çox aşağı nəticə: {round(new_pct)}%"
    elif len(prev_results) >= 1:
        prev_avg = sum(r.percentage for r in prev_results) / len(prev_results)
        if new_pct < 55 and prev_avg < 65:
            is_risk = True
            reason = f"Ardıcıl aşağı nəticələr (ortalama {round(prev_avg)}% → {round(new_pct)}%)"
        elif prev_avg - new_pct >= 25:
            is_risk = True
            reason = f"Kəskin düşüş: {round(prev_avg)}% → {round(new_pct)}%"

    if is_risk:
        db.add(Notification(
            user_id=teacher_id,
            title=f"⚠️ Risk siqnalı: {student_name}",
            description=f'"{exam_title}" imtahanı — {reason}',
            type="warning",
        ))


# ── Nişanlar ────────────────────────────────────────────────────────────────

class BadgeOut(BaseModel):
    id: str
    icon: str
    label: str
    desc: str
    color: str
    unlocked: bool
    progress_current: int = 0   # cari dəyər
    progress_max: int = 0       # hədəf dəyər
    progress_label: str = ""    # "3 / 10 imtahan"


@router.get("/badges", response_model=list[BadgeOut])
async def get_badges(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdin qazandığı + qazanmadığı nişanlar, hər birinin irəliləyiş məlumatı ilə."""
    from app.models.gamification import DailyChallengeSubmission

    stu_rows = (await db.execute(
        select(Student).where(Student.user_id == current_user.id)
    )).scalars().all()

    earned: set[str] = set()
    streak = 0
    xp = 0
    for s in stu_rows:
        earned.update(_get_badges(s))
        streak = max(streak, s.streak or 0)
        xp = max(xp, s.xp or 0)

    row_ids = [s.id for s in stu_rows]

    # İmtahan sayı
    exam_count = 0
    if row_ids:
        ec = (await db.execute(
            select(func.count(ExamResult.id)).where(ExamResult.student_id.in_(row_ids))
        )).scalar_one()
        exam_count = ec or 0

    # Gündəlik tapşırıq düzgün sayı
    daily_count = 0
    if row_ids:
        dc = (await db.execute(
            select(func.count(DailyChallengeSubmission.id)).where(
                DailyChallengeSubmission.student_id.in_(row_ids),
                DailyChallengeSubmission.is_correct == True,
            )
        )).scalar_one()
        daily_count = dc or 0

    def _prog(badge_id: str):
        """(current, max, label) → irəliləyiş məlumatı."""
        m = {
            "first_exam":    (exam_count,  1,    f"{exam_count} / 1 imtahan"),
            "exam_5":        (exam_count,  5,    f"{exam_count} / 5 imtahan"),
            "exam_10":       (exam_count,  10,   f"{exam_count} / 10 imtahan"),
            "perfect_score": (exam_count,  1,    "İmtahanda 90%+ qazanmaq lazımdır"),
            "xp_100":        (xp,          100,  f"{xp} / 100 XP"),
            "xp_500":        (xp,          500,  f"{xp} / 500 XP"),
            "xp_1000":       (xp,          1000, f"{xp} / 1000 XP"),
            "streak_3":      (streak,      3,    f"{streak} / 3 gün seriya"),
            "streak_7":      (streak,      7,    f"{streak} / 7 gün seriya"),
            "streak_30":     (streak,      30,   f"{streak} / 30 gün seriya"),
            "daily_3":       (daily_count, 3,    f"{daily_count} / 3 tapşırıq"),
            "daily_7":       (daily_count, 7,    f"{daily_count} / 7 tapşırıq"),
        }
        return m.get(badge_id, (0, 0, ""))

    result = []
    for b in BADGE_DEFS:
        unlocked = b["id"] in earned
        cur, mx, lbl = _prog(b["id"])
        result.append(BadgeOut(
            id=b["id"], icon=b["icon"], label=b["label"],
            desc=b["desc"], color=b["color"],
            unlocked=unlocked,
            progress_current=min(cur, mx),
            progress_max=mx,
            progress_label=lbl if not unlocked else "",
        ))
    return result


# ── Gündəlik Tapşırıq ────────────────────────────────────────────────────────

class DailyChallengeOut(BaseModel):
    date: str
    question_id: Optional[str]
    text: str
    type: str
    options: Optional[list[str]]
    points: int
    already_done: bool
    xp_reward: int


class DailyChallengeAnswerBody(BaseModel):
    answer: str


class DailyChallengeAnswerOut(BaseModel):
    is_correct: bool
    correct_answer: str
    xp_gained: int
    new_xp: int
    new_streak: int
    new_badges: list[str]


@router.get("/daily-challenge", response_model=DailyChallengeOut)
async def get_daily_challenge(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Bu günün tapşırığı — sual bankından seçilir."""
    from app.models.exam import Question
    from app.models.gamification import DailyChallengeSubmission
    import random

    stu_rows = (await db.execute(
        select(Student).where(Student.user_id == current_user.id)
    )).scalars().all()
    stu = stu_rows[0] if stu_rows else None

    today = date_type.today().isoformat()
    already_done = False

    if stu:
        done = (await db.execute(
            select(DailyChallengeSubmission).where(
                DailyChallengeSubmission.student_id == stu.id,
                DailyChallengeSubmission.challenge_date == today,
            )
        )).scalars().first()
        already_done = done is not None

    # Sual bankından günə görə deterministik seç
    qs = (await db.execute(
        select(Question).where(Question.type.in_(["mcq", "truefalse"]))
    )).scalars().all()

    if not qs:
        # Fallback — statik sual
        return DailyChallengeOut(
            date=today, question_id=None,
            text="2 + 2 × 3 = ?",
            type="mcq", options=["A) 8", "B) 10", "C) 6", "D) 12"],
            points=1, already_done=already_done, xp_reward=25,
        )

    # Günə görə deterministik — tarixin günü rəqəmi ilə
    seed = sum(int(c) for c in today if c.isdigit())
    rng = random.Random(seed)
    q = rng.choice(qs)
    opts = None
    if q.type == "mcq" and isinstance(q.options, dict):
        opts = q.options.get("choices")
    elif q.type == "truefalse":
        opts = ["Doğru", "Yanlış"]

    return DailyChallengeOut(
        date=today, question_id=q.id,
        text=q.text, type=q.type,
        options=opts, points=q.points,
        already_done=already_done, xp_reward=25,
    )


@router.post("/daily-challenge/answer", response_model=DailyChallengeAnswerOut)
async def answer_daily_challenge(
    body: DailyChallengeAnswerBody,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Gündəlik tapşırığa cavab ver → XP + streak."""
    from app.models.exam import Question
    from app.models.gamification import DailyChallengeSubmission
    from app.models.notification import Notification

    stu_rows = (await db.execute(
        select(Student).where(Student.user_id == current_user.id)
    )).scalars().all()
    if not stu_rows:
        raise HTTPException(404, "Şagird tapılmadı")
    stu = stu_rows[0]

    today = date_type.today().isoformat()

    # Artıq cavablandırılıbmı?
    existing = (await db.execute(
        select(DailyChallengeSubmission).where(
            DailyChallengeSubmission.student_id == stu.id,
            DailyChallengeSubmission.challenge_date == today,
        )
    )).scalars().first()
    if existing:
        raise HTTPException(400, "Bu günün tapşırığını artıq tamamlamısınız")

    # Günün sualını tap (eyni deterministik seçim)
    import random
    qs = (await db.execute(
        select(Question).where(Question.type.in_(["mcq", "truefalse"]))
    )).scalars().all()

    correct_answer = "4"   # fallback
    question_id = None
    is_correct = False

    if qs:
        seed = sum(int(c) for c in today if c.isdigit())
        rng = random.Random(seed)
        q = rng.choice(qs)
        question_id = q.id
        correct_answer = q.correct_answer or ""
        is_correct = body.answer.strip().lower() == correct_answer.strip().lower()
    else:
        is_correct = body.answer.strip() == "8"  # fallback cavabı

    xp_reward = 25 if is_correct else 5   # yanlış cavab üçün də az XP

    # Streak yenilə
    _update_streak(stu)

    # XP əlavə et
    stu.xp += xp_reward
    stu.level = max(1, stu.xp // 100 + 1)

    # Nişanları yoxla
    exam_count_res = await db.execute(
        select(func.count(ExamResult.id)).where(ExamResult.student_id == stu.id)
    )
    exam_count_val = exam_count_res.scalar_one() or 0

    daily_correct_res = await db.execute(
        select(func.count(DailyChallengeSubmission.id)).where(
            DailyChallengeSubmission.student_id == stu.id,
            DailyChallengeSubmission.is_correct == True,
        )
    )
    daily_count_val = (daily_correct_res.scalar_one() or 0) + (1 if is_correct else 0)

    new_badges = await _check_and_award_badges(stu, exam_count_val, 0, daily_count_val)

    # Gündəlik tapşırıq qeydi saxla
    sub = DailyChallengeSubmission(
        student_id=stu.id,
        challenge_date=today,
        question_id=question_id,
        is_correct=is_correct,
        xp_awarded=xp_reward,
    )
    db.add(sub)

    # Bildiriş
    db.add(Notification(
        user_id=current_user.id,
        title="Gündəlik tapşırıq tamamlandı! 🎯",
        description=f"{'Düzgün! +' + str(xp_reward) + ' XP qazandın 🎉' if is_correct else 'Yanlış cavab, amma iştirak üçün +' + str(xp_reward) + ' XP'}",
        type="success" if is_correct else "info",
    ))
    for bid in new_badges:
        bdef = next((b for b in BADGE_DEFS if b["id"] == bid), None)
        if bdef:
            db.add(Notification(
                user_id=current_user.id,
                title=f"Yeni nişan: {bdef['icon']} {bdef['label']}",
                description=bdef["desc"],
                type="success",
            ))

    await db.commit()

    return DailyChallengeAnswerOut(
        is_correct=is_correct,
        correct_answer=correct_answer,
        xp_gained=xp_reward,
        new_xp=stu.xp,
        new_streak=stu.streak,
        new_badges=new_badges,
    )


# ── AI Öyrənmə Tövsiyəsi ────────────────────────────────────────────────────

@router.get("/ai/study-plan")
async def get_ai_study_plan(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdin fənlər üzrə imtahan nəticələrini analiz edib AI fərdi plan qaytarır."""
    from app.models.exam import Exam, ExamResult
    from app.services.ai_service import study_recommendations

    stu_rows = (await db.execute(
        select(Student).where(Student.user_id == current_user.id)
    )).scalars().all()
    row_ids = [s.id for s in stu_rows]

    subject_stats: list[dict] = []
    if row_ids:
        rows = (await db.execute(
            select(ExamResult, Exam)
            .join(Exam, Exam.id == ExamResult.exam_id)
            .where(ExamResult.student_id.in_(row_ids))
        )).all()

        # Fənn üzrə qrupla
        agg: dict[str, list[float]] = {}
        for r, e in rows:
            agg.setdefault(e.subject or "Ümumi", []).append(r.percentage or 0.0)
        subject_stats = [
            {"subject": subj, "percentage": sum(ps) / len(ps), "exams_count": len(ps)}
            for subj, ps in agg.items()
        ]

    try:
        result = await study_recommendations(current_user.name, subject_stats)
    except RuntimeError:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="AI servisi müvəqqəti əlçatmazdır.")
    return result


# ── Live Room ──────────────────────────────────────────────────────────────────

class StudentLiveRoomOut(BaseModel):
    room_name: str
    url: str


@router.get("/live-room", response_model=StudentLiveRoomOut)
async def get_student_live_room(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Returns the Jitsi room URL for the student's class teacher (legacy)."""
    from fastapi import HTTPException

    stu_result = await db.execute(select(Student).where(Student.user_id == current_user.id))
    stu = stu_result.scalar_one_or_none()

    if not stu or not stu.class_id:
        raise HTTPException(status_code=404, detail="Sinif tapılmadı")

    cls_result = await db.execute(select(Class).where(Class.id == stu.class_id))
    cls = cls_result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Sinif tapılmadı")

    teacher_result = await db.execute(select(User).where(User.id == cls.teacher_id))
    teacher = teacher_result.scalar_one_or_none()
    if not teacher:
        raise HTTPException(status_code=404, detail="Müəllim tapılmadı")

    room_name = f"eduai-{teacher.tenant_id[:8]}"
    return StudentLiveRoomOut(room_name=room_name, url=f"https://meet.jit.si/{room_name}")


# ── Live Sessions (new) ───────────────────────────────────────────────────────

class StudentLiveSessionOut(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    teacher_name: str
    class_name: Optional[str] = None
    scheduled_at: Optional[str] = None
    started_at: Optional[str] = None
    status: str
    room_name: str
    join_url: str


@router.get("/live-sessions", response_model=list[StudentLiveSessionOut])
async def get_student_live_sessions(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Returns live + upcoming sessions for the student's class(es)."""
    import sqlalchemy as _sa
    from app.database import engine

    # Find student's class_id(s)
    stu_r = await db.execute(select(Student).where(Student.user_id == current_user.id))
    stu = stu_r.scalar_one_or_none()
    if not stu or not stu.class_id:
        return []

    # Find teacher of that class
    cls_r = await db.execute(select(Class).where(Class.id == stu.class_id))
    cls = cls_r.scalar_one_or_none()
    if not cls:
        return []

    teacher_r = await db.execute(select(User).where(User.id == cls.teacher_id))
    teacher = teacher_r.scalar_one_or_none()
    teacher_name = teacher.name if teacher else "Müəllim"

    # Fetch sessions: live first, then scheduled, skip ended older than 2h
    async with engine.connect() as conn:
        r = await conn.execute(_sa.text("""
            SELECT * FROM live_sessions
            WHERE teacher_id = :tid
              AND (class_id = :cid OR class_id IS NULL)
              AND status IN ('live','scheduled')
            ORDER BY
              CASE status WHEN 'live' THEN 0 ELSE 1 END,
              scheduled_at ASC,
              created_at DESC
            LIMIT 20
        """), {"tid": cls.teacher_id, "cid": stu.class_id})
        rows = [dict(row) for row in r.mappings().all()]

    result = []
    for s in rows:
        result.append(StudentLiveSessionOut(
            id=s["id"],
            title=s["title"],
            description=s.get("description"),
            teacher_name=teacher_name,
            class_name=cls.name,
            scheduled_at=s.get("scheduled_at"),
            started_at=s.get("started_at"),
            status=s["status"],
            room_name=s["room_name"],
            join_url=f"https://meet.jit.si/{s['room_name']}",
        ))
    return result


# ══════════════════════════════════════════════════════════════════════════════
# ELANLAR — Korporativ admin tərəfindən yaradılan elanlar
# ══════════════════════════════════════════════════════════════════════════════

import json as _json
import os as _os

_ANNOUNCEMENTS_FILE_S = _os.path.join(_os.path.dirname(__file__), "..", "announcements_data.json")


class StudentAnnouncementOut(BaseModel):
    id: str
    title: str
    message: str
    target: str
    created_at: str


@router.get("/announcements", response_model=list[StudentAnnouncementOut])
async def get_student_announcements(
    current_user: User = Depends(require_student),
):
    """Şagirdin müəssisəsinə aid elanlar (target=all veya students)"""
    if not _os.path.exists(_ANNOUNCEMENTS_FILE_S):
        return []
    with open(_ANNOUNCEMENTS_FILE_S, encoding="utf-8") as f:
        all_data = _json.load(f)
    return [
        StudentAnnouncementOut(
            id=a["id"], title=a["title"], message=a["message"],
            target=a["target"], created_at=a["created_at"],
        )
        for a in all_data
        if a["tenant_id"] == current_user.tenant_id
        and a["target"] in ("all", "students")
    ]


# ── Repetitor şagirdi: qiymətlər ────────────────────────────────────────────

class RepGradeOut(BaseModel):
    id: str
    subject: str
    topic: Optional[str]
    grade: int
    date: str
    teacher_name: str


class RepInfoOut(BaseModel):
    has_repetitor: bool
    teacher_name: Optional[str] = None
    subject: Optional[str] = None
    daily_grades: list[RepGradeOut] = []
    daily_avg: Optional[float] = None


@router.get("/repetitor/grades", response_model=RepInfoOut)
async def get_repetitor_grades(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Login olmuş şagirdin repetitorundan aldığı günlük qiymətlər."""
    from app.models.repetitor import RepetitorStudent, RepetitorDailyGrade

    rs_res = await db.execute(
        select(RepetitorStudent).where(RepetitorStudent.user_id == current_user.id).limit(1)
    )
    rs = rs_res.scalars().first()
    if not rs:
        return RepInfoOut(has_repetitor=False)

    t_res = await db.execute(select(User).where(User.id == rs.teacher_id))
    teacher = t_res.scalar_one_or_none()

    g_res = await db.execute(
        select(RepetitorDailyGrade)
        .where(RepetitorDailyGrade.student_id == rs.id)
        .order_by(RepetitorDailyGrade.date.desc())
    )
    grades = g_res.scalars().all()

    grade_out = [
        RepGradeOut(
            id=g.id, subject=g.subject, topic=g.note,
            grade=g.grade, date=g.date,
            teacher_name=teacher.name if teacher else "—",
        )
        for g in grades
    ]
    avg = round(sum(g.grade for g in grades) / len(grades), 1) if grades else None

    return RepInfoOut(
        has_repetitor=True,
        teacher_name=teacher.name if teacher else None,
        subject=rs.subject or None,
        daily_grades=grade_out,
        daily_avg=avg,
    )


# ── Şagird qeydləri (notes) ─────────────────────────────────────────────────

class NoteOut(BaseModel):
    id: str
    title: str
    content: Optional[str]
    created_at: str


class NoteCreate(BaseModel):
    title: str
    content: Optional[str] = None


@router.get("/notes", response_model=list[NoteOut])
async def list_notes(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    from app.models.student_note import StudentNote
    res = await db.execute(
        select(StudentNote)
        .where(StudentNote.user_id == current_user.id)
        .order_by(StudentNote.created_at.desc())
    )
    return [
        NoteOut(
            id=n.id, title=n.title, content=n.content,
            created_at=n.created_at.strftime("%d.%m.%Y") if n.created_at else "",
        )
        for n in res.scalars().all()
    ]


@router.post("/notes", response_model=NoteOut, status_code=201)
async def create_note(
    body: NoteCreate,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    if not body.title.strip():
        raise HTTPException(400, "Başlıq boş ola bilməz")
    from app.models.student_note import StudentNote
    n = StudentNote(
        user_id=current_user.id,
        title=body.title.strip(),
        content=(body.content or "").strip() or None,
    )
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return NoteOut(
        id=n.id, title=n.title, content=n.content,
        created_at=n.created_at.strftime("%d.%m.%Y") if n.created_at else "",
    )


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(
    note_id: str,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    from app.models.student_note import StudentNote
    res = await db.execute(
        select(StudentNote).where(
            and_(StudentNote.id == note_id, StudentNote.user_id == current_user.id)
        )
    )
    n = res.scalar_one_or_none()
    if not n:
        raise HTTPException(404, "Qeyd tapılmadı")
    await db.delete(n)
    await db.commit()


# ── Hesabı bağla (deaktivasiya — geri qaytarıla bilən) ──────────────────────

@router.delete("/account", status_code=204)
async def deactivate_account(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Şagird öz hesabını bağlayır (is_active=False). Hard-delete deyil — geri qaytarıla bilər."""
    u_res = await db.execute(select(User).where(User.id == current_user.id))
    u = u_res.scalar_one_or_none()
    if u:
        u.is_active = False
        await db.commit()
