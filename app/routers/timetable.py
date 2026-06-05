"""
Timetable Router - /timetable/*
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.dependencies import require_role, require_not_demo_repetitor
from app.models.user import User
from app.models.timetable import TimetableEntry
from app.models.class_model import Class
from app.models.student import Student

router = APIRouter(prefix="/timetable", tags=["Timetable"], dependencies=[Depends(require_not_demo_repetitor)])
require_teacher = require_role("teacher", "admin", "superadmin")
require_student = require_role("student", "admin", "superadmin")
require_any = require_role("student", "teacher", "parent", "admin", "superadmin")

class TimetableEntryOut(BaseModel):
    id: str
    class_id: str
    class_name: str
    day_of_week: int
    period: int
    start_time: str
    end_time: str
    subject: str
    room: Optional[str]

class TimetableCreate(BaseModel):
    class_id: str
    day_of_week: int
    period: int
    start_time: str
    end_time: str
    subject: str
    room: Optional[str] = None

@router.get("/student", response_model=list[TimetableEntryOut])
async def get_student_timetable(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    stu_res = await db.execute(select(Student).where(Student.user_id == current_user.id))
    stu = stu_res.scalar_one_or_none()
    if not stu or not stu.class_id:
        return []

    cls_res = await db.execute(select(Class).where(Class.id == stu.class_id))
    cls = cls_res.scalar_one_or_none()

    result = await db.execute(
        select(TimetableEntry)
        .where(TimetableEntry.class_id == stu.class_id)
        .order_by(TimetableEntry.day_of_week, TimetableEntry.period)
    )
    entries = result.scalars().all()
    return [
        TimetableEntryOut(
            id=e.id, class_id=e.class_id, class_name=cls.name if cls else "",
            day_of_week=e.day_of_week, period=e.period,
            start_time=e.start_time, end_time=e.end_time,
            subject=e.subject, room=e.room,
        )
        for e in entries
    ]

@router.get("/teacher", response_model=list[TimetableEntryOut])
async def get_teacher_timetable(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    cls_res = await db.execute(select(Class).where(Class.teacher_id == current_user.id))
    classes = cls_res.scalars().all()
    class_map = {c.id: c.name for c in classes}
    class_ids = list(class_map.keys())
    if not class_ids:
        return []

    result = await db.execute(
        select(TimetableEntry)
        .where(TimetableEntry.class_id.in_(class_ids))
        .order_by(TimetableEntry.day_of_week, TimetableEntry.period)
    )
    entries = result.scalars().all()
    return [
        TimetableEntryOut(
            id=e.id, class_id=e.class_id, class_name=class_map.get(e.class_id, ""),
            day_of_week=e.day_of_week, period=e.period,
            start_time=e.start_time, end_time=e.end_time,
            subject=e.subject, room=e.room,
        )
        for e in entries
    ]

@router.post("", response_model=TimetableEntryOut, status_code=201)
async def create_entry(
    body: TimetableCreate,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException
    cls_res = await db.execute(
        select(Class).where(Class.id == body.class_id, Class.teacher_id == current_user.id)
    )
    cls = cls_res.scalar_one_or_none()
    if not cls:
        raise HTTPException(403, "Bu sinif sizin deyil")

    entry = TimetableEntry(
        class_id=body.class_id, day_of_week=body.day_of_week,
        period=body.period, start_time=body.start_time, end_time=body.end_time,
        subject=body.subject, room=body.room,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return TimetableEntryOut(
        id=entry.id, class_id=entry.class_id, class_name=cls.name,
        day_of_week=entry.day_of_week, period=entry.period,
        start_time=entry.start_time, end_time=entry.end_time,
        subject=entry.subject, room=entry.room,
    )

@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: str,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException
    entry_res = await db.execute(select(TimetableEntry).where(TimetableEntry.id == entry_id))
    entry = entry_res.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Tapilmadi")
    # Verify ownership
    cls_res = await db.execute(select(Class).where(Class.id == entry.class_id, Class.teacher_id == current_user.id))
    if not cls_res.scalar_one_or_none():
        raise HTTPException(403, "Icaze yoxdur")
    await db.delete(entry)
    await db.commit()
