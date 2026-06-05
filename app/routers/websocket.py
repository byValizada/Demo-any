"""
WebSocket endpoint — real-time bildiriş axını.
ws://localhost:8000/ws/notifications?token=<access_token>
"""
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


async def _authenticate_ws(token: str) -> str | None:
    """JWT token-i yoxla, user_id qaytar."""
    try:
        from app.services.auth_service import decode_token
        payload = decode_token(token)
        return payload.get("sub")
    except Exception:
        return None


@router.websocket("/ws/notifications")
async def ws_notifications(
    ws: WebSocket,
    token: str = Query(...),
):
    user_id = await _authenticate_ws(token)
    if not user_id:
        await ws.close(code=4001)
        return

    await ws_manager.connect(user_id, ws)
    try:
        # Ping-pong — bağlantını canlı saxla
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(user_id, ws)
    except Exception as e:
        logger.warning(f"WS error for {user_id}: {e}")
        ws_manager.disconnect(user_id, ws)
