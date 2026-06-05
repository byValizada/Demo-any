from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
import uuid

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    from_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=True)
    file_url: Mapped[str] = mapped_column(Text, nullable=True)            # əlavə fayl (şəkil/video/sənəd)
    file_name: Mapped[str] = mapped_column(String(300), nullable=True)
    file_type: Mapped[str] = mapped_column(String(20), nullable=True)     # image | video | document
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    # "Özüm üçün sil" — mesaj göndərənin / alanın görünüşündən gizlənir (bazada qalır)
    deleted_by_sender: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_by_receiver: Mapped[bool] = mapped_column(Boolean, default=False)
    edited_at: Mapped[DateTime] = mapped_column(DateTime, nullable=True)   # redaktə olunubsa
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class MessageClear(Base):
    """İstifadəçinin bir söhbəti 'təmizləmə' kəsim nöqtəsi.
    cleared_at-dan əvvəlki mesajlar yalnız bu istifadəçidən gizlənir — bazada qalır."""
    __tablename__ = "message_clears"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    other_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    cleared_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)
