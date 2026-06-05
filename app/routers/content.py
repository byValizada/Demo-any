"""
Content Router — /content/*
Dərs materialları: link, qeyd, sənəd, şəkil, video + çoxlu əlavələr
"""
import uuid, json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.dependencies import get_current_user, require_role, require_not_demo_repetitor
from app.models.user import User
from app.models.content import Content, ContentAttachment
from app.models.class_model import Class
from app.models.student import Student

router = APIRouter(
    prefix="/content",
    tags=["Content"],
    dependencies=[Depends(require_not_demo_repetitor)],
)
require_teacher = require_role("teacher", "admin", "superadmin")

UPLOAD_DIR = Path("uploads") / "content"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_MIME: dict[str, str] = {
    "application/pdf": "document",
    "application/msword": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/vnd.ms-excel": "document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
    "application/vnd.ms-powerpoint": "document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "document",
    "text/plain": "document",
    "image/jpeg": "image", "image/png": "image", "image/gif": "image",
    "image/webp": "image", "image/svg+xml": "image",
    "video/mp4": "video", "video/webm": "video", "video/ogg": "video",
    "video/quicktime": "video", "video/x-msvideo": "video",
}


# ── Schemas ────────────────────────────────────────────────────────────────
class AttachmentOut(BaseModel):
    id: str
    attachment_type: str
    url: str
    label: Optional[str]
    file_name: Optional[str]
    file_size: Optional[int]
    created_at: str

class ContentOut(BaseModel):
    id: str
    title: str
    description: Optional[str]
    content_type: str
    url: Optional[str]
    subject: Optional[str]
    topic: Optional[str]
    class_id: Optional[str]
    class_name: Optional[str]
    class_names: list[str] = []
    teacher_name: str
    file_name: Optional[str]
    file_size: Optional[int]
    attachment_count: int = 0
    created_at: str

class ContentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    content_type: str = "link"
    url: Optional[str] = None
    subject: Optional[str] = None
    topic: Optional[str] = None
    class_ids: list[str] = []

class ContentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    subject: Optional[str] = None
    topic: Optional[str] = None
    class_ids: Optional[list[str]] = None

class AttachmentLinkIn(BaseModel):
    url: str
    label: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────
def _parse_class_ids(class_id: Optional[str]) -> list[str]:
    if not class_id:
        return []
    try:
        parsed = json.loads(class_id)
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x]
        return [str(parsed)] if parsed else []
    except (json.JSONDecodeError, ValueError):
        return [class_id]


async def _batch_class_names(db: AsyncSession, class_ids_list: list[str]) -> dict[str, str]:
    """Bütün lazım olan class ID-lərini BİR sorğuda al."""
    if not class_ids_list:
        return {}
    res = await db.execute(select(Class).where(Class.id.in_(class_ids_list)))
    return {c.id: c.name for c in res.scalars().all()}


def _build_out(
    item: Content,
    teacher_name: str,
    cls_map: dict[str, str],
    att_count: int = 0,
) -> ContentOut:
    ids = _parse_class_ids(item.class_id)
    names = [cls_map[i] for i in ids if i in cls_map]
    return ContentOut(
        id=item.id, title=item.title, description=item.description,
        content_type=item.content_type, url=item.url,
        subject=item.subject, topic=item.topic,
        class_id=item.class_id,
        class_name=names[0] if names else None,
        class_names=names,
        teacher_name=teacher_name,
        file_name=item.file_name, file_size=item.file_size,
        attachment_count=att_count,
        created_at=item.created_at.isoformat() if item.created_at else "",
    )


def _att_out(a: ContentAttachment) -> AttachmentOut:
    return AttachmentOut(
        id=a.id, attachment_type=a.attachment_type,
        url=a.url, label=a.label,
        file_name=a.file_name, file_size=a.file_size,
        created_at=a.created_at.isoformat() if a.created_at else "",
    )


def _safe_class_id(class_ids: list[str]) -> Optional[str]:
    if not class_ids:
        return None
    return json.dumps(class_ids)


def _safe_filename(url: str) -> Optional[Path]:
    """URL-dən fayl yolunu güvənli şəkildə al."""
    if not url.startswith("/uploads/content/"):
        return None
    name = url.split("/")[-1]
    path = UPLOAD_DIR / name
    # Directory traversal qorunması
    try:
        path.resolve().relative_to(UPLOAD_DIR.resolve())
        return path if path.exists() else None
    except ValueError:
        return None


async def _save_file(file: UploadFile) -> tuple[str, str, int]:
    """Faylı saxla → (url, original_name, size)"""
    mime = file.content_type or ""
    if mime not in ALLOWED_MIME:
        raise HTTPException(415, f"Dəstəklənməyən format: {mime}")
    data = await file.read()
    ext = Path(file.filename or "file").suffix.lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / unique_name
    dest.write_bytes(data)
    return f"/uploads/content/{unique_name}", file.filename or unique_name, len(data)


