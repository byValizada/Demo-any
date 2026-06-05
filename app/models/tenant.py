from sqlalchemy import String, Boolean, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from app.database import Base
import uuid


class Tenant(Base):
    """
    Hər məktəb və ya repetitor bir tenant-dır.
    Multi-tenant: hər tenant yalnız öz datasını görür.
    """
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(20), default="school")  # school | repetitor
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    # 0 = limitsiz
    student_limit: Mapped[int] = mapped_column(Integer, default=0)
    teacher_limit: Mapped[int] = mapped_column(Integer, default=0)   # yalnız korporativ üçün mənalı

    # Subscription
    plan: Mapped[str] = mapped_column(String(20), default="free")           # free | basic | pro
    plan_expires_at: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)   # ISO date string
    monthly_fee: Mapped[int] = mapped_column(Integer, default=0)            # AZN qəpik (100 = 1.00 AZN)

    # AI limits (0 = unlimited)
    ai_daily_limit: Mapped[int] = mapped_column(Integer, default=0)

    # Feature flags — JSON string e.g. '{"ai_tutor":true,"flashcards":false}'
    features: Mapped[str] = mapped_column(String(500), default='{}')

    # Branding
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    primary_color: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # hex e.g. "#2196f3"

    # Relations
    users: Mapped[list["User"]] = relationship("User", back_populates="tenant")
    classes: Mapped[list["Class"]] = relationship("Class", back_populates="tenant")
