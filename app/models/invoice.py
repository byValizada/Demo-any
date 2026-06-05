from sqlalchemy import String, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional
from app.database import Base
import uuid
from datetime import datetime, timezone


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    tenant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)       # YYYY-MM
    amount: Mapped[int] = mapped_column(Integer, default=0)              # qəpik (100 = 1.00 AZN)
    status: Mapped[str] = mapped_column(String(20), default="unpaid")   # paid | unpaid | cancelled
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(String(30), default=lambda: datetime.now(timezone.utc).isoformat())
    paid_at: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