async def _get_content_or_404(content_id: str, teacher_id: str, db: AsyncSession) -> Content:
    res = await db.execute(
        select(Content).where(Content.id == content_id, Content.teacher_id == teacher_id)
    )
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Material tapılmadı")
    return item


# ── GET /content/teacher ──────────────────────────────────────────────────
@router.get("/teacher", response_model=list[ContentOut])
async def get_teacher_content(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    items_res = await db.execute(
        select(Content)
        .where(Content.teacher_id == current_user.id, Content.is_active == True)
        .order_by(Content.created_at.desc())
    )
    items = items_res.scalars().all()

    # Bütün class ID-lərini bir sorğuda al (N+1 yoxdur)
    all_ids: set[str] = set()
    for it in items:
        all_ids.update(_parse_class_ids(it.class_id))
    cls_map = await _batch_class_names(db, list(all_ids))

    # Attachment saylarını bir sorğuda al
    att_res = await db.execute(
        select(ContentAttachment.content_id)
        .where(ContentAttachment.content_id.in_([it.id for it in items]))
    )
    att_counts: dict[str, int] = {}
    for (cid,) in att_res.all():
        att_counts[cid] = att_counts.get(cid, 0) + 1

    return [_build_out(it, current_user.name, cls_map, att_counts.get(it.id, 0)) for it in items]


# ── POST /content/teacher ─────────────────────────────────────────────────
@router.post("/teacher", response_model=ContentOut, status_code=201)
async def create_content(
    body: ContentCreate,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    item = Content(
        teacher_id=current_user.id,
        title=body.title.strip(),
        description=body.description.strip() if body.description else None,
        content_type=body.content_type,
        url=body.url.strip() if body.url else None,
        subject=body.subject.strip() if body.subject else None,
        topic=body.topic.strip() if body.topic else None,
        class_id=_safe_class_id(body.class_ids),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    # RAG auto-indeksləmə — mətn/link materialları üçün
    try:
        from app.services import rag_service
        import asyncio
        text = f"{item.title}\n{item.description or ''}"
        if item.url and item.content_type not in ("image", "video"):
            text += f"\nURL: {item.url}"
        asyncio.create_task(rag_service.index_document(
            doc_id=rag_service._doc_id("content", item.id),
            text=text,
            metadata={"type": "content", "subject": item.subject or "", "topic": item.topic or ""},
        ))
    except Exception:
        pass

    all_ids = _parse_class_ids(item.class_id)
    cls_map = await _batch_class_names(db, all_ids)
    return _build_out(item, current_user.name, cls_map)


# ── POST /content/teacher/upload ──────────────────────────────────────────
@router.post("/teacher/upload", response_model=ContentOut, status_code=201)
async def upload_content(
    file: UploadFile = File(...),
    title: str = Form(...),
    subject: str = Form(""),
    topic: str = Form(""),
    description: str = Form(""),
    class_ids: str = Form(""),
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    url, fname, fsize = await _save_file(file)

    # class_ids JSON string olaraq gəlir: '["id1","id2"]' or ''
    try:
        parsed_ids = json.loads(class_ids) if class_ids.strip() else []
        if not isinstance(parsed_ids, list):
            parsed_ids = []
    except (json.JSONDecodeError, ValueError):
        parsed_ids = []

    item = Content(
        teacher_id=current_user.id,
        title=(title.strip() or fname),
        description=description.strip() or None,
        content_type=ALLOWED_MIME[file.content_type or ""],
        url=url,
        subject=subject.strip() or None,
        topic=topic.strip() or None,
        class_id=_safe_class_id(parsed_ids),
        file_name=fname,
        file_size=fsize,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    cls_map = await _batch_class_names(db, parsed_ids)
    return _build_out(item, current_user.name, cls_map)


# ── PATCH /content/teacher/{id} ───────────────────────────────────────────
@router.patch("/teacher/{content_id}", response_model=ContentOut)
async def update_content(
    content_id: str,
    body: ContentUpdate,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    item = await _get_content_or_404(content_id, current_user.id, db)

    if body.title is not None:       item.title       = body.title.strip()
    if body.description is not None: item.description = body.description.strip() or None
    if body.url is not None:         item.url         = body.url.strip() or None
    if body.subject is not None:     item.subject     = body.subject.strip() or None
    if body.topic is not None:       item.topic       = body.topic.strip() or None
    if body.class_ids is not None:   item.class_id    = _safe_class_id(body.class_ids)

    await db.commit()
    await db.refresh(item)

    all_ids = _parse_class_ids(item.class_id)
    cls_map = await _batch_class_names(db, all_ids)

    att_res = await db.execute(
        select(ContentAttachment.id).where(ContentAttachment.content_id == item.id)
    )
    att_count = len(att_res.scalars().all())
    return _build_out(item, current_user.name, cls_map, att_count)


# ── DELETE /content/teacher/{id} ─────────────────────────────────────────
@router.delete("/teacher/{content_id}", status_code=204)
async def delete_content(
    content_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    item = await _get_content_or_404(content_id, current_user.id, db)
    # Ana faylı sil
    if path := _safe_filename(item.url or ""):
        path.unlink(missing_ok=True)
    # Attachment fayllarını sil
    att_res = await db.execute(
        select(ContentAttachment).where(ContentAttachment.content_id == content_id)
    )
    for a in att_res.scalars().all():
        if p := _safe_filename(a.url):
            p.unlink(missing_ok=True)
    await db.delete(item)
    await db.commit()


# ── GET /content/student ──────────────────────────────────────────────────
@router.get("/student", response_model=list[ContentOut])
async def get_student_content(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stu_res = await db.execute(select(Student).where(Student.user_id == current_user.id))
    stu = stu_res.scalar_one_or_none()
    student_class_id = stu.class_id if stu else None

    # Repetitor şagirdidirsə → repetitorunun (müəllim) id-sini tap
    from app.models.repetitor import RepetitorStudent
    rs_res = await db.execute(
        select(RepetitorStudent.teacher_id)
        .where(RepetitorStudent.user_id == current_user.id).limit(1)
    )
    repetitor_teacher_id = rs_res.scalars().first()

    items_res = await db.execute(
        select(Content, User)
        .join(User, User.id == Content.teacher_id)
        .where(Content.is_active == True)
        .order_by(Content.created_at.desc())
    )
    rows = items_res.all()

    def _visible(c: Content) -> bool:
        # Repetitorunun bütün materialları (sinif hədəfindən asılı olmayaraq)
        if repetitor_teacher_id and c.teacher_id == repetitor_teacher_id:
            return True
        # Platform sinif məntiqi: hədəfsiz (null) → hamıya, ya da şagirdin sinfi daxildir
        ids = _parse_class_ids(c.class_id)
        if not ids:
            return True
        return bool(student_class_id and student_class_id in ids)

    visible = [(c, u) for c, u in rows if _visible(c)]

    all_ids: set[str] = set()
    for c, _ in visible:
        all_ids.update(_parse_class_ids(c.class_id))
    cls_map = await _batch_class_names(db, list(all_ids))

    return [_build_out(c, u.name, cls_map) for c, u in visible]


# ── GET /content/teacher/{id}/attachments ────────────────────────────────
@router.get("/teacher/{content_id}/attachments", response_model=list[AttachmentOut])
async def list_attachments(
    content_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    await _get_content_or_404(content_id, current_user.id, db)
    res = await db.execute(
        select(ContentAttachment)
        .where(ContentAttachment.content_id == content_id)
        .order_by(ContentAttachment.created_at)
    )
    return [_att_out(a) for a in res.scalars().all()]


# ── POST /content/teacher/{id}/attachments (link) ────────────────────────
@router.post("/teacher/{content_id}/attachments", response_model=AttachmentOut, status_code=201)
async def add_link_attachment(
    content_id: str,
    body: AttachmentLinkIn,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    await _get_content_or_404(content_id, current_user.id, db)
    if not body.url.strip():
        raise HTTPException(400, "URL boş ola bilməz")
    a = ContentAttachment(
        content_id=content_id,
        attachment_type="link",
        url=body.url.strip(),
        label=body.label,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return _att_out(a)


# ── POST /content/teacher/{id}/attachments/upload ────────────────────────
@router.post("/teacher/{content_id}/attachments/upload", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    content_id: str,
    file: UploadFile = File(...),
    label: str = Form(""),
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    await _get_content_or_404(content_id, current_user.id, db)
    url, fname, fsize = await _save_file(file)
    att_type = ALLOWED_MIME[file.content_type or ""]
    a = ContentAttachment(
        content_id=content_id,
        attachment_type=att_type,
        url=url,
        label=label.strip() or fname,
        file_name=fname,
        file_size=fsize,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return _att_out(a)


# ── DELETE /content/teacher/{id}/attachments/{att_id} ────────────────────
@router.delete("/teacher/{content_id}/attachments/{att_id}", status_code=204)
async def delete_attachment(
    content_id: str,
    att_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    await _get_content_or_404(content_id, current_user.id, db)
    res = await db.execute(
        select(ContentAttachment).where(
            ContentAttachment.id == att_id,
            ContentAttachment.content_id == content_id,
        )
    )
    a = res.scalar_one_or_none()
    if not a:
        raise HTTPException(404, "Əlavə tapılmadı")
    if p := _safe_filename(a.url):
        p.unlink(missing_ok=True)
    await db.delete(a)
    await db.commit()
