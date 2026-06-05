"""
Meeting Room — Canlı görüş (Jitsi) köməkçiləri
----------------------------------------------
Valideyn ↔ Müəllim görüşləri üçün determinist otaq adı və
"qoşulma pəncərəsi" hesablaması. Real-time scheduler lazım deyil:
düymə vaxt pəncərəsinə görə aktivləşir.
"""

from datetime import datetime, timedelta

JITSI_DOMAIN   = "https://meet.jit.si"
JOIN_EARLY_MIN = 10     # görüşdən neçə dəqiqə əvvəl otaq açılır
JOIN_LATE_HRS  = 2      # görüş vaxtından neçə saat sonra bağlanır


def room_name(meeting_id: str) -> str:
    """Determinist otaq adı — hər iki tərəf eyni otağı hesablayır."""
    clean = (meeting_id or "").replace("-", "")[:16]
    return f"va-meet-{clean}"


def room_url(meeting_id: str) -> str:
    return f"{JITSI_DOMAIN}/{room_name(meeting_id)}"


def _parse_dt(s: str):
    """'2026-06-10T14:00' və ya ISO formatını parse et (naive local)."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        try:
            return datetime.strptime(s[:16], "%Y-%m-%dT%H:%M")
        except Exception:
            return None


def join_info(meeting_id: str, preferred_date: str, status: str) -> dict:
    """
    Qoşulma vəziyyətini hesablar.

    join_state: 'not_confirmed' | 'too_early' | 'open' | 'ended'
    """
    url = room_url(meeting_id)

    if status != "confirmed":
        return {"join_state": "not_confirmed", "can_join": False,
                "starts_in_minutes": None, "room_url": url}

    dt = _parse_dt(preferred_date)
    if not dt:
        # Tarix oxunmursa, təsdiqlənibsə açıq say
        return {"join_state": "open", "can_join": True,
                "starts_in_minutes": 0, "room_url": url}

    now      = datetime.now()
    open_at  = dt - timedelta(minutes=JOIN_EARLY_MIN)
    close_at = dt + timedelta(hours=JOIN_LATE_HRS)

    if now < open_at:
        mins = int((open_at - now).total_seconds() // 60)
        return {"join_state": "too_early", "can_join": False,
                "starts_in_minutes": mins, "room_url": url}

    if now > close_at:
        return {"join_state": "ended", "can_join": False,
                "starts_in_minutes": None, "room_url": url}

    return {"join_state": "open", "can_join": True,
            "starts_in_minutes": 0, "room_url": url}
