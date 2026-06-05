from sqlalchemy import String, ForeignKey, DateTime, Boolean, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import uuid


class Homework(Base):
    __tablename__ = "homeworks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    class_id: Mapped[str] = mapped_column(String, ForeignKey("classes.id"), nullable=False)
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    deadline: Mapped[DateTime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    attachments: Mapped[str] = mapped_column(Text, default="[]", nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    # Relations
    class_: Mapped["Class"] = relationship("Class", back_populates="homeworks")
    submissions: Mapped[list["HomeworkSubmission"]] = relationship("HomeworkSubmission", back_populates="homework", cascade="all, delete-orphan")


class HomeworkSubmission(Base):
    __tablename__ = "homework_submissions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    homework_id: Mapped[str] = mapped_column(String, ForeignKey("homeworks.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(String, ForeignKey("students.id"), nullable=False)

    answer: Mapped[str] = mapped_column(Text, nullable=True)
    file_url: Mapped[str] = mapped_column(Text, nullable=True)         # yüklənmiş cavab faylı
    file_name: Mapped[str] = mapped_column(String(300), nullable=True) # orijinal fayl adı
    grade: Mapped[str] = mapped_column(String(10), nullable=True)     # 1-10 qiymət
    feedback: Mapped[str] = mapped_column(Text, nullable=True)         # müəllim rəyi
    submitted_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    graded_at: Mapped[DateTime] = mapped_column(DateTime, nullable=True)

    # Relations
    homework: Mapped["Homework"] = relationship("Homework", back_populates="submissions")
    student: Mapped["Student"] = relationship("Student", back_populates="homework_submissions")
