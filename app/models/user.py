from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import uuid


class User(Base):
    """
    Bütün istifadəçilər: müəllim, şagird, valideyn, admin
    Role sistemi ilə idarə olunur.
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False)

    # Əsas məlumatlar
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # Rol: teacher | student | parent | admin
    role: Mapped[str] = mapped_column(String(20), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    student_limit: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    avatar_url: Mapped[str] = mapped_column(Text, nullable=True)  # base64 data URL or path
    subjects_json: Mapped[str] = mapped_column(Text, nullable=True)  # JSON array of subjects, e.g. '["Riyaziyyat","Fizika"]'
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relations
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="users")
    student_profile: Mapped["Student"] = relationship(
        "Student", back_populates="user", uselist=False,
        foreign_keys="Student.user_id"
    )
