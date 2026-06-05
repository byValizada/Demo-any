"""
VarisAcademy — AI Servis (Groq + Gemini, avtomatik keçid)
----------------------------------------------------------
Groq (Llama 3.3 70B) → limit bitəndə → Gemini (gemini-2.0-flash)
RAG (ChromaDB + Ollama embedding) — yerli, öz serverində.

Konfiqurasiya (.env):
    GROQ_API_KEY=gsk_...
    GEMINI_API_KEY=AIza...
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import settings
from app.schemas.ai import (
    QuestionGenerateRequest, QuestionGenerateResponse,
    GeneratedQuestion,
    AnswerCheckRequest, AnswerCheckResponse,
    TutorRequest, TutorResponse,
    ExplainMistakeRequest, ExplainMistakeResponse,
    WeakTopic, StudyPlanResponse,
)
from app.services import rag_service

logger = logging.getLogger(__name__)

# ── Provider konfiqurasiyası ───────────────────────────────────────────────────

GROQ_URL    = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL  = "llama-3.3-70b-versatile"

GEMINI_URL  = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_MODEL = "gemini-2.0-flash"

TIMEOUT = 60.0

# ── Sistem promptu ────────────────────────────────────────────────────────────

_SYSTEM = """Sən VarisAcademy-nin peşəkar AI müəllimsən.
Azərbaycan məktəb proqramı üzrə bütün fənləri mükəmməl bilirsən: riyaziyyat, fizika, kimya, biologiya, tarix, coğrafiya, Azərbaycan dili və ədəbiyyat.
Cavablarını HƏMİŞƏ düzgün Azərbaycan ədəbi dilində ver. Qısa, aydın, müəllim kimi danış."""


# ── Groq sorğusu ─────────────────────────────────────────────────────────────

async def _call_groq(messages: list[dict], max_tokens: int, temperature: float) -> tuple[str, str]:
    api_key = settings.GROQ_API_KEY
    if not api_key:
        raise RuntimeError("no_key")

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": GROQ_MODEL, "messages": messages,
                  "max_tokens": max_tokens, "temperature": temperature},
        )
        if r.status_code == 429:
            raise RuntimeError("rate_limit")
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip(), data.get("model", GROQ_MODEL)


# ── Gemini sorğusu ───────────────────────────────────────────────────────────

async def _call_gemini(messages: list[dict], max_tokens: int, temperature: float) -> tuple[str, str]:
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise RuntimeError("no_key")

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            GEMINI_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": GEMINI_MODEL, "messages": messages,
                  "max_tokens": max_tokens, "temperature": temperature},
        )
        if r.status_code == 429:
            raise RuntimeError("rate_limit")
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip(), data.get("model", GEMINI_MODEL)


# ── Ana _chat: Groq → Gemini avtomatik keçid ─────────────────────────────────

async def _chat(
    messages: list[dict],
    *,
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> tuple[str, str]:
    """
    Əvvəlcə Groq-u cəhd et.
    Rate limit və ya xəta olsa → avtomatik Gemini-yə keç.
    """
    # ── Groq ──
    try:
        return await _call_groq(messages, max_tokens, temperature)
    except RuntimeError as e:
        err = str(e)
        if err not in ("rate_limit", "no_key"):
            # Şəbəkə xətası da Gemini-yə düşsün
            logger.warning(f"Groq xətası, Gemini-yə keçilir: {err}")
        else:
            logger.info(f"Groq: {err} → Gemini-yə keçilir")
    except Exception as e:
        logger.warning(f"Groq xətası, Gemini-yə keçilir: {e}")

    # ── Gemini ──
    try:
        return await _call_gemini(messages, max_tokens, temperature)
    except RuntimeError as e:
        raise RuntimeError(f"Hər iki AI provider xəta verdi. ({e})")
    except httpx.ConnectError:
        raise RuntimeError("AI serverlərinə qoşulmaq mümkün olmadı.")
    except Exception as e:
        logger.error(f"Gemini xətası: {e}")
        raise RuntimeError(str(e))


# ── JSON çıxarma ──────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict | list:
    m = re.search(r"```(?:json)?\s*([\[\{].*?)```", text, re.S)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"([\[\{].*[\]\}])", text, re.S)
    if m:
        return json.loads(m.group(1))
    raise ValueError(f"JSON tapılmadı:\n{text[:300]}")


# ── RAG kontekst ──────────────────────────────────────────────────────────────

async def _get_rag_context(query: str, subject: str = "") -> str:
    try:
        results = await rag_service.search(query, n_results=4,
                     filter_meta={"subject": subject} if subject else None)
        if not results:
            results = await rag_service.search(query, n_results=3)
        if not results:
            return ""
        lines = ["Sistemdəki əlaqəli materiallar:"]
        for r in results:
            lines.append(f"• {r['text'][:300]}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"RAG xətası: {e}")
        return ""


# ── 1. Sual Generasiyası ──────────────────────────────────────────────────────

async def generate_questions(req: QuestionGenerateRequest) -> QuestionGenerateResponse:
    diff_map = {"easy": "asan", "medium": "orta", "hard": "çətin"}
    type_map = {
        "mcq":       "çoxseçimli test (A, B, C, D variantları ilə)",
        "open":      "açıq cavablı (yazılı cavab)",
        "truefalse": "doğru/yanlış",
    }
    diff   = diff_map.get(req.difficulty, "orta")
    q_type = type_map.get(req.type, "çoxseçimli test")
    grade  = f"{req.grade}-ci sinif. " if req.grade else ""

    rag_ctx = await _get_rag_context(f"{req.subject} {req.topic}", req.subject)
    rag_block = f"\n\nƏlaqəli materiallar:\n{rag_ctx}" if rag_ctx else ""

    prompt = f"""Fənn: {req.subject}
