from sqlalchemy import String, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import uuid


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False)
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(50), nullable=False)   # məs. "10A"
    subject: Mapped[str] = mapped_column(String(100), nullable=False) # məs. "Riyaziyyat"
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    # Relations
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="classes")
    students: Mapped[list["Student"]] = relationship("Student", back_populates="class_")
    exams: Mapped[list["Exam"]] = relationship("Exam", back_populates="class_")
    homeworks: Mapped[list["Homework"]] = relationship("Homework", back_populates="class_")
