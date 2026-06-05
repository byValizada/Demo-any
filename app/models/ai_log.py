from sqlalchemy import String, ForeignKey, DateTime, Text, Boolean, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
import uuid


class AILog(Base):
    """
    Hər AI sorğusunu saxlayırıq.
    Məqsəd: öz modelimizi öyrətmək üçün data toplamaq.
    """
    __tablename__ = "ai_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)

    # Sorğu məlumatları
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # cerebras | groq | gemini | openrouter
    model: Mapped[str] = mapped_column(String(100), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)

    # Keyfiyyət qiymətləndirməsi — öyrənmə üçün
    was_edited: Mapped[bool] = mapped_column(Boolean, default=False)   # müəllim dəyişdirdimi?
    was_accepted: Mapped[bool] = mapped_column(Boolean, default=True)  # qəbul edildi?

    purpose: Mapped[str] = mapped_column(String(50), nullable=True)    # question_gen | answer_check | feedback
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
