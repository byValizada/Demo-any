"""
Messages Router - /messages/*
"""
import uuid as _uuid
from pathlib import Path as _Path
from fastapi import APIRouter, Depends, Query, UploadFile, File, Form, HTTPException
from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.dependencies import require_role, require_not_demo_repetitor
from app.models.user import User
from app.models.message import Message
from app.models.class_model import Class

router = APIRouter(prefix="/messages", tags=["Messages"], dependencies=[Depends(require_not_demo_repetitor)])
require_any = require_role("student", "teacher", "parent", "admin", "superadmin")

_MSG_UPLOAD = _Path("uploads") / "messages"
_IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".heic", ".heif"}
_VID_EXT = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v", ".ogg"}


def _classify(mime: str, ext: str) -> str:
    if mime.startswith("image/") or ext in _IMG_EXT:
        return "image"
    if mime.startswith("video/") or ext in _VID_EXT:
        return "video"
    return "document"


async def _save_msg_file(file: UploadFile) -> tuple[str, str, str]:
    """Mesaj faylını saxla → (url, original_name, file_type). Hər fayl qəbul olunur."""
    _MSG_UPLOAD.mkdir(parents=True, exist_ok=True)
    ext = _Path(file.filename or "file").suffix.lower()
    ftype = _classify(file.content_type or "", ext)
    unique = f"{_uuid.uuid4().hex}{ext}"
    (_MSG_UPLOAD / unique).write_bytes(await file.read())
    return f"/uploads/messages/{unique}", (file.filename or unique), ftype


def _msg_out(m: Message, from_name: str, to_name: str) -> "MessageOut":
    return MessageOut(
        id=m.id, from_user_id=m.from_user_id, from_name=from_name,
        to_user_id=m.to_user_id, to_name=to_name,
        content=m.content or "", file_url=m.file_url, file_name=m.file_name, file_type=m.file_type,
        is_read=m.is_read, edited=m.edited_at is not None,
        created_at=m.created_at.strftime("%d.%m.%Y %H:%M") if m.created_at else "",
    )

class MessageOut(BaseModel):
    id: str
    from_user_id: str
    from_name: str
    to_user_id: str
    to_name: str
    content: str
    file_url: Optional[str] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    is_read: bool
    edited: bool = False
    created_at: str

class ConversationOut(BaseModel):
    other_user_id: str
    other_name: str
    other_role: str
    other_subject: Optional[str] = None
    last_message: str
    last_time: str
    unread_count: int

class MessageCreate(BaseModel):
    to_user_id: str
    content: str

def _last_preview(m: Message) -> str:
    if m.content:
        return m.content[:80]
    return {"image": "📷 Şəkil", "video": "🎬 Video", "document": "📎 Sənəd"}.get(m.file_type or "", "📎 Fayl")


