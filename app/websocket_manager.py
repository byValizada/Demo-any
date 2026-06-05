"""
WebSocket Connection Manager
Hər user_id üçün aktiv WebSocket bağlantılarını saxlayır.
"""
import asyncio
import json
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # user_id → list of WebSocket connections (eyni user bir neçə tab aça bilər)
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, user_id: str, ws: WebSocket):
        await ws.accept()
        self._connections.setdefault(user_id, []).append(ws)
        logger.info(f"WS connected: {user_id} (total={len(self._connections[user_id])})")

    def disconnect(self, user_id: str, ws: WebSocket):
        conns = self._connections.get(user_id, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self._connections.pop(user_id, None)
        logger.info(f"WS disconnected: {user_id}")

    async def send(self, user_id: str, data: dict):
        """Bir user-ə JSON mesaj göndər (bütün tablarına)."""
        conns = self._connections.get(user_id, [])
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)

    def is_connected(self, user_id: str) -> bool:
        return bool(self._connections.get(user_id))

    async def broadcast_notification(self, user_id: str, title: str,
                                      description: str = "", notif_type: str = "info"):
        """Bildiriş event-i göndər — frontend dərhal göstərir."""
        await self.send(user_id, {
            "event": "notification",
            "title": title,
            "description": description,
            "type": notif_type,
        })


# Tək qlobal instance
ws_manager = ConnectionManager()