Mövzu: {req.topic}
{grade}Çətinlik: {diff} | Tip: {q_type} | Say: {req.count}{rag_block}

Yalnız aşağıdakı JSON formatında {req.count} sual yaz, başqa heç nə yazma:

```json
[
  {{
    "text": "Sualın mətni Azərbaycan dilində?",
    "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
    "answer": "A",
    "explanation": "Qısa izahat Azərbaycan dilində"
  }}
]
```

Qaydalar:
- Bütün mətnlər Azərbaycan dilində olsun
- options: yalnız mcq üçün (4 variant), digərləri üçün null
- answer: mcq→"A"/"B"/"C"/"D", açıq→tam cavab, doğru/yanlış→"Doğru" və ya "Yanlış"
- Mövzuya tam uyğun, {diff} çətinlikdə suallar ol"""

    content, model = await _chat(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=2048,
        temperature=0.7,
    )

    try:
        raw   = _extract_json(content)
        items = raw if isinstance(raw, list) else raw.get("questions", [])
    except Exception as e:
        logger.error(f"JSON parse xətası: {e}\nLLM: {content[:400]}")
        raise RuntimeError("Model sualları düzgün formatda qaytarmadı. Yenidən cəhd edin.")

    questions: list[GeneratedQuestion] = []
    for item in items[: req.count]:
        questions.append(GeneratedQuestion(
            text=item.get("text", ""),
            type=req.type,
            options=item.get("options") or None,
            correct_answer=str(item.get("answer", "")),
            difficulty=req.difficulty,
            explanation=item.get("explanation"),
        ))
        # Self-learning
        if item.get("text"):
            await rag_service.index_document(
                doc_id=rag_service._doc_id("gen_q", item["text"]),
                text=f"Sual: {item['text']}\nCavab: {item.get('answer','')}\nİzahat: {item.get('explanation','')}",
                metadata={"type": "generated_question", "subject": req.subject, "topic": req.topic},
            )

    return QuestionGenerateResponse(questions=questions, model_used=model, total=len(questions))


# ── 2. Cavab Yoxlama ──────────────────────────────────────────────────────────

async def check_answer(req: AnswerCheckRequest) -> AnswerCheckResponse:
    if req.question_type == "mcq":
        correct = req.student_answer.strip().upper() == req.correct_answer.strip().upper()
        return AnswerCheckResponse(
            is_correct=correct,
            score=1.0 if correct else 0.0,
            feedback="Düzgün cavab!" if correct else f"Düzgün cavab: {req.correct_answer}",
            model_used="exact-match",
        )

    prompt = f"""Sual: {req.question}
