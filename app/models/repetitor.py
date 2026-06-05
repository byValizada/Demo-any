"""
Repetitor Models
----------------
Fərdi repetitor müəllimlər üçün şagird, seans və ödəniş modelləri.
Bu modellər mövcud teacher/student/class sistemindən tamamilə müstəqildir.
"""

from sqlalchemy import String, ForeignKey, DateTime, Integer, Text, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import uuid


class RepetitorClass(Base):
    """Repetitorun yaratdığı sinif/qrup (məs. '9-A', 'Riyaziyyat qrupu')."""
    __tablename__ = "repetitor_classes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class RepetitorSubject(Base):
    """Repetitorun tədris etdiyi fənlər."""
    __tablename__ = "repetitor_subjects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class RepetitorStudent(Base):
    """Repetitorun öz şagird siyahısı (User hesabından asılı deyil)."""
    __tablename__ = "repetitor_students"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    # Şagirdin login hesabı (User). Null = hesabı yoxdur.
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    # Valideynin login hesabı (User, role=parent). Null = hesabı yoxdur.
    parent_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    grade: Mapped[str] = mapped_column(String(20), nullable=True)   # sinif/kurs
    hourly_rate: Mapped[int] = mapped_column(Integer, default=0)    # qepik (100 = 1 AZN)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1)      # 1=aktiv, 0=arxivdə

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    # Relations
    sessions: Mapped[list["RepetitorSession"]] = relationship(
        "RepetitorSession", back_populates="student", cascade="all, delete-orphan"
    )
    payments: Mapped[list["RepetitorPayment"]] = relationship(
        "RepetitorPayment", back_populates="student", cascade="all, delete-orphan"
    )


class RepetitorSession(Base):
    """Repetitor seansı (dərs)."""
    __tablename__ = "repetitor_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(String, ForeignKey("repetitor_students.id"), nullable=False)

    subject: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    scheduled_at: Mapped[str] = mapped_column(String(30), nullable=False)   # ISO datetime
    duration_min: Mapped[int] = mapped_column(Integer, default=60)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")    # scheduled|completed|cancelled
    score: Mapped[int] = mapped_column(Integer, nullable=True)              # 0-100 (completed seans üçün)
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    # Relations
    student: Mapped["RepetitorStudent"] = relationship("RepetitorStudent", back_populates="sessions")


