"""Логирование действий админа."""
from shared.db.database import get_pool


async def log_admin(admin_id: int, action: str, details: dict = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO admin_logs (admin_id, action, details) VALUES ($1, $2, $3)",
            admin_id, action[:80], details)
