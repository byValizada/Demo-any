from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.tenant import Tenant
from app.services.auth_service import hash_password

SUPERADMIN_EMAIL  = "admin@eduai.az"
SUPERADMIN_ID     = "u-superadmin"
SYSTEM_TENANT_ID  = "tenant-system"


async def seed_database() -> None:
    async with AsyncSessionLocal() as db:
        # ID və ya email ilə artıq mövcuddursa skip et
        by_id = await db.execute(select(User).where(User.id == SUPERADMIN_ID))
        if by_id.scalar_one_or_none():
            print("[SEED] Superadmin mövcuddur (id), skip")
            return

        by_email = await db.execute(select(User).where(User.email == SUPERADMIN_EMAIL))
        if by_email.scalar_one_or_none():
            print("[SEED] Superadmin mövcuddur (email), skip")
            return

        # Sistem tenant (superadmin üçün lazımdır, istifadəçilərə görünmür)
        t_result = await db.execute(select(Tenant).where(Tenant.id == SYSTEM_TENANT_ID))
        if not t_result.scalar_one_or_none():
            system_tenant = Tenant(
                id=SYSTEM_TENANT_ID,
                name="System",
                slug="system",
                type="school",
                is_active=False,
            )
            db.add(system_tenant)
            await db.flush()

        superadmin = User(
            id=SUPERADMIN_ID,
            tenant_id=SYSTEM_TENANT_ID,
            email=SUPERADMIN_EMAIL,
            hashed_password=hash_password("superadmin2026"),
            name="Super Admin",
            role="superadmin",
            is_active=True,
        )
        db.add(superadmin)
        try:
            await db.commit()
            print("[SEED] Superadmin yaradıldı — email: admin@eduai.az")
        except Exception:
            await db.rollback()
            print("[SEED] Superadmin artıq mövcuddur, skip")
