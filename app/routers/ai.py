from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.database import get_db
from app.dependencies import get_current_user, require_teacher, get_optional_user, require_not_demo_repetitor
from app.models.user import User
from app.models.tutor_message import TutorMessage
from app.schemas.ai import (
    QuestionGenerateRequest, QuestionGenerateResponse,
    AnswerCheckRequest, AnswerCheckResponse,
    TutorRequest, TutorResponse,
    ExplainMistakeRequest, ExplainMistakeResponse,
)
from app.services.ai_service import (
    generate_questions, check_answer, tutor_chat, check_health,
    explain_mistake,
)

router = APIRouter(prefix="/ai", tags=["AI"], dependencies=[Depends(require_not_demo_repetitor)])


async def _check_ai_limit(user: User, db: AsyncSession) -> None:
    """Raise 429 if tenant's daily AI limit is exceeded."""
    from app.models.tenant import Tenant
    from app.models.ai_log import AILog
    from sqlalchemy import func, select
    from datetime import date

    if not user.tenant_id:
        return

    t_res = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = t_res.scalar_one_or_none()
    if not tenant:
        return
    limit = tenant.ai_daily_limit or 0
    if limit == 0:
        return   # unlimited

    today = date.today().isoformat()
    count_res = await db.execute(
        select(func.count(AILog.id)).where(
            AILog.tenant_id == user.tenant_id,
            func.strftime('%Y-%m-%d', AILog.created_at) == today,
        )
    )
    used = count_res.scalar_one()
    if used >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Günlük AI limiti ({limit} sorğu) dolub. Sabah yenidən cəhd edin.",
        )


@router.post("/generate-questions", response_model=QuestionGenerateResponse)
async def api_generate_questions(
    req: QuestionGenerateRequest,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Müəllim üçün sual generasiyası."""
    await _check_ai_limit(current_user, db)
    try:
        return await generate_questions(req)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/check-answer", response_model=AnswerCheckResponse)
async def api_check_answer(
    req: AnswerCheckRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdin açıq sual cavabını AI ilə yoxla."""
    await _check_ai_limit(current_user, db)
    try:
        return await check_answer(req)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/explain-mistake", response_model=ExplainMistakeResponse)
async def api_explain_mistake(
    req: ExplainMistakeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdin səhv cavabını AI ilə izah et (niyə səhv + düzgün anlayış + məsləhət)."""
    await _check_ai_limit(current_user, db)
    try:
        return await explain_mistake(req)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/tutor", response_model=TutorResponse)
async def ai_tutor(
    req: TutorRequest,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """
    AI Müəllim — şagirdin sualına cavab ver + söhbət tarixini saxla.
    Token varsa DB-ə yazılır, yoxdursa cavab yenə verilir.
    """
    try:
        result = await tutor_chat(req)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="AI servisi müvəqqəti əlçatmazdır.")

    # Authenticated istifadəçinin söhbətini saxla
    if current_user:
        try:
            db.add(TutorMessage(
                user_id=current_user.id,
                role="user",
                content=req.question,
                subject=req.subject,
            ))
            db.add(TutorMessage(
                user_id=current_user.id,
                role="ai",
                content=result.answer,
                subject=req.subject,
                provider=result.model_used,
                suggestions=result.suggestions,
            ))
            await db.commit()
        except Exception:
            await db.rollback()  # saxlama uğursuz olsa da cavab qaytar

    return result


# ── Söhbət Tarixi ────────────────────────────────────────────────────────────

class TutorMessageOut(BaseModel):
    id: str
    role: str
    content: str
    subject: Optional[str]
    provider: Optional[str]
    suggestions: Optional[list]
    created_at: str


@router.get("/tutor/history", response_model=list[TutorMessageOut])
async def get_tutor_history(
    subject: Optional[str] = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Şagirdin AI Müəllim söhbət tarixini qaytar (son → əvvəl)."""
    query = (
        select(TutorMessage)
        .where(TutorMessage.user_id == current_user.id)
        .order_by(TutorMessage.created_at.desc())
        .limit(limit)
    )
    if subject and subject not in ("Hamısı", ""):
        query = query.where(TutorMessage.subject == subject)

    result = await db.execute(query)
    messages = list(reversed(result.scalars().all()))

    return [
        TutorMessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            subject=m.subject,
            provider=m.provider,
            suggestions=m.suggestions,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in messages
    ]


@router.delete("/tutor/history")
async def clear_tutor_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """İstifadəçinin bütün AI söhbət tarixini sil."""
    result = await db.execute(
        select(TutorMessage).where(TutorMessage.user_id == current_user.id)
    )
    for msg in result.scalars().all():
        await db.delete(msg)
    await db.commit()
    return {"deleted": True}


@router.get("/status")
async def ai_status(current_user: User = Depends(require_teacher)):
    """AI provider statusunu göstər (Groq + Gemini + RAG)."""
    from app.config import settings
    from app.services.rag_service import get_stats as rag_stats
    from app.services.ai_service import GROQ_MODEL, GEMINI_MODEL
    rag = await rag_stats()
    return {
        "primary_provider":   "Groq",
        "primary_model":      GROQ_MODEL,
        "fallback_provider":  "Gemini",
        "fallback_model":     GEMINI_MODEL,
        "groq_key_set":       bool(settings.GROQ_API_KEY),
        "gemini_key_set":     bool(settings.GEMINI_API_KEY),
        "embed_model":        settings.OLLAMA_EMBED_MODEL,
        "ollama_url":         settings.OLLAMA_URL,
        "rag":                rag,
    }


@router.get("/health")
async def ai_health(current_user: User = Depends(require_teacher)):
    """Groq → Gemini-yə real sorğu göndər, RAG statistikasını qaytar."""
    result = await check_health()
    if result["status"] != "ok":
        raise HTTPException(status_code=503, detail=result.get("error", "AI xətası"))
    return result


@router.post("/reindex")
async def reindex_rag(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Bütün məzmunu yenidən RAG bazasına indeksə əlavə et."""
    from app.services.indexer import run_full_index
    result = await run_full_index(db)
    return {"success": True, "indexed": result}
