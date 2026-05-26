"""НейроБокс — История чата, системный промпт, избранное, экспорт."""
from shared.db.database import get_pool
from shared.config import settings

_MAX_STORED_MESSAGES = 40


def _history_limit():
    return getattr(settings, "chat_history_limit", 20)


async def get_chat_history(user_id: int):
    """Последние N пар user/assistant. N from settings.chat_history_limit."""
    limit = _history_limit()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content FROM chat_messages WHERE user_id = $1 ORDER BY id DESC LIMIT $2",
            user_id, limit * 2)
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def append_chat_message(user_id: int, role: str, content: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO chat_messages (user_id, role, content) VALUES ($1, $2, $3)",
            user_id, role, content[:10000])
        # Efficient pruning: find the Nth newest id and delete everything older
        cutoff_id = await conn.fetchval(
            "SELECT id FROM chat_messages WHERE user_id = $1 ORDER BY id DESC OFFSET $2 LIMIT 1",
            user_id, _MAX_STORED_MESSAGES)
        if cutoff_id is not None:
            await conn.execute(
                "DELETE FROM chat_messages WHERE user_id = $1 AND id < $2",
                user_id, cutoff_id)

async def append_chat_pair(user_id: int, user_content: str, assistant_content: str):
    """Insert user + assistant messages in a single connection (batch)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO chat_messages (user_id, role, content) VALUES ($1, $2, $3)",
            [(user_id, "user", user_content[:10000]),
             (user_id, "assistant", assistant_content[:10000])])
        cutoff_id = await conn.fetchval(
            "SELECT id FROM chat_messages WHERE user_id = $1 ORDER BY id DESC OFFSET $2 LIMIT 1",
            user_id, _MAX_STORED_MESSAGES)
        if cutoff_id is not None:
            await conn.execute(
                "DELETE FROM chat_messages WHERE user_id = $1 AND id < $2",
                user_id, cutoff_id)


async def clear_chat_history(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM chat_messages WHERE user_id = $1", user_id)

async def get_system_prompt(user_id: int) -> str | None:
    """Эффективный системный промпт: из user_settings (режим/кастом) или users.system_prompt."""
    from services.bot.services.mode_service import get_effective_system_prompt
    return await get_effective_system_prompt(user_id)

async def set_system_prompt(user_id: int, prompt: str | None):
    """Обратная совместимость: пишем в users. Режимы — через mode_service."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET system_prompt = $1, updated_at = NOW() WHERE id = $2", prompt or "", user_id)

async def save_prompt(user_id: int, title: str, content: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO saved_prompts (user_id, title, content) VALUES ($1, $2, $3) RETURNING id",
            user_id, title[:200], content[:5000])
        return row["id"]

async def list_saved_prompts(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, title, content FROM saved_prompts WHERE user_id = $1 ORDER BY created_at DESC LIMIT 50",
            user_id)

async def get_saved_prompt(user_id: int, prompt_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, title, content FROM saved_prompts WHERE user_id = $1 AND id = $2",
            user_id, prompt_id)

async def get_due_reminders():
    """Напоминания, которые пора отправить. Блокировка FOR UPDATE SKIP LOCKED — без дублей при нескольких воркерах."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """SELECT id, user_id, text FROM reminders
                   WHERE sent = FALSE AND remind_at <= NOW()
                   ORDER BY remind_at ASC LIMIT 50
                   FOR UPDATE SKIP LOCKED""")
            for r in rows:
                await conn.execute("UPDATE reminders SET sent = TRUE WHERE id = $1", r["id"])
    return [dict(r) for r in rows]


async def get_subscription_reminders_due():
    """Подписки, которые истекают через 1–3 дня. Возвращает список {user_id, end_date, plan_name}."""
    from datetime import date, timedelta
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            tomorrow = date.today() + timedelta(days=1)
            end_range = date.today() + timedelta(days=3)
            rows = await conn.fetch(
                """SELECT user_id, end_date, plan_name FROM subscription_ends
                   WHERE end_date >= $1 AND end_date <= $2""",
                tomorrow, end_range)
        return [dict(r) for r in rows]
    except Exception:
        return []


async def get_users_for_balance_reminder(limit: int = 200) -> list[dict]:
    """Пользователи, которым пора отправить ненавязчивое напоминание о пополнении (раз в 3 дня).
    Условия: не забанен, нет активного безлимита/48h, последнее напоминание > 3 дней назад или не было."""
    from datetime import datetime, timedelta, timezone
    pool = await get_pool()
    try:
        now = datetime.now(timezone.utc)
        three_days_ago = now - timedelta(days=3)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id FROM users
                   WHERE is_blocked = FALSE
                     AND (unlimited_ends_at IS NULL OR unlimited_ends_at <= $1)
                     AND (full_access_48h_ends_at IS NULL OR full_access_48h_ends_at <= $1)
                     AND (last_balance_reminder_at IS NULL OR last_balance_reminder_at <= $2)
                   ORDER BY last_balance_reminder_at NULLS FIRST
                   LIMIT $3""",
                now, three_days_ago, limit)
        return [{"user_id": r["id"]} for r in rows]
    except Exception:
        return []


async def set_balance_reminder_sent(user_id: int) -> None:
    """Отметить, что пользователю отправлено напоминание о пополнении."""
    from datetime import datetime, timezone
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET last_balance_reminder_at = $1, updated_at = NOW() WHERE id = $2",
            datetime.now(timezone.utc), user_id)

async def get_chat_history_for_export(user_id: int, limit: int = 100):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content, created_at FROM chat_messages WHERE user_id = $1 ORDER BY id ASC LIMIT $2",
            user_id, limit)
    return [dict(r) for r in rows]


async def mark_user_blocked(user_id: int) -> None:
    """Пометить пользователя как заблокировавшего бота."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_blocked = TRUE, updated_at = NOW() WHERE id = $1",
            user_id,
        )
