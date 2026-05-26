"""Режимы чата: user_settings + chat_modes, эффективный system_prompt."""
from shared.db.database import get_pool


async def get_current_mode_id(user_id: int) -> int | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT current_mode_id FROM user_settings WHERE user_id = $1", user_id)
        return row["current_mode_id"] if row and row["current_mode_id"] else None


async def get_custom_mode_prompt(user_id: int) -> str | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT custom_mode_prompt FROM user_settings WHERE user_id = $1", user_id)
        return (row["custom_mode_prompt"] if row and row["custom_mode_prompt"] else None) or None


async def set_mode(user_id: int, mode_id: int | None):
    """Установить режим по id из chat_modes. None = сброс."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO user_settings (user_id, current_mode_id, custom_mode_prompt, updated_at)
               VALUES ($1, $2, NULL, NOW())
               ON CONFLICT (user_id) DO UPDATE SET current_mode_id = $2, custom_mode_prompt = NULL, updated_at = NOW()""",
            user_id, mode_id)


async def set_custom_mode(user_id: int, prompt: str | None):
    """Установить кастомный режим (Мой режим). prompt до 2000 символов."""
    if prompt is not None:
        prompt = prompt[:2000].strip() or None
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO user_settings (user_id, current_mode_id, custom_mode_prompt, updated_at)
               VALUES ($1, NULL, $2, NOW())
               ON CONFLICT (user_id) DO UPDATE SET current_mode_id = NULL, custom_mode_prompt = $2, updated_at = NOW()""",
            user_id, prompt)


async def get_effective_system_prompt(user_id: int) -> str | None:
    """Системный промпт для генерации: из режима или кастомный. Fallback на users.system_prompt (старый код)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT current_mode_id, custom_mode_prompt FROM user_settings WHERE user_id = $1", user_id)
        if row:
            if row["current_mode_id"]:
                mode = await conn.fetchrow("SELECT system_prompt FROM chat_modes WHERE id = $1", row["current_mode_id"])
                if mode and mode["system_prompt"]:
                    return mode["system_prompt"]
                return None
            if row["custom_mode_prompt"]:
                return row["custom_mode_prompt"]
        # Обратная совместимость
        u = await conn.fetchrow("SELECT system_prompt FROM users WHERE id = $1", user_id)
        return (u["system_prompt"] if u and u["system_prompt"] else None) or None


async def get_current_mode_display(user_id: int) -> str:
    """Текст для отображения текущего режима."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT current_mode_id, custom_mode_prompt FROM user_settings WHERE user_id = $1", user_id)
        if row:
            if row["current_mode_id"]:
                mode = await conn.fetchrow("SELECT name, emoji FROM chat_modes WHERE id = $1", row["current_mode_id"])
                if mode:
                    return f"{mode['emoji']} {mode['name']}"
            if row["custom_mode_prompt"]:
                p = row["custom_mode_prompt"][:50]
                return f"✏️ Мой режим: {p}..."
        u = await conn.fetchrow("SELECT system_prompt FROM users WHERE id = $1", user_id)
        if u and u["system_prompt"]:
            return f"✏️ {u['system_prompt'][:50]}..."
        return "Обычный ассистент"


async def get_all_categories_with_modes():
    """Список категорий и режимов для клавиатур. Возвращает [(category, [(id, name, emoji), ...]), ...]."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, category, emoji, sort_order FROM chat_modes ORDER BY sort_order, id")
    from itertools import groupby
    out = []
    for cat, group in groupby(rows, key=lambda r: r["category"]):
        out.append((cat, [(r["id"], r["name"], r["emoji"] or "💬") for r in group]))
    return out


async def get_modes_by_category(category: str) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, emoji FROM chat_modes WHERE category = $1 ORDER BY sort_order, id",
            category)
    return [(r["id"], r["name"], r["emoji"] or "💬") for r in rows]


async def get_mode_by_id(mode_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT id, name, system_prompt, emoji FROM chat_modes WHERE id = $1", mode_id)
