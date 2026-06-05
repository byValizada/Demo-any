from sqlalchemy import String, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
from app.database import Base
import uuid
from datetime import datetime, timezone


class AnnouncementHistory(Base):
    __tablename__ = "announcement_history"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    notif_type: Mapped[str] = mapped_column(String(20), default="info")
    target: Mapped[str] = mapped_column(String(20), default="all")     # "all" | "tenant"
    tenant_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tenant_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    roles: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)   # JSON-encoded list, e.g. '["teacher","student"]'
    sent_to: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_at: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)   # ISO datetime; None = send now
    is_sent: Mapped[int] = mapped_column(Integer, default=1)   # 1 = sent, 0 = pending scheduled
    created_at: Mapped[Optional[str]] = mapped_column(String(30), default=lambda: datetime.now(timezone.utc).isoformat())
