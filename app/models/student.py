from sqlalchemy import String, ForeignKey, DateTime, Integer, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import uuid


class Student(Base):
    __tablename__ = "students"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Eyni şagird (user_id) müxtəlif siniflərdə iştirak edə bilər (fərqli fənlər)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    class_id: Mapped[str] = mapped_column(String, ForeignKey("classes.id"), nullable=True)
    parent_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)

    # Gamification
    xp: Mapped[int] = mapped_column(Integer, default=0)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    earned_badges: Mapped[list] = mapped_column(JSON, default=list)   # ["first_exam", "xp_500", ...]
    last_active_date: Mapped[str] = mapped_column(String(10), nullable=True)  # "YYYY-MM-DD"

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    # Relations
    user: Mapped["User"] = relationship("User", back_populates="student_profile", foreign_keys=[user_id])
    class_: Mapped["Class"] = relationship("Class", back_populates="students")
    exam_results: Mapped[list["ExamResult"]] = relationship("ExamResult", back_populates="student")
    homework_submissions: Mapped[list["HomeworkSubmission"]] = relationship("HomeworkSubmission", back_populates="student")
