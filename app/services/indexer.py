"""
VarisAcademy — Məzmun İndeksləyici
------------------------------------
Sistemdəki bütün materialları ChromaDB-ə indekslər.
Startup-da işə düşür, sonra incremental olaraq yeni məzmun əlavə olunur.

İndekslənən məlumatlar:
  - Tapşırıqlar (subject, description)
  - İmtahan sualları + izahatlar
  - AI Tutor söhbəti (arxiv)
  - Elanlar
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.services import rag_service

logger = logging.getLogger(__name__)


# ── Köməkçi ───────────────────────────────────────────────────────────────────

def _safe(val) -> str:
    return str(val).strip() if val else ""


# ── İndeksleme funksiyaları ───────────────────────────────────────────────────

async def index_homework_item(hw) -> None:
    """Bir tapşırığı indeksə əlavə et."""
    text = f"Tapşırıq: {_safe(hw.title)}"
    if hw.description:
        text += f"\n{_safe(hw.description)}"
    if len(text) < 15:
        return
    await rag_service.index_document(
        doc_id=f"hw_{hw.id}",
        text=text,
        metadata={
            "type":    "homework",
            "subject": _safe(getattr(hw, "subject", "")),
            "item_id": str(hw.id),
        },
    )


async def index_exam_question(question_text: str, answer: str, explanation: str,
                               subject: str, item_id: str) -> None:
    """İmtahan sualını indeksə əlavə et."""
    text = f"Sual: {question_text}"
    if answer:
        text += f"\nCavab: {answer}"
    if explanation:
        text += f"\nİzahat: {explanation}"
    await rag_service.index_document(
        doc_id=f"eq_{item_id}",
        text=text,
        metadata={"type": "exam_question", "subject": subject, "item_id": item_id},
    )


async def index_announcement(ann) -> None:
    """Elanı indeksə əlavə et."""
    text = f"Elan: {_safe(ann.title)}"
    if hasattr(ann, "body") and ann.body:
        text += f"\n{_safe(ann.body)}"
    if len(text) < 15:
        return
    await rag_service.index_document(
        doc_id=f"ann_{ann.id}",
        text=text,
        metadata={"type": "announcement", "item_id": str(ann.id)},
    )


# ── Tam indeksleme ────────────────────────────────────────────────────────────

async def run_full_index(db: "AsyncSession") -> dict:
    """
    Bütün mövcud məlumatları indeksə əlavə et.
    Startup-da bir dəfə çağırılır.
    Artıq indekslənmiş sənədlər upsert ilə yenilənir (dublikat yoxdur).
    """
    from sqlalchemy import select, text as sa_text

    counts = {"homework": 0, "exam_questions": 0, "announcements": 0}

    # ── Tapşırıqlar ───────────────────────────────────────────────────────────
    try:
        from app.models.homework import Homework
        hw_res = await db.execute(select(Homework))
        for hw in hw_res.scalars().all():
            await index_homework_item(hw)
            counts["homework"] += 1
    except Exception as e:
        logger.warning(f"Tapşırıq indeksleme xətası: {e}")

    # ── Elanlar ───────────────────────────────────────────────────────────────
    try:
        from app.models.announcement import Announcement
        ann_res = await db.execute(select(Announcement))
        for ann in ann_res.scalars().all():
            await index_announcement(ann)
            counts["announcements"] += 1
    except Exception as e:
        logger.warning(f"Elan indeksleme xətası: {e}")


    # ── İmtahan sualları ──────────────────────────────────────────────────────
    try:
        from app.models.exam import Exam
        exam_res = await db.execute(select(Exam))
        for exam in exam_res.scalars().all():
            import json as _json
            if not exam.questions:
                continue
            try:
                qs = _json.loads(exam.questions) if isinstance(exam.questions, str) else exam.questions
            except Exception:
                continue
            for i, q in enumerate(qs or []):
                if not isinstance(q, dict):
                    continue
                await index_exam_question(
                    question_text=str(q.get("text", q.get("q", ""))),
                    answer=str(q.get("answer", q.get("correct_answer", ""))),
                    explanation=str(q.get("explanation", "")),
                    subject=str(exam.subject or ""),
                    item_id=f"{exam.id}_{i}",
                )
                counts["exam_questions"] += 1
    except Exception as e:
        logger.warning(f"İmtahan sualı indeksleme xətası: {e}")

    total = sum(counts.values())
    rag_stats = await rag_service.get_stats()
    logger.info(f"İndeksleme tamamlandı: {counts} | RAG bazası: {rag_stats['count']} sənəd")
    return {"indexed": counts, "total": total, "rag_total": rag_stats.get("count", 0)}
