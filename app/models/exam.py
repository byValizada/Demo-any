from sqlalchemy import String, ForeignKey, DateTime, Integer, Float, JSON, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import uuid


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    class_id: Mapped[str] = mapped_column(String, ForeignKey("classes.id"), nullable=False)
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    scheduled_at: Mapped[DateTime] = mapped_column(DateTime, nullable=True)
    auto_activated: Mapped[bool] = mapped_column(Boolean, default=False)  # planlaşdırıcı işlədib
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    # Relations
    class_: Mapped["Class"] = relationship("Class", back_populates="exams")
    questions: Mapped[list["Question"]] = relationship("Question", back_populates="exam", cascade="all, delete-orphan")
    results: Mapped[list["ExamResult"]] = relationship("ExamResult", back_populates="exam")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    exam_id: Mapped[str] = mapped_column(String, ForeignKey("exams.id"), nullable=False)

    text: Mapped[str] = mapped_column(String(2000), nullable=False)
    type: Mapped[str] = mapped_column(String(20), default="mcq")  # mcq | open | truefalse
    options: Mapped[dict] = mapped_column(JSON, nullable=True)     # MCQ seçimləri
    correct_answer: Mapped[str] = mapped_column(String(500), nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=1)
    difficulty: Mapped[str] = mapped_column(String(10), default="medium")  # easy | medium | hard

    # AI tərəfindən yaradıldısa — öyrənmə üçün saxlayırıq
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_provider: Mapped[str] = mapped_column(String(50), nullable=True)

    # Relations
    exam: Mapped["Exam"] = relationship("Exam", back_populates="questions")


class ExamResult(Base):
    __tablename__ = "exam_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    exam_id: Mapped[str] = mapped_column(String, ForeignKey("exams.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(String, ForeignKey("students.id"), nullable=False)

    score: Mapped[float] = mapped_column(Float, nullable=False)
    max_score: Mapped[float] = mapped_column(Float, nullable=False)
    percentage: Mapped[float] = mapped_column(Float, nullable=False)
    answers: Mapped[dict] = mapped_column(JSON, nullable=True)  # {question_id: answer}
    manual_grades: Mapped[dict] = mapped_column(JSON, nullable=True)  # açıq suallar: {question_id: verilən_bal}
    violations: Mapped[int] = mapped_column(Integer, default=0)  # köçürmə pozuntu sayı
    submitted_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    # Relations
    exam: Mapped["Exam"] = relationship("Exam", back_populates="results")
    student: Mapped["Student"] = relationship("Student", back_populates="exam_results")
