"""
WebSocket Chat Router
----------------------
Real-time mesajlaşma: otaqlar memory-də saxlanılır.
Otaq ID formatları:
  teacher_student_{teacher_id}_{student_id}
  class_{class_id}
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services.auth_service import decode_token, get_user_by_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


# ─── Aktiv bağlantılar (memory) ──────────────────────────────────────────────

# room_id → [WebSocket]
_rooms: Dict[str, List[WebSocket]] = {}


# ─── Sxemlər ─────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    type: str = "message"
    content: str
    sender_name: str
    sender_id: str
    timestamp: str


class RoomInfo(BaseModel):
    room_id: str
    participant_count: int


# ─── Köməkçi funksiyalar ─────────────────────────────────────────────────────

def _add_to_room(room_id: str, ws: WebSocket) -> None:
    if room_id not in _rooms:
        _rooms[room_id] = []
    _rooms[room_id].append(ws)


def _remove_from_room(room_id: str, ws: WebSocket) -> None:
    if room_id in _rooms:
        try:
            _rooms[room_id].remove(ws)
        except ValueError:
            pass
        if not _rooms[room_id]:
            del _rooms[room_id]


async def _broadcast(room_id: str, message: dict, exclude: WebSocket = None) -> None:
    """Otaqdakı bütün bağlantılara mesaj göndər."""
    if room_id not in _rooms:
        return

    dead: List[WebSocket] = []
    for ws in _rooms[room_id]:
        if ws is exclude:
            continue
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)

    for ws in dead:
        _remove_from_room(room_id, ws)


async def _authenticate_ws(token: str, db: AsyncSession) -> User:
    """WebSocket sorğusundan JWT token ilə istifadəçini doğrula."""
    try:
        payload = decode_token(token)
        user_id: str = payload.get("sub")
        if not user_id:
            return None
    except JWTError:
        return None

    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        return None
    return user


# ─── WebSocket endpoint ───────────────────────────────────────────────────────

@router.websocket("/ws/{room_id}")
async def websocket_chat(
    websocket: WebSocket,
    room_id: str,
    token: str = Query(..., description="JWT access token"),
    db: AsyncSession = Depends(get_db),
):
    """
    WebSocket əlaqəsi.
    URL: ws://host/chat/ws/{room_id}?token={jwt}

    Mesaj formatı (göndər/al):
    {
      "type": "message",
      "content": "salam",
      "sender_name": "Əli",
      "sender_id": "uuid",
      "timestamp": "2024-01-01T10:00:00Z"
    }
    """
    # 1. Doğrulama
    user = await _authenticate_ws(token, db)
    if not user:
        await websocket.close(code=4001, reason="Token etibarsızdır")
        return

    # 2. Bağlan
    await websocket.accept()
    _add_to_room(room_id, websocket)
    logger.info(f"[Chat] {user.name} otağa qoşuldu: {room_id}")

    # Otağa qoşulma bildirişi göndər
    join_msg = {
        "type": "system",
        "content": f"{user.name} söhbətə qoşuldu",
        "sender_name": "system",
        "sender_id": "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await _broadcast(room_id, join_msg, exclude=websocket)

    try:
        while True:
            # Mesaj gözlə
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "content": "JSON formatı yanlışdır"})
                continue

            # Mesajı formatla
            message = {
                "type": "message",
                "content": data.get("content", ""),
                "sender_name": user.name,
                "sender_id": user.id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Özü daxil bütün otağa yayımla
            await _broadcast(room_id, message)
            # Özünə də göndər (echo)
            await websocket.send_json(message)

    except WebSocketDisconnect:
        _remove_from_room(room_id, websocket)
        logger.info(f"[Chat] {user.name} otaqdan ayrıldı: {room_id}")

        leave_msg = {
            "type": "system",
            "content": f"{user.name} söhbəti tərk etdi",
            "sender_name": "system",
            "sender_id": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _broadcast(room_id, leave_msg)

    except Exception as e:
        logger.error(f"[Chat] WebSocket xətası: {e}")
        _remove_from_room(room_id, websocket)


# ─── REST Endpoint-lər ───────────────────────────────────────────────────────

@router.get("/rooms", response_model=List[RoomInfo])
async def list_rooms(current_user: User = Depends(get_current_user)):
    """
    Hazırda aktiv olan söhbət otaqlarını listə.
    Yalnız autentifikasiya olunmuş istifadəçilər üçün.
    """
    return [
        RoomInfo(room_id=room_id, participant_count=len(connections))
        for room_id, connections in _rooms.items()
    ]


@router.get("/history/{room_id}")
async def chat_history(
    room_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Söhbət tarixçəsi — hazırda placeholder (DB persist sonra əlavə ediləcək).
    """
    return {
        "room_id": room_id,
        "messages": [],
        "note": "Tarixçə saxlama tezliklə əlavə ediləcək",
    }
