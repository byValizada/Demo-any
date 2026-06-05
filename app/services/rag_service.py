"""
VarisAcademy — RAG Servisi (Retrieval-Augmented Generation)
-----------------------------------------------------------
ChromaDB (yerli vector bazası) + Ollama embedding modeli.

Necə işləyir:
  1. Hər yeni məzmun (tapşırıq, sual, izahat) → ChromaDB-ə əlavə edilir
  2. Şagird/müəllim sual verəndə → ən uyğun materiallar tapılır
  3. Tapılan materiallar → AI-a kontekst kimi verilir
  4. AI cavab verir + bu söhbət də indeksə əlavə edilir (self-learning)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ── Sabitler ──────────────────────────────────────────────────────────────────

EMBED_TIMEOUT = 30.0
MAX_CHUNK_LEN = 500   # hər chunk maksimum simvol sayı
SIMILARITY_THRESHOLD = 0.72   # bu dəyərdən aşağı oxşarlıq → nəticəyə daxil edilmir


# ── ChromaDB lazy init ────────────────────────────────────────────────────────

_collection = None


def _get_collection():
    global _collection
    if _collection is not None:
        return _collection

    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        path = Path(settings.RAG_DB_PATH)
        path.mkdir(parents=True, exist_ok=True)

        client = chromadb.PersistentClient(
            path=str(path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        _collection = client.get_or_create_collection(
            name="varisacademy_v1",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"ChromaDB yükləndi: {path} | {_collection.count()} sənəd")
    except ImportError:
        logger.warning("chromadb quraşdırılmayıb — RAG deaktivdir. pip install chromadb")
        _collection = None
    except Exception as e:
        logger.error(f"ChromaDB xətası: {e}")
        _collection = None

    return _collection


# ── Embedding ─────────────────────────────────────────────────────────────────

async def _embed(text: str) -> list[float] | None:
    """Ollama nomic-embed-text ilə vektora çevir."""
    url = f"{settings.OLLAMA_URL}/api/embeddings"
    try:
        async with httpx.AsyncClient(timeout=EMBED_TIMEOUT) as client:
            r = await client.post(url, json={
                "model": settings.OLLAMA_EMBED_MODEL,
                "prompt": text[:2000],   # max input
            })
            r.raise_for_status()
            return r.json()["embedding"]
    except Exception as e:
        logger.warning(f"Embedding xətası: {e}")
        return None


# ── Chunk helper ──────────────────────────────────────────────────────────────

def _chunks(text: str, size: int = MAX_CHUNK_LEN) -> list[str]:
    """Uzun mətni hissələrə böl."""
    text = text.strip()
    if len(text) <= size:
        return [text]
    parts = []
    while text:
        parts.append(text[:size])
        text = text[size:]
    return parts


def _doc_id(prefix: str, content: str) -> str:
    """Unikal sənəd ID-si yarat (hash əsaslı — dublikat qarşısı)."""
    h = hashlib.md5(content.encode()).hexdigest()[:12]
    return f"{prefix}_{h}"


# ── Public API ────────────────────────────────────────────────────────────────

async def index_document(
    doc_id: str,
    text: str,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """
    Bir sənədi ChromaDB-ə əlavə et / yenilə.
    Uzun mətnlər chunk-lara bölünür.
    """
    col = _get_collection()
    if col is None:
        return False

    meta = metadata or {}
    chunks = _chunks(text)

    for i, chunk in enumerate(chunks):
        cid = f"{doc_id}_c{i}" if len(chunks) > 1 else doc_id
        emb = await _embed(chunk)
        if emb is None:
            continue
        try:
            col.upsert(
                ids=[cid],
                embeddings=[emb],
                documents=[chunk],
                metadatas=[{**meta, "chunk": i}],
            )
        except Exception as e:
            logger.error(f"ChromaDB upsert xətası ({cid}): {e}")
            return False

    return True


async def search(
    query: str,
    n_results: int = 5,
    filter_meta: dict | None = None,
) -> list[dict]:
    """
    Sorğuya ən uyğun sənədləri tap.
    Qaytarılan: [{"text": ..., "meta": ..., "score": 0-1}, ...]
    """
    col = _get_collection()
    if col is None:
        return []

    count = col.count()
    if count == 0:
        return []

    emb = await _embed(query)
    if emb is None:
        return []

    actual_n = min(n_results, count)

    try:
        kwargs: dict[str, Any] = dict(
            query_embeddings=[emb],
            n_results=actual_n,
            include=["documents", "metadatas", "distances"],
        )
        if filter_meta:
            kwargs["where"] = filter_meta

        results = col.query(**kwargs)
    except Exception as e:
        logger.error(f"ChromaDB query xətası: {e}")
        return []

    out = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        score = 1.0 - float(dist)
        if score >= SIMILARITY_THRESHOLD:
            out.append({"text": doc, "meta": meta, "score": round(score, 3)})

    out.sort(key=lambda x: x["score"], reverse=True)
    return out


async def index_qa_pair(
    question: str,
    answer: str,
    subject: str = "",
    doc_type: str = "tutor",
) -> bool:
    """Sual-cavab cütünü indeksə əlavə et (self-learning)."""
    text = f"Sual: {question}\nCavab: {answer}"
    doc_id = _doc_id(doc_type, text)
    return await index_document(
        doc_id=doc_id,
        text=text,
        metadata={"type": doc_type, "subject": subject},
    )


async def get_stats() -> dict:
    """RAG bazası statistikası."""
    col = _get_collection()
    if col is None:
        return {"status": "deaktiv", "count": 0}
    return {
        "status": "aktiv",
        "count": col.count(),
        "embed_model": settings.OLLAMA_EMBED_MODEL,
        "db_path": settings.RAG_DB_PATH,
    }
