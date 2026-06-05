"""
AI Schema-ları — Llama 3.2 / HuggingFace Inference API
"""

from pydantic import BaseModel
from typing import Optional, List


# ── Sual Generasiyası ─────────────────────────────────────────────────────────

class QuestionGenerateRequest(BaseModel):
    subject: str                    # Riyaziyyat, Fizika, Biologiya...
    topic: str                      # Kvadrat tənliklər, İşıq, Hüceyrə...
    difficulty: str = "medium"      # easy | medium | hard
    count: int = 5                  # neçə sual (1-10)
    type: str = "mcq"               # mcq | open | truefalse
    language: str = "az"            # az | ru | en
    grade: Optional[str] = None     # 9-cu sinif, 11-ci sinif...


class GeneratedQuestion(BaseModel):
    text: str                       # Sualın mətni
    type: str                       # mcq | open | truefalse
    options: Optional[List[str]] = None   # MCQ üçün: ["A) ...", "B) ...", ...]
    correct_answer: str             # MCQ: "A" | Open: tam cavab
    difficulty: str = "medium"
    explanation: Optional[str] = None    # İzahat


class QuestionGenerateResponse(BaseModel):
    questions: List[GeneratedQuestion]
    model_used: str
    total: int


# ── Cavab Yoxlama ─────────────────────────────────────────────────────────────

class AnswerCheckRequest(BaseModel):
    question: str
    student_answer: str
    correct_answer: str
    question_type: str = "open"     # open | mcq


class AnswerCheckResponse(BaseModel):
    is_correct: bool
    score: float                    # 0.0 – 1.0
    feedback: str                   # Azərbaycanca qısa rəy
    model_used: str


# ── AI Tutor ──────────────────────────────────────────────────────────────────

class TutorRequest(BaseModel):
    question: str
    subject: str = ""
    context: str = ""               # Əvvəlki mesajlar (kontekst)
    language: str = "az"


class TutorResponse(BaseModel):
    answer: str
    suggestions: List[str] = []    # 2-3 davamçı sual
    model_used: str
    rag_used: bool = False         # RAG-dan kontekst götürüldüsə True


# ── Səhv İzahı (şagird imtahana baxış) ───────────────────────────────────────

class ExplainMistakeRequest(BaseModel):
    question: str
    student_answer: str
    correct_answer: str
    subject: str = ""
    question_type: str = "mcq"      # mcq | open | truefalse


class ExplainMistakeResponse(BaseModel):
    explanation: str                # Niyə səhvdir + düzgün anlayış
    tip: str = ""                   # Qısa məsləhət / yadda saxlamaq üçün
    model_used: str


# ── Öyrənmə Tövsiyəsi (zəif mövzu analizi) ───────────────────────────────────

class WeakTopic(BaseModel):
    subject: str
    percentage: float               # orta nəticə %
    exams_count: int


class StudyPlanResponse(BaseModel):
    summary: str                    # Ümumi qiymətləndirmə
    weak_topics: List[WeakTopic]    # ən zəif fənlər
    recommendations: List[str]      # konkret addımlar
    motivation: str = ""            # qısa motivasiya cümləsi
    model_used: str
    has_data: bool = True


# ── Ümumi Chat ────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str      # user | assistant | system
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    max_tokens: int = 1024
    temperature: float = 0.7


class ChatResponse(BaseModel):
    content: str
    model_used: str