class RepetitorPayment(Base):
    """Repetitor ödənişi — aylıq və ya seans əsaslı."""
    __tablename__ = "repetitor_payments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(String, ForeignKey("repetitor_students.id"), nullable=False)

    amount: Mapped[int] = mapped_column(Integer, nullable=False)    # qepik — ümumi gözlənilən
    paid_amount: Mapped[int] = mapped_column(Integer, default=0)    # qepik — indiyədək ödənilən (qismi ödəniş)
    method: Mapped[str] = mapped_column(String(20), nullable=True)  # cash|card|transfer
    month: Mapped[str] = mapped_column(String(7), nullable=False)   # "2025-05"
    payment_date: Mapped[str] = mapped_column(String(10), nullable=True)  # "2025-05-15"
    status: Mapped[str] = mapped_column(String(10), default="unpaid")  # paid|partial|unpaid
    paid_at: Mapped[str] = mapped_column(String(30), nullable=True)
    note: Mapped[str] = mapped_column(String(300), nullable=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    # Relations
    student: Mapped["RepetitorStudent"] = relationship("RepetitorStudent", back_populates="payments")


class RepetitorExpense(Base):
    """Repetitorun xərci — kirayə, material, reklam və s. (xalis mənfəət üçün)."""
    __tablename__ = "repetitor_expenses"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    amount: Mapped[int] = mapped_column(Integer, nullable=False)        # qepik
    category: Mapped[str] = mapped_column(String(40), default="other")  # rent|materials|ads|software|transport|other
    date: Mapped[str] = mapped_column(String(10), nullable=False)       # "2026-05-15"
    note: Mapped[str] = mapped_column(String(300), nullable=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class RepetitorDailyGrade(Base):
    """Repetitorun şagirdinə verdiyi günlük qiymət."""
    __tablename__ = "repetitor_daily_grades"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(String, ForeignKey("repetitor_students.id"), nullable=False)

    subject: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    grade: Mapped[int] = mapped_column(Integer, nullable=False)   # 1-10
    date: Mapped[str] = mapped_column(String(10), nullable=False) # "2025-05-26"
    note: Mapped[str] = mapped_column(String(300), nullable=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    student: Mapped["RepetitorStudent"] = relationship("RepetitorStudent")


class RepetitorTopic(Base):
    """Repetitorun fənn üzrə mövzuları (sual olmasa da saxlanılır)."""
    __tablename__ = "repetitor_topics"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    subject: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class RepetitorQuestion(Base):
    """Repetitorun şəxsi sual bankı."""
    __tablename__ = "repetitor_questions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    subject: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    topic: Mapped[str] = mapped_column(String(100), nullable=False, default="")   # mövzu
    text: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(20), default="mcq")        # mcq | open | truefalse
    options: Mapped[str] = mapped_column(Text, nullable=True)           # JSON array (mcq üçün)
    correct_answer: Mapped[str] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(10), default="medium")  # easy|medium|hard
    points: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class RepetitorExam(Base):
    """Repetitorun bankdan yaratdığı imtahan sənədi."""
    __tablename__ = "repetitor_exams"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    duration_min: Mapped[int] = mapped_column(Integer, default=45)
    total_points: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    questions: Mapped[list["RepetitorExamQuestion"]] = relationship(
        "RepetitorExamQuestion", back_populates="exam", cascade="all, delete-orphan",
        order_by="RepetitorExamQuestion.order_num",
    )


class RepetitorExamQuestion(Base):
    """İmtahan sualının bağlantısı."""
    __tablename__ = "repetitor_exam_questions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    exam_id: Mapped[str] = mapped_column(String, ForeignKey("repetitor_exams.id"), nullable=False)
    question_id: Mapped[str] = mapped_column(String, ForeignKey("repetitor_questions.id"), nullable=False)
    order_num: Mapped[int] = mapped_column(Integer, default=0)

    exam: Mapped["RepetitorExam"] = relationship("RepetitorExam", back_populates="questions")
    question: Mapped["RepetitorQuestion"] = relationship("RepetitorQuestion")


class RepetitorMeeting(Base):
    """Repetitorun valideynlə görüşü."""
    __tablename__ = "repetitor_meetings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(String, ForeignKey("repetitor_students.id"), nullable=False)

    title: Mapped[str] = mapped_column(String(200), nullable=False)          # görüş mövzusu
    meeting_date: Mapped[str] = mapped_column(String(30), nullable=False)    # "2026-06-01T14:00"
    duration_min: Mapped[int] = mapped_column(Integer, default=30)
    location: Mapped[str] = mapped_column(String(200), nullable=True)        # "online" / ünvan
    note: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="planned")       # planned|done|cancelled

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    student: Mapped["RepetitorStudent"] = relationship("RepetitorStudent")


class RepetitorMessage(Base):
    """Repetitor ↔ şagird/valideyn mesajlaşma jurnalı.

    direction: 'out' = müəllim göndərib, 'in' = şagird/valideyn cavab verib (müəllim qeyd edir)
    to_type  : 'student' | 'parent'
    """
    __tablename__ = "repetitor_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(String, ForeignKey("repetitor_students.id"), nullable=False)

    direction: Mapped[str] = mapped_column(String(5), default="out")      # out | in
    to_type: Mapped[str] = mapped_column(String(10), default="student")   # student | parent
    content: Mapped[str] = mapped_column(Text, nullable=True)
    file_url: Mapped[str] = mapped_column(Text, nullable=True)            # əlavə fayl
    file_name: Mapped[str] = mapped_column(String(300), nullable=True)
    file_type: Mapped[str] = mapped_column(String(20), nullable=True)     # image | video | document
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)          # "özüm üçün sil" — yalnız müəllimdən gizlənir
    edited_at: Mapped[DateTime] = mapped_column(DateTime, nullable=True)  # redaktə olunubsa
    bridge_message_id: Mapped[str] = mapped_column(String, nullable=True) # platform Message id (out mesaj körpüsü)

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    student: Mapped["RepetitorStudent"] = relationship("RepetitorStudent")


class RepetitorChatClear(Base):
    """Repetitorun bir şagird söhbətini 'təmizləmə' kəsim nöqtəsi.

    cleared_at-dan əvvəlki mesajlar yalnız repetitorun ekranından gizlənir —
    bazada qalır, qarşı tərəf görməyə davam edir.
    """
    __tablename__ = "repetitor_chat_clears"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    teacher_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(String, ForeignKey("repetitor_students.id"), nullable=False)
    cleared_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)
