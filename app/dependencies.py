from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError
from app.database import get_db
from app.services.auth_service import decode_token, get_user_by_id
from app.models.user import User
from app.models.tenant import Tenant

security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    try:
        payload = decode_token(credentials.credentials)
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token etibarsızdır")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token etibarsızdır")

    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="İstifadəçi tapılmadı")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hesabınız deaktiv edilib. Müəssisə administratoru ilə əlaqə saxlayın.")

    return user


def require_role(*roles: str):
    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Bu əməliyyat üçün icazəniz yoxdur. Lazımi rol: {', '.join(roles)}"
            )
        return current_user
    return checker


# Hazır dependency-lər
require_teacher = require_role("teacher", "admin", "superadmin")
require_student = require_role("student")
require_parent = require_role("parent")
require_admin = require_role("admin", "superadmin")


async def require_not_demo_repetitor(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """POST/PATCH/DELETE/PUT sorğularında demo (pulsuz) planda olan repetitorları bloklayır."""
    if request.method not in ("GET", "HEAD", "OPTIONS", "DELETE"):
        t_res = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
        t = t_res.scalar_one_or_none()
        if t and t.type == "repetitor" and t.plan != "repetitor":
            raise HTTPException(
                status_code=403,
                detail="Pulsuz planda yazma əməliyyatları bağlıdır. Davam etmək üçün bizimlə əlaqə saxlayın."
            )


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_optional),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Token varsa istifadəçini qaytar, yoxdursa None."""
    if not credentials:
        return None
    try:
        payload = decode_token(credentials.credentials)
        user_id: str = payload.get("sub")
        if not user_id:
            return None
        return await get_user_by_id(db, user_id)
    except Exception:
        return None
