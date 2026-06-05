from sqlalchemy import String, ForeignKey, DateTime, Integer, Boolean, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import uuid


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(300), nullable=True)   # qısa təsvir (Udemy subtitle)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    level: Mapped[str] = mapped_column(String(20), default="beginner")  # beginner | intermediate | advanced
    cover_color: Mapped[str] = mapped_column(String(20), default="#2196F3")  # tema rəngi
    cover_image: Mapped[str] = mapped_column(String(500), nullable=True)      # üzqabığı şəkli URL
    objectives: Mapped[list] = mapped_column(JSON, default=list)        # "Nə öyrənəcəksən" siyahısı
    tags: Mapped[list] = mapped_column(JSON, default=list)              # axtarış/kateqoriya teqləri
    prerequisite_id: Mapped[str] = mapped_column(String, nullable=True) # önşərt kurs id
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    assignment_mode: Mapped[str] = mapped_column(String(20), default="public")  # public | assigned
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    modules: Mapped[list["CourseModule"]] = relationship(
        "CourseModule", back_populates="course",
        cascade="all, delete-orphan", order_by="CourseModule.order_index"
    )


class CourseModule(Base):
    __tablename__ = "course_modules"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    quiz: Mapped[list] = mapped_column(JSON, default=list)   # [{q, options:[...], correct: idx}]

    course: Mapped["Course"] = relationship("Course", back_populates="modules")
    lessons: Mapped[list["Lesson"]] = relationship(
        "Lesson", back_populates="module",
        cascade="all, delete-orphan", order_by="Lesson.order_index"
    )


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    module_id: Mapped[str] = mapped_column(String, ForeignKey("course_modules.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=True)      # Markdown mətn
    lesson_type: Mapped[str] = mapped_column(String(20), default="text")  # text | video | document | link
    url: Mapped[str] = mapped_column(String(500), nullable=True)   # video/sənəd/link üçün
    file_name: Mapped[str] = mapped_column(String(300), nullable=True)  # yüklənmiş faylın adı
    resources: Mapped[list] = mapped_column(JSON, default=list)    # [{url, name}] əlavə resurslar
    is_preview: Mapped[bool] = mapped_column(Boolean, default=False)  # pulsuz/kilidsiz önizləmə
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    duration_min: Mapped[int] = mapped_column(Integer, default=5)

    module: Mapped["CourseModule"] = relationship("CourseModule", back_populates="lessons")
    progress: Mapped[list["LessonProgress"]] = relationship("LessonProgress", back_populates="lesson", cascade="all, delete-orphan")


class LessonProgress(Base):
    __tablename__ = "lesson_progress"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    lesson_id: Mapped[str] = mapped_column(String, ForeignKey("lessons.id"), nullable=False)
    completed_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    lesson: Mapped["Lesson"] = relationship("Lesson", back_populates="progress")


class CourseReview(Base):
    """Şagirdin kursa verdiyi reytinq + şərh."""
    __tablename__ = "course_reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, default=5)   # 1-5 ulduz
    comment: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class CourseAssignment(Base):
    """Kursun konkret şagirdə təyinatı (assigned rejimi üçün)."""
    __tablename__ = "course_assignments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)


class CourseFavorite(Base):
    """Şagirdin sevimli kursları."""
    __tablename__ = "course_favorites"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)


class ModuleQuizResult(Base):
    """Şagirdin modul quizinə verdiyi nəticə."""
    __tablename__ = "module_quiz_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    module_id: Mapped[str] = mapped_column(String, ForeignKey("course_modules.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0)       # 0-100 %
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class LessonNote(Base):
    """Şagirdin dərsə yazdığı şəxsi qeyd (hər dərsə bir qeyd)."""
    __tablename__ = "lesson_notes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    lesson_id: Mapped[str] = mapped_column(String, ForeignKey("lessons.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=True)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class LessonComment(Base):
    """Dərs sual-cavab: parent_id=None → sual, dolu → cavab."""
    __tablename__ = "lesson_comments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    lesson_id: Mapped[str] = mapped_column(String, ForeignKey("lessons.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    parent_id: Mapped[str] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class CourseLastViewed(Base):
    """Şagirdin kursda son baxdığı dərs — 'Davam et' üçün."""
    __tablename__ = "course_last_viewed"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    lesson_id: Mapped[str] = mapped_column(String, ForeignKey("lessons.id"), nullable=True)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
