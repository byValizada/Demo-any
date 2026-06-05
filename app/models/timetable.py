from sqlalchemy import String, Integer, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
import uuid

class TimetableEntry(Base):
    __tablename__ = "timetable_entries"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    class_id: Mapped[str] = mapped_column(String, ForeignKey("classes.id"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)   # 0=Mon 4=Fri
    period: Mapped[int] = mapped_column(Integer, nullable=False)         # 1-8
    start_time: Mapped[str] = mapped_column(String(10), nullable=False)  # "08:00"
    end_time: Mapped[str] = mapped_column(String(10), nullable=False)    # "08:45"
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    room: Mapped[str] = mapped_column(String(50), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
