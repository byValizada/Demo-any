from sqlalchemy import String, ForeignKey, DateTime, Integer, Boolean, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
import uuid


class DailyChallengeSubmission(Base):
    """Şagirdin gündəlik tapşırığa verdiyi cavab."""
    __tablename__ = "daily_challenge_submissions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id: Mapped[str] = mapped_column(String, ForeignKey("students.id"), nullable=False)
    challenge_date: Mapped[str] = mapped_column(String(10), nullable=False)   # "YYYY-MM-DD"
    question_id: Mapped[str] = mapped_column(String, nullable=True)           # sual bankından
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
