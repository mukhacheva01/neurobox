"""Доска объявлений: посты, лайки, комментарии, закрепление, модерация."""
from datetime import datetime

from shared.db.database import get_pool

BOARD_PAGE = 5
MAX_POSTS_PER_DAY = 3
MAX_PINNED = 3


async def count_user_posts_today(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM board_posts WHERE user_id = $1 AND created_at >= CURRENT_DATE AND NOT is_deleted",
            user_id)


async def is_banned_on_board(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT 1 FROM board_bans WHERE user_id = $1") is not None


async def get_stopwords() -> list[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT word FROM board_stopwords")
    return [r["word"].lower() for r in rows]


def contains_stopword(text: str, stopwords: list[str]) -> bool:
    t = text.lower()
    return any(w in t for w in stopwords)


async def create_post(user_id: int, text: str, photo_file_id: str | None = None) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO board_posts (user_id, text, photo_file_id) VALUES ($1, $2, $3) RETURNING id",
            user_id, text[:1000], photo_file_id)
    return row["id"]


async def list_posts(offset: int = 0, limit: int = BOARD_PAGE) -> list[dict]:
    """Сначала закреплённые, потом по дате. Без удалённых."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT p.id, p.user_id, p.text, p.photo_file_id, p.is_pinned, p.likes_count, p.comments_count, p.created_at,
                      u.username, u.first_name
               FROM board_posts p
               JOIN users u ON u.id = p.user_id
               WHERE NOT p.is_deleted
               ORDER BY p.is_pinned DESC, p.created_at DESC
               OFFSET $1 LIMIT $2""",
            offset, limit + 1)
    has_more = len(rows) > limit
    rows = rows[:limit]
    return [dict(r) for r in rows], has_more


async def get_post(post_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT p.*, u.username, u.first_name FROM board_posts p
               JOIN users u ON u.id = p.user_id WHERE p.id = $1 AND NOT p.is_deleted""", post_id)
    return dict(row) if row else None


async def user_liked(post_id: int, user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT 1 FROM board_likes WHERE post_id = $1 AND user_id = $2", post_id, user_id) is not None


async def user_liked_post_ids(user_id: int, post_ids: list[int]) -> set[int]:
    """Для каких постов из списка пользователь поставил лайк. Устраняет N+1 при рендере доски."""
    if not post_ids:
        return set()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT post_id FROM board_likes WHERE user_id = $1 AND post_id = ANY($2::bigint[])",
            user_id, post_ids)
    return {r["post_id"] for r in rows}


async def toggle_like(post_id: int, user_id: int) -> bool:
    """Вернуть True если лайк поставлен, False если снят."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            exists = await conn.fetchval("SELECT 1 FROM board_likes WHERE post_id = $1 AND user_id = $2", post_id, user_id)
            if exists:
                await conn.execute("DELETE FROM board_likes WHERE post_id = $1 AND user_id = $2", post_id, user_id)
                await conn.execute("UPDATE board_posts SET likes_count = likes_count - 1 WHERE id = $1", post_id)
                return False
            await conn.execute("INSERT INTO board_likes (post_id, user_id) VALUES ($1, $2)", post_id, user_id)
            await conn.execute("UPDATE board_posts SET likes_count = likes_count + 1 WHERE id = $1", post_id)
            return True


async def add_comment(post_id: int, user_id: int, text: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO board_comments (post_id, user_id, text) VALUES ($1, $2, $3) RETURNING id",
            post_id, user_id, text[:500])
        await conn.execute("UPDATE board_posts SET comments_count = comments_count + 1 WHERE id = $1", post_id)
    return row["id"]


async def list_comments(post_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT c.id, c.user_id, c.text, c.created_at, u.username, u.first_name
               FROM board_comments c JOIN users u ON u.id = c.user_id
               WHERE c.post_id = $1 AND NOT c.is_deleted ORDER BY c.created_at ASC""",
            post_id)
    return [dict(r) for r in rows]


async def count_pinned() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM board_posts WHERE is_pinned AND NOT is_deleted")


async def set_pinned(post_id: int, pin: bool) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if pin:
            n = await conn.fetchval("SELECT COUNT(*) FROM board_posts WHERE is_pinned AND NOT is_deleted")
            if n >= MAX_PINNED:
                return False
        await conn.execute("UPDATE board_posts SET is_pinned = $1 WHERE id = $2", pin, post_id)
    return True


async def delete_post(post_id: int, by_user_id: int) -> bool:
    """Мягкое удаление. Вернуть True если удалено."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id FROM board_posts WHERE id = $1 AND NOT is_deleted", post_id)
        if not row:
            return False
        await conn.execute("UPDATE board_posts SET is_deleted = TRUE WHERE id = $1", post_id)
    return True


async def ban_on_board(user_id: int, admin_id: int, reason: str = ""):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO board_bans (user_id, banned_by, reason) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET banned_by = $2, reason = $3",
            user_id, admin_id, reason[:500])


async def unban_on_board(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM board_bans WHERE user_id = $1", user_id)


async def get_post_author_id(post_id: int) -> int | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT user_id FROM board_posts WHERE id = $1", post_id)


async def add_complaint(post_id: int, user_id: int, reason: str = ""):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO board_complaints (post_id, user_id, reason) VALUES ($1, $2, $3)", post_id, user_id, reason[:500])


async def get_likes_since(last_notified: datetime) -> dict[int, int]:
    """post_id -> count лайков за период (для батч-уведомлений)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT post_id, COUNT(*) AS cnt FROM board_likes WHERE created_at > $1 GROUP BY post_id""",
            last_notified)
    return {r["post_id"]: r["cnt"] for r in rows}


async def board_notifications_disabled(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT board_notifications_disabled FROM users WHERE id = $1", user_id)
        return row["board_notifications_disabled"] if row else False


async def set_board_notifications(user_id: int, disabled: bool):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET board_notifications_disabled = $1, updated_at = NOW() WHERE id = $2",
            disabled, user_id)
