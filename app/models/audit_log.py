from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
from app.database import Base
import uuid
from datetime import datetime, timezone


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)   # e.g. "activate_user", "delete_tenant"
    target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)   # "user" | "tenant" | "subscription"
    target_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(String(30), default=lambda: datetime.now(timezone.utc).isoformat())
