"""
Notifications Router - /notifications/*
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.dependencies import require_role
from app.models.user import User
from app.models.notification import Notification

router = APIRouter(prefix="/notifications", tags=["Notifications"])
require_any = require_role("student", "teacher", "parent", "admin", "superadmin")

class NotifOut(BaseModel):
    id: str
    title: str
    description: Optional[str]
    type: str
    is_read: bool
    created_at: str

class NotifCreate(BaseModel):
    user_id: str
    title: str
    description: Optional[str] = None
    type: str = "info"

@router.get("", response_model=list[NotifOut])
async def get_my_notifications(
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    notifs = result.scalars().all()
    return [
        NotifOut(
            id=n.id, title=n.title, description=n.description,
            type=n.type, is_read=n.is_read,
            created_at=n.created_at.strftime("%d.%m.%Y %H:%M") if n.created_at else "",
        )
        for n in notifs
    ]

@router.patch("/{notif_id}/read")
async def mark_read(
    notif_id: str,
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification).where(Notification.id == notif_id, Notification.user_id == current_user.id)
    )
    n = result.scalar_one_or_none()
    if n:
        n.is_read = True
        await db.commit()
    return {"ok": True}

@router.patch("/read-all")
async def mark_all_read(
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification).where(Notification.user_id == current_user.id, Notification.is_read == False)
    )
    notifs = result.scalars().all()
    for n in notifs:
        n.is_read = True
    await db.commit()
    return {"ok": True, "count": len(notifs)}


@router.delete("/clear")
async def clear_all_notifications(
    current_user: User = Depends(require_any),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification).where(Notification.user_id == current_user.id)
    )
    for n in result.scalars().all():
        await db.delete(n)
    await db.commit()
    return {"ok": True}
