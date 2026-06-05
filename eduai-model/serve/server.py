"""
EduAI — Local Inference Server
================================
llama-cpp-python ilə öz modelimizi API kimi işlədir.
EduAI backend bu serverlə danışır.

Quraşdırma:
  pip install llama-cpp-python fastapi uvicorn

İstifadə:
  python server.py --model ./eduai-model-q4.gguf

Port: 8001 (EduAI backend http://localhost:8001-ə sorğu göndərir)
"""

import argparse
import time
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from llama_cpp import Llama

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eduai-model")

# ── FastAPI ────────────────────────────────────────────────────────────────────

app = FastAPI(title="EduAI Model Server", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

llm: Optional[Llama] = None

SYSTEM_PROMPT = (
    "Sən EduAI platformasının AI müəllimsən. "
    "Azərbaycan məktəb şagirdlərinə və müəllimlərinə kömək edirsən. "
    "Həmişə Azərbaycan dilində cavab verirsən. "
    "Dəqiq, aydın və təhsilə uyğun cavablar verirsən. "
    "Cavablarını strukturlu (başlıq, nümunə, izah) verirsən."
)

# ── Sxemlər ───────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str       # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    max_tokens: int = 1024
    temperature: float = 0.7
    top_p: float = 0.9


class ChatResponse(BaseModel):
    content: str
    tokens_used: int
    duration_ms: int


class QuestionGenRequest(BaseModel):
    subject: str        # "Riyaziyyat"
    topic: str          # "Kəsrlər"
    grade: int          # 5
    count: int = 5      # neçə sual
    difficulty: str = "qarışıq"   # "asan" | "orta" | "çətin" | "qarışıq"


class QuestionGenResponse(BaseModel):
    questions: list[dict]
    duration_ms: int


class TutorRequest(BaseModel):
    question: str
    subject: Optional[str] = None
    grade: Optional[int] = None


class TutorResponse(BaseModel):
    answer: str
    duration_ms: int


class TranslateRequest(BaseModel):
    text: str
    from_lang: str    # "az" | "en" | "ru"
    to_lang: str      # "az" | "en" | "ru"


class TranslateResponse(BaseModel):
    translated: str
    duration_ms: int


# ── Köməkçi funksiyalar ────────────────────────────────────────────────────────

def chat(messages: list[dict], max_tokens: int = 1024, temperature: float = 0.7) -> tuple[str, int]:
    """Model ilə danış, cavab və token sayını qaytar"""
    if llm is None:
        raise RuntimeError("Model yüklənməyib")

    # System prompt əlavə et
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    result = llm.create_chat_completion(
        messages=full_messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=0.9,
        repeat_penalty=1.1,
        stop=["<|eot_id|>", "<|end_of_text|>"],
    )
    content = result["choices"][0]["message"]["content"].strip()
    tokens  = result["usage"]["total_tokens"]
    return content, tokens


# ── Endpoint-lər ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": llm is not None}


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """Ümumi söhbət endpoint-i"""
    if llm is None:
        raise HTTPException(503, "Model hələ yüklənməyib")
    t0 = time.time()
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    content, tokens = chat(messages, req.max_tokens, req.temperature)
    return ChatResponse(
        content=content,
        tokens_used=tokens,
        duration_ms=int((time.time() - t0) * 1000),
    )


@app.post("/generate-questions", response_model=QuestionGenResponse)
async def generate_questions(req: QuestionGenRequest):
    """Müəllim üçün test sualları yarat"""
    if llm is None:
        raise HTTPException(503, "Model hələ yüklənməyib")
    t0 = time.time()

    prompt = (
        f"{req.subject} fənni, {req.grade}-ci sinif, mövzu: {req.topic}.\n"
        f"{req.count} ədəd {req.difficulty} çətinlikdə test sualı yarat.\n"
        f"Hər sual üçün: sual mətni, 4 variant (A/B/C/D), düzgün cavab və qısa izah.\n"
        f"JSON formatında qaytar: {{\"questions\": [{{\"text\": ..., \"options\": {{\"A\":...,\"B\":...,\"C\":...,\"D\":...}}, \"answer\": ..., \"explanation\": ...}}]}}"
    )

    content, _ = chat([{"role": "user", "content": prompt}], max_tokens=2048, temperature=0.8)

    # JSON parse
    import json, re
    questions = []
    try:
        # JSON blokunu tap
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            data = json.loads(match.group())
            questions = data.get("questions", [])
    except Exception:
        # JSON parse olmadısa raw text qaytar
        questions = [{"text": content, "options": {}, "answer": "", "explanation": ""}]

    return QuestionGenResponse(
        questions=questions,
        duration_ms=int((time.time() - t0) * 1000),
    )


@app.post("/tutor", response_model=TutorResponse)
async def tutor_endpoint(req: TutorRequest):
    """Şagird sualına cavab ver"""
    if llm is None:
        raise HTTPException(503, "Model hələ yüklənməyib")
    t0 = time.time()

    context = ""
    if req.subject:
        context += f"Fənn: {req.subject}. "
    if req.grade:
        context += f"Sinif: {req.grade}. "

    prompt = f"{context}Şagird sualı: {req.question}"
    content, _ = chat([{"role": "user", "content": prompt}])

    return TutorResponse(
        answer=content,
        duration_ms=int((time.time() - t0) * 1000),
    )


@app.post("/translate", response_model=TranslateResponse)
async def translate_endpoint(req: TranslateRequest):
    """Mətn tərcüməsi"""
    if llm is None:
        raise HTTPException(503, "Model hələ yüklənməyib")
    t0 = time.time()

    lang_names = {"az": "Azərbaycan", "en": "İngilis", "ru": "Rus"}
    from_name = lang_names.get(req.from_lang, req.from_lang)
    to_name   = lang_names.get(req.to_lang, req.to_lang)

    prompt = (
        f"Aşağıdakı mətni {from_name} dilindən {to_name} dilinə tərcümə et.\n"
        f"Yalnız tərcüməni yaz, əlavə izahat vermə.\n\n"
        f"Mətn: {req.text}"
    )
    content, _ = chat([{"role": "user", "content": prompt}], temperature=0.3)

    return TranslateResponse(
        translated=content,
        duration_ms=int((time.time() - t0) * 1000),
    )


# ── Başlanğıc ─────────────────────────────────────────────────────────────────

def load_model(model_path: str):
    global llm
    logger.info(f"Model yüklənir: {model_path}")
    llm = Llama(
        model_path=model_path,
        n_ctx=4096,          # kontekst uzunluğu
        n_gpu_layers=35,     # GPU-ya yüklənəcək layer sayı (4GB VRAM üçün)
        n_threads=6,         # CPU thread (Ryzen 5 5600H üçün)
        verbose=False,
    )
    logger.info("✅ Model hazırdır")


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Model faylının yolu (.gguf)")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    if not Path(args.model).exists():
        print(f"[XƏTA] Model faylı tapılmadı: {args.model}")
        exit(1)

    load_model(args.model)
    uvicorn.run(app, host=args.host, port=args.port)
