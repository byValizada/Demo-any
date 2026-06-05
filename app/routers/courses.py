"""
Courses Router — /courses/*
Müəllim: kurs yaradır, mövzular + dərslər əlavə edir.
Şagird: nəşr olunmuş kursları görür, irəliləyişini izləyir.
"""
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.course import Course, CourseModule, Lesson, LessonProgress

router = APIRouter(prefix="/courses", tags=["Courses"])
require_teacher = require_role("teacher", "admin", "superadmin")
require_student = require_role("student", "admin", "superadmin")
require_any     = require_role("student", "teacher", "admin", "superadmin")

# Kurs dərs faylları (video / sənəd) üçün qovluq
COURSE_UPLOAD_DIR = Path("uploads") / "courses"
COURSE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# İcazəli formatlar
VIDEO_MIME = {"video/mp4", "video/webm", "video/ogg", "video/quicktime", "video/x-msvideo"}
IMAGE_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
DOC_MIME = {
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
}
MAX_UPLOAD = 200 * 1024 * 1024   # 200 MB


@router.post("/teacher/upload")
async def teacher_upload_lesson_file(
    file: UploadFile = File(...),
    kind: str = "document",   # video | document
    current_user: User = Depends(require_teacher),
):
    """Dərs üçün video və ya sənəd faylını kompüterdən yüklə → URL qaytarır."""
    mime = file.content_type or ""
    allowed = VIDEO_MIME if kind == "video" else IMAGE_MIME if kind == "image" else DOC_MIME
    if mime not in allowed:
        raise HTTPException(415, f"Dəstəklənməyən format: {mime or 'naməlum'}")

    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Fayl çox böyükdür (maks. 200 MB)")

    ext = Path(file.filename or "file").suffix.lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    (COURSE_UPLOAD_DIR / unique_name).write_bytes(data)
    return {
        "url": f"/uploads/courses/{unique_name}",
        "file_name": file.filename or unique_name,
        "size": len(data),
    }


# ── Schemas ────────────────────────────────────────────────────────────────

class LessonResource(BaseModel):
    url: str
    name: str


class LessonIn(BaseModel):
    title: str
    content: Optional[str] = None
    lesson_type: str = "text"   # text | video | document | link
    url: Optional[str] = None
    file_name: Optional[str] = None
    resources: list[LessonResource] = []
    is_preview: bool = False
    order_index: int = 0
    duration_min: int = 5


class ModuleIn(BaseModel):
    title: str
    description: Optional[str] = None
    order_index: int = 0
    lessons: list[LessonIn] = []


class CourseIn(BaseModel):
    title: str
    subject: str
    subtitle: Optional[str] = None
    description: Optional[str] = None
    level: str = "beginner"
    cover_color: str = "#2196F3"
    cover_image: Optional[str] = None
    objectives: list[str] = []
    tags: list[str] = []
    prerequisite_id: Optional[str] = None
    assignment_mode: str = "public"
    is_published: bool = False
    modules: list[ModuleIn] = []


class LessonOut(BaseModel):
    id: str
    title: str
    content: Optional[str]
    lesson_type: str
    url: Optional[str]
    file_name: Optional[str] = None
    resources: list = []
    is_preview: bool = False
    order_index: int
    duration_min: int
    completed: bool = False   # şagird üçün


class QuizQuestion(BaseModel):
    q: str
    options: list[str]
    correct: int = 0   # düzgün variantın indeksi (müəllimə görünür)
    qtype: str = "mcq"          # mcq | truefalse
    explanation: str = ""       # cavabdan sonra izah


class ModuleOut(BaseModel):
    id: str
    title: str
    description: Optional[str]
    order_index: int
    lessons: list[LessonOut]
    completed_count: int = 0
    total_count: int = 0
    quiz_count: int = 0       # quiz sual sayı
    quiz_passed: bool = False # şagird quizi keçibmi


class CourseOut(BaseModel):
    id: str
    teacher_id: str
    teacher_name: str = ""
    title: str
    subtitle: Optional[str] = None
    subject: str
    description: Optional[str]
    level: str = "beginner"
    cover_color: str = "#2196F3"
    cover_image: Optional[str] = None
    objectives: list[str] = []
    tags: list[str] = []
    is_published: bool
    module_count: int = 0
    lesson_count: int = 0
    total_minutes: int = 0
    completed_lessons: int = 0  # şagird üçün
    avg_rating: float = 0.0
    review_count: int = 0
    last_lesson_id: Optional[str] = None   # şagirdin son baxdığı dərs
    is_favorite: bool = False
    prerequisite_id: Optional[str] = None
    prerequisite_title: Optional[str] = None
    prerequisite_locked: bool = False
    assignment_mode: str = "public"
    assigned_count: int = 0
    modules: list[ModuleOut] = []


# ── Teacher Endpoints ──────────────────────────────────────────────────────

