from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
from app.database import Base
import uuid
from datetime import datetime, timezone


class LoginLog(Base):
    __tablename__ = "login_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    user_name: Mapped[str] = mapped_column(String(200), nullable=False)
    user_role: Mapped[str] = mapped_column(String(50), nullable=False)
    tenant_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tenant_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    success: Mapped[int] = mapped_column(Integer, default=1)   # 1=success, 0=failed
    created_at: Mapped[Optional[str]] = mapped_column(String(30), default=lambda: datetime.now(timezone.utc).isoformat())
