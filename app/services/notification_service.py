"""Helper to create in-app notifications + real-time WebSocket push."""
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.notification import Notification


async def send_notification(
    db: AsyncSession,
    user_id: str,
    title: str,
    description: str = "",
    notif_type: str = "info",   # info | success | warning | error
) -> None:
    """Insert a notification row. Caller must commit the session.
       Eyni zamanda WebSocket üzərindən real-time göndərir."""
    n = Notification(
        user_id=user_id,
        title=title,
        description=description,
        type=notif_type,
    )
    db.add(n)

    # Real-time push (WS bağlıdırsa)
    try:
        from app.websocket_manager import ws_manager
        import asyncio
        asyncio.create_task(ws_manager.broadcast_notification(
            user_id=user_id,
            title=title,
            description=description,
            notif_type=notif_type,
        ))
    except Exception:
        pass  # WS olmasa da bildiriş DB-də saxlanır