@router.get("/teacher", response_model=list[CourseOut])
async def teacher_list_courses(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    courses = (await db.execute(
        select(Course).where(Course.teacher_id == current_user.id)
        .order_by(Course.created_at.desc())
    )).scalars().all()
    return [await _build_course_out(c, db) for c in courses]


@router.post("/teacher", response_model=CourseOut, status_code=201)
async def teacher_create_course(
    body: CourseIn,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    course = Course(
        teacher_id=current_user.id,
        title=body.title.strip(),
        subtitle=(body.subtitle or "").strip() or None,
        subject=body.subject.strip(),
        description=body.description,
        level=body.level or "beginner",
        cover_color=body.cover_color or "#2196F3",
        cover_image=body.cover_image or None,
        objectives=[o.strip() for o in (body.objectives or []) if o.strip()],
        tags=[t.strip() for t in (body.tags or []) if t.strip()],
        prerequisite_id=body.prerequisite_id or None,
        assignment_mode=body.assignment_mode or 'public',
        is_published=body.is_published,
    )
    db.add(course)
    await db.flush()

    for mi, mod in enumerate(body.modules):
        m = CourseModule(course_id=course.id, title=mod.title,
                         description=mod.description, order_index=mi)
        db.add(m)
        await db.flush()
        for li, les in enumerate(mod.lessons):
            db.add(Lesson(module_id=m.id, title=les.title, content=les.content,
                          lesson_type=les.lesson_type, url=les.url, file_name=les.file_name, resources=[r.model_dump() for r in les.resources], is_preview=les.is_preview,
                          order_index=li, duration_min=les.duration_min))

    await db.commit()
    await db.refresh(course)
    return await _build_course_out(course, db)


@router.patch("/teacher/{course_id}", response_model=CourseOut)
async def teacher_update_course(
    course_id: str,
    body: CourseIn,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    course = await _get_course_or_404(course_id, current_user.id, db)
    course.title = body.title.strip()
    course.subtitle = (body.subtitle or "").strip() or None
    course.subject = body.subject.strip()
    course.description = body.description
    course.level = body.level or course.level
    course.cover_color = body.cover_color or course.cover_color
    course.cover_image = body.cover_image or None
    if body.objectives is not None:
        course.objectives = [o.strip() for o in body.objectives if o.strip()]
    if body.tags is not None:
        course.tags = [t.strip() for t in body.tags if t.strip()]
    course.prerequisite_id = body.prerequisite_id or None
    course.assignment_mode = body.assignment_mode or course.assignment_mode
    course.is_published = body.is_published
    await db.commit()
    return await _build_course_out(course, db)


@router.post("/teacher/{course_id}/clone", response_model=CourseOut, status_code=201)
async def teacher_clone_course(
    course_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Kursu bütün bölmə/dərsləri ilə kopyala (qaralama olaraq)."""
    src = await _get_course_or_404(course_id, current_user.id, db)
    new = Course(
        teacher_id=current_user.id, title=f"{src.title} (kopya)",
        subtitle=src.subtitle, subject=src.subject, description=src.description,
        level=src.level, cover_color=src.cover_color, cover_image=src.cover_image,
        objectives=src.objectives if isinstance(src.objectives, list) else [],
        tags=src.tags if isinstance(src.tags, list) else [],
        is_published=False,
    )
    db.add(new)
    await db.flush()
    modules = (await db.execute(
        select(CourseModule).where(CourseModule.course_id == src.id).order_by(CourseModule.order_index)
    )).scalars().all()
    for m in modules:
        nm = CourseModule(course_id=new.id, title=m.title, description=m.description,
                          order_index=m.order_index, quiz=m.quiz if isinstance(m.quiz, list) else [])
        db.add(nm)
        await db.flush()
        lessons = (await db.execute(
            select(Lesson).where(Lesson.module_id == m.id).order_by(Lesson.order_index)
        )).scalars().all()
        for l in lessons:
            db.add(Lesson(module_id=nm.id, title=l.title, content=l.content,
                          lesson_type=l.lesson_type, url=l.url, file_name=l.file_name,
                          resources=l.resources if isinstance(l.resources, list) else [], is_preview=bool(l.is_preview),
                          order_index=l.order_index, duration_min=l.duration_min))
    await db.commit()
    await db.refresh(new)
    return await _build_course_out(new, db)


@router.delete("/teacher/{course_id}", status_code=204)
async def teacher_delete_course(
    course_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    course = await _get_course_or_404(course_id, current_user.id, db)
    await db.delete(course)
    await db.commit()


@router.post("/teacher/{course_id}/modules", response_model=ModuleOut, status_code=201)
async def teacher_add_module(
    course_id: str,
    body: ModuleIn,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    await _get_course_or_404(course_id, current_user.id, db)
    # Mövcud module sayı — order üçün
    cnt = (await db.execute(
        select(func.count(CourseModule.id)).where(CourseModule.course_id == course_id)
    )).scalar_one()
    m = CourseModule(course_id=course_id, title=body.title,
                     description=body.description, order_index=cnt)
    db.add(m)
    await db.flush()
    for li, les in enumerate(body.lessons):
        db.add(Lesson(module_id=m.id, title=les.title, content=les.content,
                      lesson_type=les.lesson_type, url=les.url, file_name=les.file_name, resources=[r.model_dump() for r in les.resources], is_preview=les.is_preview,
                      order_index=li, duration_min=les.duration_min))
    await db.commit()
    # Yeni əlavə olunan dərsləri açıq şəkildə oxu (async lazy-load qarşısını al)
    lessons = (await db.execute(
        select(Lesson).where(Lesson.module_id == m.id).order_by(Lesson.order_index)
    )).scalars().all()
    return _build_module_out(m, set(), lessons)


class ReorderBody(BaseModel):
    ids: list[str]   # yeni sıra


@router.put("/teacher/{course_id}/modules/reorder")
async def reorder_modules(
    course_id: str,
    body: ReorderBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    await _get_course_or_404(course_id, current_user.id, db)
    for idx, mid in enumerate(body.ids):
        m = (await db.execute(select(CourseModule).where(CourseModule.id == mid, CourseModule.course_id == course_id))).scalar_one_or_none()
        if m:
            m.order_index = idx
    await db.commit()
    return {"saved": True}


@router.put("/teacher/modules/{module_id}/lessons/reorder")
async def reorder_lessons(
    module_id: str,
    body: ReorderBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    m = (await db.execute(
        select(CourseModule).join(Course, Course.id == CourseModule.course_id)
        .where(CourseModule.id == module_id, Course.teacher_id == current_user.id)
    )).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Mövzu tapılmadı")
    for idx, lid in enumerate(body.ids):
        l = (await db.execute(select(Lesson).where(Lesson.id == lid, Lesson.module_id == module_id))).scalar_one_or_none()
        if l:
            l.order_index = idx
    await db.commit()
    return {"saved": True}


class ModuleUpdateBody(BaseModel):
    title: str
    description: Optional[str] = None


@router.patch("/teacher/modules/{module_id}", response_model=ModuleOut)
async def teacher_update_module(
    module_id: str,
    body: ModuleUpdateBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    m = (await db.execute(
        select(CourseModule).join(Course, Course.id == CourseModule.course_id)
        .where(CourseModule.id == module_id, Course.teacher_id == current_user.id)
    )).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Mövzu tapılmadı")
    m.title = body.title.strip()
    m.description = body.description
    await db.commit()
    lessons = (await db.execute(
        select(Lesson).where(Lesson.module_id == m.id).order_by(Lesson.order_index)
    )).scalars().all()
    return _build_module_out(m, set(), lessons)


@router.delete("/teacher/modules/{module_id}", status_code=204)
async def teacher_delete_module(
    module_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    m = (await db.execute(
        select(CourseModule).join(Course, Course.id == CourseModule.course_id)
        .where(CourseModule.id == module_id, Course.teacher_id == current_user.id)
    )).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Mövzu tapılmadı")
    await db.delete(m)
    await db.commit()


@router.post("/teacher/modules/{module_id}/lessons", response_model=LessonOut, status_code=201)
async def teacher_add_lesson(
    module_id: str,
    body: LessonIn,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    # Ownership yoxla
    m = (await db.execute(
        select(CourseModule).join(Course, Course.id == CourseModule.course_id)
        .where(CourseModule.id == module_id, Course.teacher_id == current_user.id)
    )).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Mövzu tapılmadı")
    cnt = (await db.execute(
        select(func.count(Lesson.id)).where(Lesson.module_id == module_id)
    )).scalar_one()
    les = Lesson(module_id=module_id, title=body.title, content=body.content,
                 lesson_type=body.lesson_type, url=body.url, file_name=body.file_name, resources=[r.model_dump() for r in body.resources], is_preview=body.is_preview,
                 order_index=cnt, duration_min=body.duration_min)
    db.add(les)
    await db.commit()
    await db.refresh(les)
    return LessonOut(id=les.id, title=les.title, content=les.content,
                     lesson_type=les.lesson_type, url=les.url, file_name=les.file_name, resources=[r.model_dump() for r in les.resources], is_preview=les.is_preview,
                     order_index=les.order_index, duration_min=les.duration_min)


@router.patch("/teacher/lessons/{lesson_id}", response_model=LessonOut)
async def teacher_update_lesson(
    lesson_id: str,
    body: LessonIn,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    les = (await db.execute(
        select(Lesson)
        .join(CourseModule, CourseModule.id == Lesson.module_id)
        .join(Course, Course.id == CourseModule.course_id)
        .where(Lesson.id == lesson_id, Course.teacher_id == current_user.id)
    )).scalar_one_or_none()
    if not les:
        raise HTTPException(404, "Dərs tapılmadı")
    les.title = body.title
    les.content = body.content
    les.lesson_type = body.lesson_type
    les.url = body.url
    les.file_name = body.file_name
    les.resources = [r.model_dump() for r in body.resources]
    les.is_preview = body.is_preview
    les.duration_min = body.duration_min
    await db.commit()
    return LessonOut(id=les.id, title=les.title, content=les.content,
                     lesson_type=les.lesson_type, url=les.url, file_name=les.file_name, resources=[r.model_dump() for r in les.resources], is_preview=les.is_preview,
                     order_index=les.order_index, duration_min=les.duration_min)


@router.delete("/teacher/lessons/{lesson_id}", status_code=204)
async def teacher_delete_lesson(
    lesson_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    les = (await db.execute(
        select(Lesson)
        .join(CourseModule, CourseModule.id == Lesson.module_id)
        .join(Course, Course.id == CourseModule.course_id)
        .where(Lesson.id == lesson_id, Course.teacher_id == current_user.id)
    )).scalar_one_or_none()
    if not les:
        raise HTTPException(404, "Dərs tapılmadı")
    await db.delete(les)
    await db.commit()


# ── Student Endpoints ──────────────────────────────────────────────────────

@router.get("/student", response_model=list[CourseOut])
async def student_list_courses(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Nəşr olunmuş kurslar: açıq (public) VƏ ya bu şagirdə təyin olunanlar."""
    from app.models.course import CourseAssignment
    assigned_ids = set((await db.execute(
        select(CourseAssignment.course_id).where(CourseAssignment.user_id == current_user.id)
    )).scalars().all())

    courses = (await db.execute(
        select(Course)
        .join(User, User.id == Course.teacher_id)
        .where(Course.is_published == True, User.tenant_id == current_user.tenant_id)
        .order_by(Course.created_at.desc())
    )).scalars().all()
    # public kurslar hamıya; assigned kurslar yalnız təyin olunanlara
    visible = [c for c in courses if (c.assignment_mode or "public") == "public" or c.id in assigned_ids]
    return [await _build_course_out(c, db, user_id=current_user.id) for c in visible]


@router.get("/student/certificates")
async def my_certificates(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdin 100% tamamladığı bütün kursların sertifikat siyahısı."""
    courses = (await db.execute(
        select(Course).join(User, User.id == Course.teacher_id)
        .where(Course.is_published == True, User.tenant_id == current_user.tenant_id)
    )).scalars().all()
    out = []
    for course in courses:
        lesson_ids = (await db.execute(
            select(Lesson.id).join(CourseModule, CourseModule.id == Lesson.module_id)
            .where(CourseModule.course_id == course.id)
        )).scalars().all()
        total = len(lesson_ids)
        if total == 0:
            continue
        done = (await db.execute(
            select(func.count(LessonProgress.id)).where(
                LessonProgress.user_id == current_user.id,
                LessonProgress.lesson_id.in_(lesson_ids),
            )
        )).scalar_one()
        if done >= total:
            out.append({
                "course_id": course.id, "title": course.title,
                "subject": course.subject, "cover_color": course.cover_color,
                "lesson_count": total,
            })
    return out


@router.get("/student/{course_id}", response_model=CourseOut)
async def student_get_course(
    course_id: str,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    course = (await db.execute(
        select(Course).where(Course.id == course_id, Course.is_published == True)
    )).scalar_one_or_none()
    if not course:
        raise HTTPException(404, "Kurs tapılmadı")
    # Təyin olunmuş kursdursa giriş yoxla
    if (course.assignment_mode or "public") == "assigned":
        from app.models.course import CourseAssignment
        a = (await db.execute(
            select(CourseAssignment.id).where(
                CourseAssignment.course_id == course_id, CourseAssignment.user_id == current_user.id
            ).limit(1)
        )).scalars().first()
        if not a:
            raise HTTPException(403, "Bu kurs sizə təyin olunmayıb")
    return await _build_course_out(course, db, user_id=current_user.id)


@router.post("/student/{course_id}/favorite")
async def toggle_favorite(
    course_id: str,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Kursu sevimliyə əlavə et / çıxar."""
    from app.models.course import CourseFavorite
    existing = (await db.execute(
        select(CourseFavorite).where(
            CourseFavorite.course_id == course_id, CourseFavorite.user_id == current_user.id
        ).limit(1)
    )).scalars().first()
    if existing:
        await db.delete(existing)
        await db.commit()
        return {"is_favorite": False}
    db.add(CourseFavorite(course_id=course_id, user_id=current_user.id))
    await db.commit()
    return {"is_favorite": True}


@router.post("/student/lessons/{lesson_id}/complete", status_code=200)
async def student_complete_lesson(
    lesson_id: str,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Dərsi tamamlandı kimi işarələ. Ardıcıllıq: əvvəlki dərslər bitməyibsə icazə yoxdur."""
    # Bu dərsin kursunu və düz sıralı dərs siyahısını qur
    les = (await db.execute(select(Lesson).where(Lesson.id == lesson_id))).scalar_one_or_none()
    if not les:
        raise HTTPException(404, "Dərs tapılmadı")
    mod = (await db.execute(select(CourseModule).where(CourseModule.id == les.module_id))).scalar_one_or_none()
    if not mod:
        raise HTTPException(404, "Bölmə tapılmadı")

    modules = (await db.execute(
        select(CourseModule).where(CourseModule.course_id == mod.course_id).order_by(CourseModule.order_index)
    )).scalars().all()
    flat: list[str] = []
    for m in modules:
        lids = (await db.execute(
            select(Lesson.id).where(Lesson.module_id == m.id).order_by(Lesson.order_index)
        )).scalars().all()
        flat.extend(lids)

    idx = flat.index(lesson_id) if lesson_id in flat else 0
    if idx > 0:
        prev_ids = flat[:idx]
        done = set((await db.execute(
            select(LessonProgress.lesson_id).where(
                LessonProgress.user_id == current_user.id,
                LessonProgress.lesson_id.in_(prev_ids),
            )
        )).scalars().all())
        if not all(pid in done for pid in prev_ids):
            raise HTTPException(403, "Əvvəlki dərsləri tamamlamadan bu dərsi tamamlaya bilməzsiniz")

    existing = (await db.execute(
        select(LessonProgress).where(
            LessonProgress.user_id == current_user.id,
            LessonProgress.lesson_id == lesson_id,
        )
    )).scalar_one_or_none()
    xp_gained = 0
    if not existing:
        db.add(LessonProgress(user_id=current_user.id, lesson_id=lesson_id))
        xp_gained = await _award_course_xp(current_user.id, 5, db)
        await db.commit()
        # Nudge: kursda az dərs qaldısa motivasiya bildirişi
        try:
            from app.models.notification import Notification
            course = (await db.execute(
                select(Course).join(CourseModule, CourseModule.course_id == Course.id)
                .where(CourseModule.id == les.module_id).limit(1)
            )).scalars().first()
            if course:
                all_lids = (await db.execute(
                    select(Lesson.id).join(CourseModule, CourseModule.id == Lesson.module_id)
                    .where(CourseModule.course_id == course.id)
                )).scalars().all()
                done_cnt = (await db.execute(
                    select(func.count(LessonProgress.id)).where(
                        LessonProgress.user_id == current_user.id,
                        LessonProgress.lesson_id.in_(all_lids),
                    )
                )).scalar_one()
                remaining = len(all_lids) - done_cnt
                if remaining == 0:
                    db.add(Notification(user_id=current_user.id, type="success",
                        title=f"🎉 Kurs tamamlandı: {course.title}",
                        description="Təbriklər! Sertifikatını al."))
                    await db.commit()
                elif 1 <= remaining <= 2:
                    db.add(Notification(user_id=current_user.id, type="info",
                        title=f"Az qaldı! {course.title}",
                        description=f"Yalnız {remaining} dərs qaldı — kursu bitir 💪"))
                    await db.commit()
        except Exception:
            pass
    return {"completed": True, "xp_gained": xp_gained}


# ── Son baxılan dərs (Davam et) ──────────────────────────────────────────────

class LastViewedBody(BaseModel):
    course_id: str
    lesson_id: str


@router.post("/student/last-viewed", status_code=200)
async def set_last_viewed(
    body: LastViewedBody,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdin kursda son baxdığı dərsi yadda saxla."""
    from app.models.course import CourseLastViewed
    from datetime import datetime
    existing = (await db.execute(
        select(CourseLastViewed).where(
            CourseLastViewed.course_id == body.course_id,
            CourseLastViewed.user_id == current_user.id,
        ).limit(1)
    )).scalars().first()
    if existing:
        existing.lesson_id = body.lesson_id
        existing.updated_at = datetime.utcnow()
    else:
        db.add(CourseLastViewed(
            course_id=body.course_id, user_id=current_user.id, lesson_id=body.lesson_id,
        ))
    await db.commit()
    return {"saved": True}


# ── Kurs reytinqi + şərhlər ──────────────────────────────────────────────────

class ReviewBody(BaseModel):
    rating: int
    comment: Optional[str] = None


class ReviewOut(BaseModel):
    id: str
    user_name: str
    rating: int
    comment: Optional[str]
    created_at: str
    is_mine: bool = False


@router.get("/{course_id}/reviews", response_model=list[ReviewOut])
async def get_reviews(
    course_id: str,
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    from app.models.course import CourseReview
    rows = (await db.execute(
        select(CourseReview, User.name)
        .join(User, User.id == CourseReview.user_id)
        .where(CourseReview.course_id == course_id)
        .order_by(CourseReview.created_at.desc())
    )).all()
    return [
        ReviewOut(
            id=r.id, user_name=name, rating=r.rating, comment=r.comment,
            created_at=r.created_at.strftime("%d.%m.%Y") if r.created_at else "",
            is_mine=(r.user_id == current_user.id),
        )
        for r, name in rows
    ]


@router.post("/student/{course_id}/review", status_code=200)
async def submit_review(
    course_id: str,
    body: ReviewBody,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Şagird kursa reytinq + şərh verir (hər kursa bir dəfə, yenilənə bilər)."""
    from app.models.course import CourseReview
    rating = max(1, min(5, body.rating))
    existing = (await db.execute(
        select(CourseReview).where(
            CourseReview.course_id == course_id,
            CourseReview.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if existing:
        existing.rating = rating
        existing.comment = (body.comment or "").strip() or None
    else:
        db.add(CourseReview(
            course_id=course_id, user_id=current_user.id,
            rating=rating, comment=(body.comment or "").strip() or None,
        ))
    await db.commit()
    return {"saved": True}


# ── Müəllim kurs analitikası ─────────────────────────────────────────────────

class LessonStat(BaseModel):
    lesson_id: str
    title: str
    module_title: str
    completed_by: int      # neçə şagird tamamlayıb
    drop_rate: float       # buraxılma faizi (başlayanlara nisbətən)


class CourseAnalyticsOut(BaseModel):
    enrolled: int          # kursa başlayan şagird sayı
    avg_completion: float  # ortalama tamamlanma faizi
    avg_rating: float
    review_count: int
    quiz_avg: float        # quiz orta nəticəsi
    most_dropped: Optional[LessonStat] = None
    lessons: list[LessonStat] = []


@router.get("/teacher/{course_id}/analytics", response_model=CourseAnalyticsOut)
async def teacher_course_analytics(
    course_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    from app.models.course import CourseReview, ModuleQuizResult
    await _get_course_or_404(course_id, current_user.id, db)

    modules = (await db.execute(
        select(CourseModule).where(CourseModule.course_id == course_id).order_by(CourseModule.order_index)
    )).scalars().all()

    # Bütün dərslər (sıralı)
    flat: list[tuple] = []   # (lesson, module_title)
    for m in modules:
        ls = (await db.execute(
            select(Lesson).where(Lesson.module_id == m.id).order_by(Lesson.order_index)
        )).scalars().all()
        for l in ls:
            flat.append((l, m.title))
    total_lessons = len(flat)

    # Kursa başlayan şagirdlər (heç olmasa 1 dərs)
    lesson_ids = [l.id for l, _ in flat]
    enrolled_users: set[str] = set()
    completed_per_lesson: dict[str, int] = {}
    if lesson_ids:
        rows = (await db.execute(
            select(LessonProgress.user_id, LessonProgress.lesson_id)
            .where(LessonProgress.lesson_id.in_(lesson_ids))
        )).all()
        for uid, lid in rows:
            enrolled_users.add(uid)
            completed_per_lesson[lid] = completed_per_lesson.get(lid, 0) + 1
    enrolled = len(enrolled_users)

    # Hər şagirdin tamamlanma faizi → ortalama
    avg_completion = 0.0
    if enrolled and total_lessons:
        per_user: dict[str, int] = {}
        for uid, lid in (rows if lesson_ids else []):
            per_user[uid] = per_user.get(uid, 0) + 1
        avg_completion = round(sum(per_user.values()) / (enrolled * total_lessons) * 100, 1)

    # Dərs statistikası + drop rate
    lesson_stats: list[LessonStat] = []
    for l, mtitle in flat:
        cb = completed_per_lesson.get(l.id, 0)
        drop = round((1 - cb / enrolled) * 100, 1) if enrolled else 0.0
        lesson_stats.append(LessonStat(
            lesson_id=l.id, title=l.title, module_title=mtitle,
            completed_by=cb, drop_rate=drop,
        ))
    most_dropped = max(lesson_stats, key=lambda s: s.drop_rate, default=None) if lesson_stats else None
    if most_dropped and most_dropped.drop_rate == 0:
        most_dropped = None

    # Reytinq
    rr = (await db.execute(
        select(func.avg(CourseReview.rating), func.count(CourseReview.id))
        .where(CourseReview.course_id == course_id)
    )).first()
    avg_rating = round(float(rr[0]), 1) if rr and rr[0] else 0.0
    review_count = int(rr[1]) if rr and rr[1] else 0

    # Quiz orta
    mod_ids = [m.id for m in modules]
    quiz_avg = 0.0
    if mod_ids:
        qr = (await db.execute(
            select(func.avg(ModuleQuizResult.score)).where(ModuleQuizResult.module_id.in_(mod_ids))
        )).scalar_one_or_none()
        quiz_avg = round(float(qr), 1) if qr else 0.0

    return CourseAnalyticsOut(
        enrolled=enrolled, avg_completion=avg_completion,
        avg_rating=avg_rating, review_count=review_count, quiz_avg=quiz_avg,
        most_dropped=most_dropped, lessons=lesson_stats,
    )


# ── Kurs tamamlama sertifikatı ───────────────────────────────────────────────



@router.get("/student/{course_id}/certificate")
async def course_certificate(
    course_id: str,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Kurs 100% tamamlandıqda sertifikat məlumatları."""
    from app.models.tenant import Tenant
    course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one_or_none()
    if not course:
        raise HTTPException(404, "Kurs tapılmadı")

    # Bütün dərslər tamamlanıbmı?
    lesson_ids = (await db.execute(
        select(Lesson.id).join(CourseModule, CourseModule.id == Lesson.module_id)
        .where(CourseModule.course_id == course_id)
    )).scalars().all()
    total = len(lesson_ids)
    if total == 0:
        raise HTTPException(400, "Kursda dərs yoxdur")
    done = (await db.execute(
        select(func.count(LessonProgress.id)).where(
            LessonProgress.user_id == current_user.id,
            LessonProgress.lesson_id.in_(lesson_ids),
        )
    )).scalar_one()
    if done < total:
        raise HTTPException(400, "Sertifikat üçün kursu tam tamamlamalısınız")

    teacher = (await db.execute(select(User.name).where(User.id == course.teacher_id))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))).scalar_one_or_none()
    from datetime import datetime
    import hashlib
    # Unikal doğrulama kodu (kurs + şagird) — dəyişməz
    raw = f"{course.id}-{current_user.id}"
    verify_code = "VA-" + hashlib.sha1(raw.encode()).hexdigest()[:10].upper()
    return {
        "student_name": current_user.name,
        "course_title": course.title,
        "subject": course.subject,
        "lesson_count": total,
        "teacher_name": teacher or "—",
        "school_name": tenant.name if tenant else "EduAI",
        "date": datetime.now().strftime("%d.%m.%Y"),
        "verify_code": verify_code,
    }


# ── Müəllim: kim nəyi tamamladı ──────────────────────────────────────────────

class StudentProgressOut(BaseModel):
    student_id: str
    student_name: str
    completed: int
    total: int
    percent: int


class AnnounceBody(BaseModel):
    message: str


@router.post("/teacher/{course_id}/announce")
async def teacher_announce(
    course_id: str,
    body: AnnounceBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Kursa başlamış bütün şagirdlərə elan/bildiriş göndər."""
    from app.models.notification import Notification
    course = await _get_course_or_404(course_id, current_user.id, db)
    if not body.message.strip():
        raise HTTPException(400, "Mesaj boşdur")

    lesson_ids = (await db.execute(
        select(Lesson.id).join(CourseModule, CourseModule.id == Lesson.module_id)
        .where(CourseModule.course_id == course_id)
    )).scalars().all()
    user_ids: set[str] = set()
    if lesson_ids:
        uids = (await db.execute(
            select(LessonProgress.user_id).where(LessonProgress.lesson_id.in_(lesson_ids)).distinct()
        )).scalars().all()
        user_ids = set(uids)

    for uid in user_ids:
        db.add(Notification(
            user_id=uid, type="info",
            title=f"📢 Elan: {course.title}",
            description=body.message.strip(),
        ))
    await db.commit()
    return {"sent": len(user_ids)}


class AssignableStudent(BaseModel):
    user_id: str
    name: str
    email: str
    assigned: bool


@router.get("/teacher/{course_id}/assignable", response_model=list[AssignableStudent])
async def teacher_assignable_students(
    course_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Kursa təyin edilə bilən şagirdlər (tenant şagirdləri) + təyin statusu."""
    from app.models.student import Student
    from app.models.course import CourseAssignment
    await _get_course_or_404(course_id, current_user.id, db)

    rows = (await db.execute(
        select(User.id, User.name, User.email).distinct()
        .join(Student, Student.user_id == User.id)
        .where(User.tenant_id == current_user.tenant_id, User.role == "student")
        .order_by(User.name)
    )).all()
    assigned = set((await db.execute(
        select(CourseAssignment.user_id).where(CourseAssignment.course_id == course_id)
    )).scalars().all())
    return [
        AssignableStudent(user_id=uid, name=name, email=email, assigned=(uid in assigned))
        for uid, name, email in rows
    ]


class AssignBody(BaseModel):
    mode: str = "public"          # public | assigned
    student_ids: list[str] = []


@router.put("/teacher/{course_id}/assignments")
async def teacher_set_assignments(
    course_id: str,
    body: AssignBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Kursun təyinat rejimini + təyin olunan şagirdləri yenilə."""
    from app.models.course import CourseAssignment
    from app.models.notification import Notification
    course = await _get_course_or_404(course_id, current_user.id, db)
    course.assignment_mode = "assigned" if body.mode == "assigned" else "public"

    # Mövcud təyinatları sil
    existing = (await db.execute(
        select(CourseAssignment).where(CourseAssignment.course_id == course_id)
    )).scalars().all()
    existing_ids = {e.user_id for e in existing}
    for e in existing:
        await db.delete(e)

    new_ids = set(body.student_ids) if body.mode == "assigned" else set()
    freshly_assigned = []
    for uid in new_ids:
        db.add(CourseAssignment(course_id=course_id, user_id=uid))
        # Yeni təyin olunanlara bildiriş
        if uid not in existing_ids:
            db.add(Notification(
                user_id=uid, type="info",
                title=f"📚 Yeni kurs təyin edildi: {course.title}",
                description="Kurslar bölməsində sənə təyin olunan kursu gör.",
            ))
            freshly_assigned.append(uid)
    await db.commit()

    # Yeni təyin olunanlara e-mail
    if freshly_assigned:
        try:
            from app.services.email_service import send_event_email
            from app.config import settings as _s
            users = (await db.execute(
                select(User.email, User.name).where(User.id.in_(freshly_assigned))
            )).all()
            for email, uname in users:
                if email:
                    await send_event_email(
                        email, uname, "Yeni kurs təyin edildi",
                        f'Sizə yeni kurs təyin edildi: <b>{course.title}</b>. Platformada "Kurslar" bölməsində baxa bilərsiniz.',
                        "Kursa bax", f"{_s.APP_URL}",
                    )
        except Exception:
            pass

    return {"mode": course.assignment_mode, "assigned": len(new_ids)}


@router.get("/teacher/{course_id}/students", response_model=list[StudentProgressOut])
async def teacher_course_students(
    course_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Bu kursa baxan şagirdlərin irəliləyişi."""
    await _get_course_or_404(course_id, current_user.id, db)

    # Kursun bütün dərs id-ləri
    lesson_ids = (await db.execute(
        select(Lesson.id)
        .join(CourseModule, CourseModule.id == Lesson.module_id)
        .where(CourseModule.course_id == course_id)
    )).scalars().all()
    total = len(lesson_ids)
    if total == 0 or not lesson_ids:
        return []

    # Bu dərsləri tamamlamış istifadəçilər
    rows = (await db.execute(
        select(LessonProgress.user_id, User.name, func.count(LessonProgress.id))
        .join(User, User.id == LessonProgress.user_id)
        .where(LessonProgress.lesson_id.in_(lesson_ids))
        .group_by(LessonProgress.user_id, User.name)
    )).all()

    out = []
    for uid, name, cnt in rows:
        out.append(StudentProgressOut(
            student_id=uid, student_name=name,
            completed=cnt, total=total,
            percent=round(cnt / total * 100),
        ))
    out.sort(key=lambda s: -s.percent)
    return out


# ── Modul Quiz ───────────────────────────────────────────────────────────────

PASS_THRESHOLD = 60   # %

class QuizSetBody(BaseModel):
    questions: list[QuizQuestion]


@router.get("/teacher/modules/{module_id}/quiz", response_model=list[QuizQuestion])
async def teacher_get_quiz(
    module_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    m = (await db.execute(
        select(CourseModule).join(Course, Course.id == CourseModule.course_id)
        .where(CourseModule.id == module_id, Course.teacher_id == current_user.id)
    )).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Mövzu tapılmadı")
    return m.quiz if isinstance(m.quiz, list) else []


@router.put("/teacher/modules/{module_id}/quiz")
async def teacher_set_quiz(
    module_id: str,
    body: QuizSetBody,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    m = (await db.execute(
        select(CourseModule).join(Course, Course.id == CourseModule.course_id)
        .where(CourseModule.id == module_id, Course.teacher_id == current_user.id)
    )).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Mövzu tapılmadı")
    m.quiz = [q.model_dump() for q in body.questions]
    await db.commit()
    return {"saved": True, "count": len(body.questions)}


class StudentQuizQuestion(BaseModel):
    q: str
    options: list[str]
    qtype: str = "mcq"
    # correct GÖSTƏRİLMİR


@router.get("/student/modules/{module_id}/quiz", response_model=list[StudentQuizQuestion])
async def student_get_quiz(
    module_id: str,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    m = (await db.execute(select(CourseModule).where(CourseModule.id == module_id))).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Mövzu tapılmadı")
    quiz = m.quiz if isinstance(m.quiz, list) else []
    return [StudentQuizQuestion(q=item["q"], options=item.get("options", []), qtype=item.get("qtype", "mcq")) for item in quiz]


class QuizSubmitBody(BaseModel):
    answers: list[int]   # hər sual üçün seçilən indeks


class QuizResultOut(BaseModel):
    score: int
    passed: bool
    correct_count: int
    total: int
    correct_answers: list[int]   # düzgün cavablar (nəticədən sonra göstərilir)
    explanations: list[str] = [] # hər sual üçün izah


@router.post("/student/modules/{module_id}/quiz", response_model=QuizResultOut)
async def student_submit_quiz(
    module_id: str,
    body: QuizSubmitBody,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    from app.models.course import ModuleQuizResult
    m = (await db.execute(select(CourseModule).where(CourseModule.id == module_id))).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Mövzu tapılmadı")
    quiz = m.quiz if isinstance(m.quiz, list) else []
    if not quiz:
        raise HTTPException(400, "Bu mövzuda quiz yoxdur")

    correct_answers = [int(item.get("correct", 0)) for item in quiz]
    correct_count = sum(
        1 for i, ca in enumerate(correct_answers)
        if i < len(body.answers) and body.answers[i] == ca
    )
    total = len(quiz)
    score = round(correct_count / total * 100) if total else 0
    passed = score >= PASS_THRESHOLD

    # Nəticəni saxla (ən yaxşı nəticə qalır)
    prev = (await db.execute(
        select(ModuleQuizResult).where(
            ModuleQuizResult.module_id == module_id,
            ModuleQuizResult.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if prev:
        if score > prev.score:
            prev.score = score
            prev.passed = prev.passed or passed
        elif passed:
            prev.passed = True
    else:
        db.add(ModuleQuizResult(
            module_id=module_id, user_id=current_user.id,
            score=score, passed=passed,
        ))
    # İlk dəfə keçəndə XP qazandır
    first_pass = passed and not (prev and prev.passed)
    if first_pass:
        await _award_course_xp(current_user.id, 20, db)
    await db.commit()

    return QuizResultOut(
        score=score, passed=passed, correct_count=correct_count,
        total=total, correct_answers=correct_answers,
        explanations=[str(item.get("explanation", "")) for item in quiz],
    )


# ── Dərs qeydləri ────────────────────────────────────────────────────────────

class NoteBody(BaseModel):
    content: str


@router.get("/student/lessons/{lesson_id}/note")
async def get_note(
    lesson_id: str,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    from app.models.course import LessonNote
    n = (await db.execute(
        select(LessonNote).where(LessonNote.lesson_id == lesson_id, LessonNote.user_id == current_user.id)
    )).scalar_one_or_none()
    return {"content": n.content if n else ""}


@router.get("/student/notes/all")
async def all_my_notes(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdin bütün dərs qeydləri (kurs + dərs adı ilə)."""
    from app.models.course import LessonNote
    rows = (await db.execute(
        select(LessonNote, Lesson.title, CourseModule.title, Course.title, Course.cover_color, Course.id)
        .join(Lesson, Lesson.id == LessonNote.lesson_id)
        .join(CourseModule, CourseModule.id == Lesson.module_id)
        .join(Course, Course.id == CourseModule.course_id)
        .where(LessonNote.user_id == current_user.id)
        .order_by(LessonNote.updated_at.desc())
    )).all()
    out = []
    for n, lesson_title, mod_title, course_title, cover, cid in rows:
        if n.content and n.content.strip():
            out.append({
                "lesson_id": n.lesson_id, "lesson_title": lesson_title,
                "course_id": cid, "course_title": course_title, "cover_color": cover,
                "content": n.content,
                "updated_at": n.updated_at.strftime("%d.%m.%Y") if n.updated_at else "",
            })
    return out


@router.put("/student/lessons/{lesson_id}/note")
async def save_note(
    lesson_id: str,
    body: NoteBody,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    from app.models.course import LessonNote
    from datetime import datetime
    n = (await db.execute(
        select(LessonNote).where(LessonNote.lesson_id == lesson_id, LessonNote.user_id == current_user.id)
    )).scalar_one_or_none()
    if n:
        n.content = body.content
        n.updated_at = datetime.utcnow()
    else:
        db.add(LessonNote(lesson_id=lesson_id, user_id=current_user.id, content=body.content))
    await db.commit()
    return {"saved": True}


# ── Dərs sual-cavab ──────────────────────────────────────────────────────────

class CommentBody(BaseModel):
    text: str
    parent_id: Optional[str] = None


class CommentOut(BaseModel):
    id: str
    user_name: str
    user_role: str
    text: str
    parent_id: Optional[str]
    created_at: str
    is_mine: bool = False


@router.get("/lessons/{lesson_id}/comments", response_model=list[CommentOut])
async def get_comments(
    lesson_id: str,
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    from app.models.course import LessonComment
    rows = (await db.execute(
        select(LessonComment, User.name, User.role)
        .join(User, User.id == LessonComment.user_id)
        .where(LessonComment.lesson_id == lesson_id)
        .order_by(LessonComment.created_at.asc())
    )).all()
    return [
        CommentOut(
            id=c.id, user_name=name, user_role=role, text=c.text,
            parent_id=c.parent_id,
            created_at=c.created_at.strftime("%d.%m.%Y %H:%M") if c.created_at else "",
            is_mine=(c.user_id == current_user.id),
        )
        for c, name, role in rows
    ]


@router.post("/lessons/{lesson_id}/comments", response_model=CommentOut)
async def add_comment(
    lesson_id: str,
    body: CommentBody,
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    from app.models.course import LessonComment
    if not body.text.strip():
        raise HTTPException(400, "Mətn boşdur")
    c = LessonComment(
        lesson_id=lesson_id, user_id=current_user.id,
        parent_id=body.parent_id, text=body.text.strip(),
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return CommentOut(
        id=c.id, user_name=current_user.name, user_role=current_user.role,
        text=c.text, parent_id=c.parent_id,
        created_at=c.created_at.strftime("%d.%m.%Y %H:%M") if c.created_at else "",
        is_mine=True,
    )


@router.delete("/lessons/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: str,
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    from app.models.course import LessonComment
    c = (await db.execute(select(LessonComment).where(LessonComment.id == comment_id))).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Tapılmadı")
    if c.user_id != current_user.id and current_user.role not in ("teacher", "admin", "superadmin"):
        raise HTTPException(403, "İcazə yoxdur")
    # Cavabları da sil
    children = (await db.execute(select(LessonComment).where(LessonComment.parent_id == comment_id))).scalars().all()
    for ch in children:
        await db.delete(ch)
    await db.delete(c)
    await db.commit()


# ── Helpers ────────────────────────────────────────────────────────────────

async def _award_course_xp(user_id: str, amount: int, db) -> int:
    """Şagirdə XP əlavə et (kurs fəaliyyəti üçün). Qazanılan XP qaytarır."""
    from app.models.student import Student
    stu = (await db.execute(
        select(Student).where(Student.user_id == user_id).limit(1)
    )).scalars().first()
    if stu:
        stu.xp = (stu.xp or 0) + amount
        stu.level = max(1, stu.xp // 100 + 1)
        return amount
    return 0


async def _get_course_or_404(course_id: str, teacher_id: str, db) -> Course:
    c = (await db.execute(
        select(Course).where(Course.id == course_id, Course.teacher_id == teacher_id)
    )).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Kurs tapılmadı")
    return c


async def _build_course_out(course: Course, db, user_id: str = "") -> CourseOut:
    modules = (await db.execute(
        select(CourseModule).where(CourseModule.course_id == course.id)
        .order_by(CourseModule.order_index)
    )).scalars().all()

    completed_ids: set[str] = set()
    if user_id:
        lesson_ids_all = []
        for m in modules:
            lids = (await db.execute(
                select(Lesson.id).where(Lesson.module_id == m.id)
            )).scalars().all()
            lesson_ids_all.extend(lids)
        if lesson_ids_all:
            progs = (await db.execute(
                select(LessonProgress.lesson_id).where(
                    LessonProgress.user_id == user_id,
                    LessonProgress.lesson_id.in_(lesson_ids_all),
                )
            )).scalars().all()
            completed_ids = set(progs)

    # Keçilmiş quizlər
    passed_modules: set[str] = set()
    if user_id:
        from app.models.course import ModuleQuizResult
        mod_ids = [m.id for m in modules]
        if mod_ids:
            pq = (await db.execute(
                select(ModuleQuizResult.module_id).where(
                    ModuleQuizResult.user_id == user_id,
                    ModuleQuizResult.module_id.in_(mod_ids),
                    ModuleQuizResult.passed == True,
                )
            )).scalars().all()
            passed_modules = set(pq)

    module_outs = []
    total_lessons = 0
    total_minutes = 0
    for m in modules:
        lessons = (await db.execute(
            select(Lesson).where(Lesson.module_id == m.id).order_by(Lesson.order_index)
        )).scalars().all()
        total_lessons += len(lessons)
        total_minutes += sum(l.duration_min or 0 for l in lessons)
        module_outs.append(_build_module_out(m, completed_ids, lessons, passed_modules))

    # Təlimatçı adı
    tname = ""
    t = (await db.execute(select(User.name).where(User.id == course.teacher_id))).scalar_one_or_none()
    if t:
        tname = t

    objectives = course.objectives if isinstance(course.objectives, list) else []
    tags = course.tags if isinstance(course.tags, list) else []

    # Reytinq aqreqasiyası
    from app.models.course import CourseReview, CourseLastViewed
    rating_row = (await db.execute(
        select(func.avg(CourseReview.rating), func.count(CourseReview.id))
        .where(CourseReview.course_id == course.id)
    )).first()
    avg_rating = round(float(rating_row[0]), 1) if rating_row and rating_row[0] else 0.0
    review_count = int(rating_row[1]) if rating_row and rating_row[1] else 0

    # Şagirdin son baxdığı dərs + sevimli
    last_lesson_id = None
    is_favorite = False
    if user_id:
        lv = (await db.execute(
            select(CourseLastViewed.lesson_id).where(
                CourseLastViewed.course_id == course.id,
                CourseLastViewed.user_id == user_id,
            ).order_by(CourseLastViewed.updated_at.desc()).limit(1)
        )).scalars().first()
        last_lesson_id = lv
        from app.models.course import CourseFavorite
        fav = (await db.execute(
            select(CourseFavorite.id).where(
                CourseFavorite.course_id == course.id, CourseFavorite.user_id == user_id
            ).limit(1)
        )).scalars().first()
        is_favorite = fav is not None

    # Önşərt kurs
    prereq_title = None
    prereq_locked = False
    if course.prerequisite_id:
        pc = (await db.execute(select(Course).where(Course.id == course.prerequisite_id))).scalar_one_or_none()
        if pc:
            prereq_title = pc.title
            if user_id:
                # önşərt kurs tam tamamlanıbmı?
                p_lids = (await db.execute(
                    select(Lesson.id).join(CourseModule, CourseModule.id == Lesson.module_id)
                    .where(CourseModule.course_id == pc.id)
                )).scalars().all()
                if p_lids:
                    p_done = (await db.execute(
                        select(func.count(LessonProgress.id)).where(
                            LessonProgress.user_id == user_id,
                            LessonProgress.lesson_id.in_(p_lids),
                        )
                    )).scalar_one()
                    prereq_locked = p_done < len(p_lids)

    from app.models.course import CourseAssignment as _CA
    assigned_count = (await db.execute(select(func.count(_CA.id)).where(_CA.course_id == course.id))).scalar_one() or 0
    return CourseOut(
        id=course.id, teacher_id=course.teacher_id, teacher_name=tname,
        title=course.title, subtitle=course.subtitle, subject=course.subject,
        description=course.description, level=course.level or "beginner",
        cover_color=course.cover_color or "#2196F3", cover_image=course.cover_image, objectives=objectives, tags=tags,
        is_published=course.is_published,
        module_count=len(modules), lesson_count=total_lessons,
        total_minutes=total_minutes,
        completed_lessons=len(completed_ids),
        avg_rating=avg_rating, review_count=review_count,
        last_lesson_id=last_lesson_id, is_favorite=is_favorite,
        prerequisite_id=course.prerequisite_id, prerequisite_title=prereq_title,
        prerequisite_locked=prereq_locked,
        assignment_mode=course.assignment_mode or 'public', assigned_count=assigned_count,
        modules=module_outs,
    )


def _build_module_out(m: CourseModule, completed: set[str], lessons: list[Lesson] | None = None,
                      passed_modules: set[str] | None = None) -> ModuleOut:
    if lessons is None:
        lessons = []   # async kontekstdə lazy-load etmə
    lesson_outs = [
        LessonOut(
            id=l.id, title=l.title, content=l.content,
            lesson_type=l.lesson_type, url=l.url, file_name=l.file_name, resources=(l.resources if isinstance(l.resources, list) else []), is_preview=bool(l.is_preview),
            order_index=l.order_index, duration_min=l.duration_min,
            completed=(l.id in completed),
        )
        for l in lessons
    ]
    done = sum(1 for l in lesson_outs if l.completed)
    quiz = m.quiz if isinstance(m.quiz, list) else []
    return ModuleOut(
        id=m.id, title=m.title, description=m.description,
        order_index=m.order_index, lessons=lesson_outs,
        completed_count=done, total_count=len(lesson_outs),
        quiz_count=len(quiz),
        quiz_passed=(m.id in (passed_modules or set())),
    )
