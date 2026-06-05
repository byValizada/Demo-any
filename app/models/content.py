import uuid
from sqlalchemy import String, Text, ForeignKey, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy import DateTime
from app.database import Base


class Content(Base):
    __tablename__ = "contents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    class_id: Mapped[str] = mapped_column(String, nullable=True)   # JSON array or single id
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(String(30), default="link")
    url: Mapped[str] = mapped_column(Text, nullable=True)
    subject: Mapped[str] = mapped_column(String(100), nullable=True)
    topic: Mapped[str] = mapped_column(String(200), nullable=True)
    file_name: Mapped[str] = mapped_column(String(300), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    attachments: Mapped[list["ContentAttachment"]] = relationship(
        "ContentAttachment", back_populates="content",
        cascade="all, delete-orphan", order_by="ContentAttachment.created_at",
    )


class ContentAttachment(Base):
    """Bir content-ə bağlı əlavə fayllar / linklər."""
    __tablename__ = "content_attachments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    content_id: Mapped[str] = mapped_column(String, ForeignKey("contents.id"), nullable=False)
    attachment_type: Mapped[str] = mapped_column(String(20), nullable=False)  # link|document|image|video
    url: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=True)   # istifadəçi adı
    file_name: Mapped[str] = mapped_column(String(300), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    content: Mapped["Content"] = relationship("Content", back_populates="attachments")