Düzgün cavab: {req.correct_answer}
Şagirdin cavabı: {req.student_answer}

JSON formatında qiymətləndir:
```json
{{"is_correct": true, "score": 0.85, "feedback": "Azərbaycanca qısa rəy"}}
```
- score: 0.0-1.0 arası
- feedback: müəllim kimi mehriban, konstruktiv rəy"""

    content, model = await _chat(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
        max_tokens=300, temperature=0.3,
    )
    try:
        data = _extract_json(content)
        return AnswerCheckResponse(
            is_correct=bool(data.get("is_correct", False)),
            score=float(data.get("score", 0.0)),
            feedback=str(data.get("feedback", content[:200])),
            model_used=model,
        )
    except Exception:
        is_correct = req.correct_answer.strip().lower() in content.lower()
        return AnswerCheckResponse(
            is_correct=is_correct, score=0.7 if is_correct else 0.2,
            feedback=content[:300], model_used=model,
        )


# ── 3. AI Tutor ───────────────────────────────────────────────────────────────

async def tutor_chat(req: TutorRequest) -> TutorResponse:
    subject_hint  = f"Fənn: {req.subject}. " if req.subject else ""
    context_block = f"\n\nSöhbət konteksti:\n{req.context}" if req.context else ""
    rag_ctx       = await _get_rag_context(req.question, req.subject or "")
    rag_block     = f"\n\nƏlaqəli materiallar:\n{rag_ctx}" if rag_ctx else ""

    prompt = f"""{subject_hint}Şagirdin sualı: {req.question}{context_block}{rag_block}

Cavab ver, sonra bu JSON-u əlavə et:
```json
{{
  "answer": "Azərbaycan dilində tam izahlı cavab...",
  "suggestions": ["Davamçı sual 1?", "Davamçı sual 2?", "Davamçı sual 3?"]
}}
```"""

    content, model = await _chat(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
        max_tokens=1024, temperature=0.7,
    )

    try:
        data        = _extract_json(content)
        answer      = str(data.get("answer", content))
        suggestions = list(data.get("suggestions", []))[:3]
    except Exception:
        answer      = content
        suggestions = []

    if not suggestions:
        suggestions = [f"{req.subject or 'Bu mövzu'} ilə bağlı başqa sualınız varmı?"]

    # Self-learning
    await rag_service.index_qa_pair(req.question, answer, req.subject or "")

    return TutorResponse(answer=answer, suggestions=suggestions, model_used=model, rag_used=bool(rag_ctx))


# ── 3b. Səhv İzahı ────────────────────────────────────────────────────────────

async def explain_mistake(req: ExplainMistakeRequest) -> ExplainMistakeResponse:
    """Şagirdin səhv cavabını izah et: niyə səhvdir + düzgün anlayış + məsləhət."""
    rag_ctx   = await _get_rag_context(req.question, req.subject or "")
    rag_block = f"\n\nƏlaqəli materiallar:\n{rag_ctx}" if rag_ctx else ""
    subj      = f"Fənn: {req.subject}\n" if req.subject else ""

    prompt = f"""{subj}Sual: {req.question}
Şagirdin (səhv) cavabı: {req.student_answer or "— (boş)"}
Düzgün cavab: {req.correct_answer}{rag_block}