@router.get("/conversations", response_model=list[ConversationOut])
async def get_conversations(
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    from app.models.message import MessageClear
    # Mənim təmizləmə kəsim nöqtələrim
    clr_res = await db.execute(
        select(MessageClear.other_user_id, MessageClear.cleared_at)
        .where(MessageClear.user_id == current_user.id)
    )
    clears = {oid: cat for oid, cat in clr_res.all()}

    result = await db.execute(
        select(Message)
        .where(or_(Message.from_user_id == current_user.id, Message.to_user_id == current_user.id))
        .order_by(Message.created_at.desc())
    )
    all_msgs = result.scalars().all()

    # Group by conversation partner — gizlədilmiş/təmizlənmiş mesajları nəzərə alma
    convs: dict[str, dict] = {}
    for msg in all_msgs:
        other_id = msg.to_user_id if msg.from_user_id == current_user.id else msg.from_user_id
        # "Özüm üçün sil"
        if msg.from_user_id == current_user.id and msg.deleted_by_sender:
            continue
        if msg.to_user_id == current_user.id and msg.deleted_by_receiver:
            continue
        # Söhbəti təmizlə (cutoff)
        cat = clears.get(other_id)
        if cat and msg.created_at and msg.created_at <= cat:
            continue
        if other_id not in convs:
            convs[other_id] = {"last": msg, "unread": 0}
        if not msg.is_read and msg.to_user_id == current_user.id:
            convs[other_id]["unread"] += 1

    out = []
    for other_id, data in convs.items():
        user_res = await db.execute(select(User).where(User.id == other_id))
        other = user_res.scalar_one_or_none()
        if not other:
            continue

        # Müəllim/admin üçün fənn məlumatı
        subject = None
        if other.role in ("teacher", "admin"):
            cls_res = await db.execute(
                select(Class.subject).where(Class.teacher_id == other.id).limit(1)
            )
            row = cls_res.first()
            if row:
                subject = row[0]

        msg = data["last"]
        out.append(ConversationOut(
            other_user_id=other_id,
            other_name=other.name,
            other_role=other.role,
            other_subject=subject,
            last_message=_last_preview(msg),
            last_time=msg.created_at.strftime("%d.%m.%Y %H:%M") if msg.created_at else "",
            unread_count=data["unread"],
        ))
    return out

@router.get("/contacts/list", response_model=list[dict])
async def get_contacts(
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    """Get list of users this user can message.
    Teacher/repetitor → yalnız öz sinifindəki şagirdlər.
    Student/parent    → eyni tenantdakı müəllimlər.
    """
    from app.models.student import Student
    from app.models.class_model import Class

    if current_user.role in ("teacher", "admin"):
        seen_ids: set[str] = set()
        users: list[User] = []

        # 1) Sinif şagirdləri
        cls_res = await db.execute(
            select(Class.id).where(Class.teacher_id == current_user.id)
        )
        class_ids = [r[0] for r in cls_res.all()]
        if class_ids:
            stu_res = await db.execute(
                select(User)
                .join(Student, Student.user_id == User.id)
                .where(Student.class_id.in_(class_ids), User.is_active == True)
            )
            for u in stu_res.scalars().all():
                if u.id not in seen_ids:
                    seen_ids.add(u.id); users.append(u)

        # 2) Repetitor şagirdləri (platform hesabı olan)
        from app.models.repetitor import RepetitorStudent as RS
        rep_res = await db.execute(
            select(User)
            .join(RS, RS.user_id == User.id)
            .where(RS.teacher_id == current_user.id, User.is_active == True)
        )
        for u in rep_res.scalars().all():
            if u.id not in seen_ids:
                seen_ids.add(u.id); users.append(u)

        # 3) Repetitor valideynləri (platform hesabı olan)
        rep_par = await db.execute(
            select(User)
            .join(RS, RS.parent_user_id == User.id)
            .where(RS.teacher_id == current_user.id, User.is_active == True)
        )
        for u in rep_par.scalars().all():
            if u.id not in seen_ids:
                seen_ids.add(u.id); users.append(u)

    else:
        # Şagird/valideyn → eyni tenantdakı müəllimlər
        result = await db.execute(
            select(User).where(
                User.tenant_id == current_user.tenant_id,
                User.id != current_user.id,
                User.is_active == True,
                User.role.in_(["teacher", "admin"]),
            )
        )
        users = result.scalars().all()

        # Hər müəllim üçün fənn məlumatını əlavə et
        out = []
        for u in users:
            subject = None
            cls_res = await db.execute(
                select(Class.subject).where(Class.teacher_id == u.id).limit(1)
            )
            row = cls_res.first()
            if row:
                subject = row[0]
            out.append({"id": u.id, "name": u.name, "role": u.role, "subject": subject})
        return out

    return [{"id": u.id, "name": u.name, "role": u.role, "subject": None} for u in users]

@router.get("/{other_user_id}", response_model=list[MessageOut])
async def get_thread(
    other_user_id: str,
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    from app.models.message import MessageClear
    # Söhbət təmizlənibsə kəsim nöqtəsi
    clr_res = await db.execute(
        select(MessageClear.cleared_at).where(
            and_(MessageClear.user_id == current_user.id,
                 MessageClear.other_user_id == other_user_id)
        ).limit(1)
    )
    cleared_at = clr_res.scalars().first()

    conds = [or_(
        and_(Message.from_user_id == current_user.id, Message.to_user_id == other_user_id),
        and_(Message.from_user_id == other_user_id, Message.to_user_id == current_user.id),
    )]
    if cleared_at:
        conds.append(Message.created_at > cleared_at)

    result = await db.execute(
        select(Message).where(and_(*conds)).order_by(Message.created_at.asc())
    )
    all_msgs = result.scalars().all()

    # "Özüm üçün sil" edilənləri gizlət
    msgs = [
        m for m in all_msgs
        if not (m.from_user_id == current_user.id and m.deleted_by_sender)
        and not (m.to_user_id == current_user.id and m.deleted_by_receiver)
    ]

    # Mark incoming as read
    for msg in msgs:
        if msg.to_user_id == current_user.id and not msg.is_read:
            msg.is_read = True
    await db.commit()

    # Fetch user names
    me_res = await db.execute(select(User).where(User.id == current_user.id))
    me = me_res.scalar_one_or_none()
    other_res = await db.execute(select(User).where(User.id == other_user_id))
    other = other_res.scalar_one_or_none()

    return [
        _msg_out(
            m,
            from_name=(me.name if m.from_user_id == current_user.id else (other.name if other else "?")),
            to_name=(other.name if m.to_user_id == other_user_id else (me.name if me else "?")),
        )
        for m in msgs
    ]

@router.post("", response_model=MessageOut, status_code=201)
async def send_message(
    to_user_id: str = Form(...),
    content: str = Form(""),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    to_res = await db.execute(select(User).where(User.id == to_user_id))
    to_user = to_res.scalar_one_or_none()
    if not to_user:
        raise HTTPException(404, "İstifadəçi tapılmadı")

    if not content.strip() and not (file and file.filename):
        raise HTTPException(400, "Mesaj və ya fayl daxil edin")

    file_url = file_name = file_type = None
    if file and file.filename:
        file_url, file_name, file_type = await _save_msg_file(file)

    msg = Message(
        from_user_id=current_user.id,
        to_user_id=to_user_id,
        content=content.strip() or None,
        file_url=file_url, file_name=file_name, file_type=file_type,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return _msg_out(msg, current_user.name, to_user.name)


class MessageEdit(BaseModel):
    content: str


@router.patch("/{msg_id}", response_model=MessageOut)
async def edit_message(
    msg_id: str,
    body: MessageEdit,
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    """Öz göndərdiyi mesajı redaktə et (yalnız göndərən)."""
    from fastapi import HTTPException
    from datetime import datetime, timezone
    if not body.content.strip():
        raise HTTPException(400, "Mesaj boş ola bilməz")

    res = await db.execute(select(Message).where(Message.id == msg_id).limit(1))
    m = res.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Mesaj tapılmadı")
    if m.from_user_id != current_user.id:
        raise HTTPException(403, "Yalnız öz mesajınızı redaktə edə bilərsiniz")

    m.content = body.content.strip()
    m.edited_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(m)

    other_res = await db.execute(select(User).where(User.id == m.to_user_id))
    other = other_res.scalar_one_or_none()
    return _msg_out(m, current_user.name, other.name if other else "?")


async def _user_cleared_after(db: AsyncSession, user_id: str, other_user_id: str, created_at) -> bool:
    """İstifadəçi bu söhbəti mesajdan sonrakı vaxtda təmizləyibmi?"""
    from app.models.message import MessageClear
    if not created_at:
        return False
    res = await db.execute(
        select(MessageClear.cleared_at).where(
            and_(MessageClear.user_id == user_id, MessageClear.other_user_id == other_user_id)
        ).limit(1)
    )
    c = res.scalars().first()
    return bool(c and c >= created_at)


async def _purge_if_both_hidden(db: AsyncSession, m: Message) -> bool:
    """Mesaj HƏR İKİ tərəfdən gizlədilibsə (flag və ya təmizləmə) bazadan tam sil — yer tutmasın."""
    from_hidden = m.deleted_by_sender or await _user_cleared_after(db, m.from_user_id, m.to_user_id, m.created_at)
    to_hidden = m.deleted_by_receiver or await _user_cleared_after(db, m.to_user_id, m.from_user_id, m.created_at)
    if from_hidden and to_hidden:
        await db.delete(m)
        return True
    return False


@router.delete("/{msg_id}", status_code=204)
async def delete_message(
    msg_id: str,
    scope: str = Query("me", regex="^(me|both)$"),
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    """Mesaj sil.
    - scope=me  → yalnız öz görünüşümdən gizlət (göndərən və ya alan edə bilər)
    - scope=both → bazadan tam sil (YALNIZ göndərən, öz mesajı üçün)
    Hər iki tərəf özü üçün gizlədibsə mesaj avtomatik bazadan silinir."""
    from fastapi import HTTPException
    res = await db.execute(select(Message).where(Message.id == msg_id).limit(1))
    m = res.scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Mesaj tapılmadı")

    is_sender = m.from_user_id == current_user.id
    is_receiver = m.to_user_id == current_user.id
    if not (is_sender or is_receiver):
        raise HTTPException(403, "İcazə yoxdur")

    if scope == "both":
        # Hər iki tərəfdən silmək yalnız göndərənə icazəlidir
        if not is_sender:
            raise HTTPException(400, "Gələn mesajı yalnız özünüz üçün silə bilərsiniz")
        await db.delete(m)
        await db.commit()
        return

    # scope == "me" — öz tərəfimdən gizlət (gedən və ya gələn)
    if is_sender:
        m.deleted_by_sender = True
    if is_receiver:
        m.deleted_by_receiver = True
    await db.flush()
    await _purge_if_both_hidden(db, m)
    await db.commit()


@router.post("/{other_user_id}/clear", status_code=204)
async def clear_conversation(
    other_user_id: str,
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    """Söhbəti yalnız mənim ekranımdan təmizlə — mesajlar bazada qalır, qarşı tərəf görür.
    Hər iki tərəf təmizləyibsə (və ya gizlədibsə) mesajlar bazadan silinir."""
    from datetime import datetime, timezone
    from app.models.message import MessageClear
    now = datetime.now(timezone.utc)
    res = await db.execute(
        select(MessageClear).where(
            and_(MessageClear.user_id == current_user.id,
                 MessageClear.other_user_id == other_user_id)
        ).limit(1)
    )
    clr = res.scalar_one_or_none()
    if clr:
        clr.cleared_at = now
    else:
        db.add(MessageClear(user_id=current_user.id, other_user_id=other_user_id, cleared_at=now))
    await db.flush()

    # Bu söhbətdəki mesajlardan hər iki tərəfdən gizli olanları bazadan sil
    conv_res = await db.execute(
        select(Message).where(or_(
            and_(Message.from_user_id == current_user.id, Message.to_user_id == other_user_id),
            and_(Message.from_user_id == other_user_id, Message.to_user_id == current_user.id),
        ))
    )
    for m in conv_res.scalars().all():
        await _purge_if_both_hidden(db, m)

    await db.commit()
