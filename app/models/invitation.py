from sqlalchemy import String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import uuid


class Invitation(Base):
    """
    Dəvət sistemi — müəllim token yaradır, şagird/valideyn qeydiyyatdan keçir.
    """
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    class_id: Mapped[str] = mapped_column(String, ForeignKey("classes.id"), nullable=True)

    # Rola görə dəvət: student | parent | teacher
    role: Mapped[str] = mapped_column(String(20), nullable=False)

    # Unikal token (32 simvol)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    # İstifadə vəziyyəti
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    used_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)

    expires_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    # Relations
    tenant: Mapped["Tenant"] = relationship("Tenant")
    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])
    used_by_user: Mapped["User"] = relationship("User", foreign_keys=[used_by])
    class_: Mapped["Class"] = relationship("Class")