Şagird bu sualı səhv cavablayıb. Müəllim kimi mehriban izah et.
Yalnız bu JSON-u qaytar:
```json
{{
  "explanation": "Niyə həmin cavab səhvdir və düzgün anlayışın aydın, addım-addım izahı (Azərbaycan dilində, 2-4 cümlə)",
  "tip": "Yadda saxlamaq üçün qısa bir məsləhət və ya qayda (bir cümlə)"
}}
```"""

    content, model = await _chat(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
        max_tokens=600, temperature=0.4,
    )
    try:
        data = _extract_json(content)
        return ExplainMistakeResponse(
            explanation=str(data.get("explanation", content))[:1200],
            tip=str(data.get("tip", ""))[:300],
            model_used=model,
        )
    except Exception:
        return ExplainMistakeResponse(explanation=content[:1200], tip="", model_used=model)


# ── 3c. Öyrənmə Tövsiyəsi (zəif mövzu analizi) ───────────────────────────────

async def study_recommendations(
    student_name: str,
    subject_stats: list[dict],   # [{"subject": .., "percentage": .., "exams_count": ..}]
) -> StudyPlanResponse:
    """Şagirdin fənlər üzrə nəticələrinə görə fərdi öyrənmə planı qur."""
    if not subject_stats:
        return StudyPlanResponse(
            summary="Hələ kifayət qədər imtahan nəticən yoxdur.",
            weak_topics=[], recommendations=[
                "Müəllimin paylaşdığı imtahanlara qoşul.",
                "İlk nəticələrdən sonra fərdi plan burada görünəcək.",
            ],
            motivation="Başlamaq üçün ən yaxşı vaxt indidir! 🚀",
            model_used="rule-based", has_data=False,
        )

    # Ən zəif 3 fənn
    weak = sorted(subject_stats, key=lambda s: s["percentage"])[:3]
    weak_topics = [
        WeakTopic(subject=w["subject"], percentage=round(w["percentage"], 1),
                  exams_count=w["exams_count"])
        for w in weak
    ]

    stats_text = "\n".join(
        f"- {s['subject']}: orta {round(s['percentage'],1)}% ({s['exams_count']} imtahan)"
        for s in sorted(subject_stats, key=lambda s: s["percentage"])
    )

    prompt = f"""Şagird: {student_name}
Fənlər üzrə imtahan nəticələri:
{stats_text}

Bu şagird üçün fərdi öyrənmə planı hazırla. Ən zəif fənlərə fokuslan.
Yalnız bu JSON-u qaytar:
```json
{{
  "summary": "Ümumi qiymətləndirmə — güclü və zəif tərəflər (2-3 cümlə)",
  "recommendations": ["Konkret addım 1", "Konkret addım 2", "Konkret addım 3", "Konkret addım 4"],
  "motivation": "Qısa, ürəkləndirici bir cümlə"
}}
```
Qaydalar: hər şey Azərbaycan dilində, konkret və əməli məsləhətlər (mövzu adları, gündəlik təcrübə və s.)."""

    content, model = await _chat(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
        max_tokens=900, temperature=0.6,
    )
    try:
        data = _extract_json(content)
        return StudyPlanResponse(
            summary=str(data.get("summary", ""))[:800],
            weak_topics=weak_topics,
            recommendations=[str(r) for r in data.get("recommendations", [])][:6],
            motivation=str(data.get("motivation", ""))[:300],
            model_used=model, has_data=True,
        )
    except Exception:
        return StudyPlanResponse(
            summary=content[:800], weak_topics=weak_topics,
            recommendations=["Zəif fənlər üzrə əlavə məşq et."],
            motivation="Davam et, irəliləyirsən! 💪",
            model_used=model, has_data=True,
        )


# ── 4. Ümumi Chat ─────────────────────────────────────────────────────────────

async def chat(messages: list[dict], max_tokens: int = 1024, temperature: float = 0.7) -> str:
    content, _ = await _chat(messages, max_tokens=max_tokens, temperature=temperature)
    return content


# ── 5. Sağlamlıq Yoxlaması ────────────────────────────────────────────────────

async def check_health() -> dict:
    try:
        content, model = await _chat(
            [{"role": "user", "content": "Salam! Sadəcə 'Hazıram' de."}],
            max_tokens=15, temperature=0.1,
        )
        rag_stats = await rag_service.get_stats()
        return {"status": "ok", "model": model, "response": content[:80], "rag": rag_stats}
    except RuntimeError as e:
        return {"status": "error", "model": GROQ_MODEL, "error": str(e)}
