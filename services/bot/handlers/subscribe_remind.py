"""НейроБокс — /subscribe (подписки), /remind, /reminders."""
import re
from datetime import datetime, timedelta

from aiogram import F, Router, types

from shared.db.database import get_pool
from shared.domain.credits import get_or_create_user

router = Router()


def _parse_remind_time(text: str):
    """Парсит '30м текст', '1ч текст', '2д текст'. Возвращает (timedelta, body) или (None, None)."""
    text = (text or "").strip()
    m = re.match(r"^(\d+)\s*([м]|мин|минут|ч|час|часов|д|день|дней)\s+(.+)$", text, re.I)
    if not m:
        return None, None
    num, unit, rest = int(m.group(1)), m.group(2).lower(), m.group(3).strip()
    if not rest:
        return None, None
    if unit in ("м", "мин", "минут"):
        delta = timedelta(minutes=num)
    elif unit in ("ч", "час", "часов"):
        delta = timedelta(hours=num)
    elif unit in ("д", "день", "дней"):
        delta = timedelta(days=num)
    else:
        return None, None
    return delta, rest


def _is_remind_msg(msg: types.Message) -> bool:
    t = (msg.text or "").strip().lower()
    return t.startswith("напомни ") and len(t) > 8


@router.message(F.text, _is_remind_msg)
async def msg_remind(message: types.Message):
    text = (message.text or "").strip()
    body = text[8:].strip()  # после "напомни "
    delta, body = _parse_remind_time(body)
    if delta is None:
        await message.answer("Формат: <code>напомни 30м купить молоко</code> или <code>напомни 1ч позвонить</code>")
        return
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    remind_at = datetime.utcnow() + delta
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO reminders (user_id, text, remind_at) VALUES ($1, $2, $3)",
            message.from_user.id, body[:500], remind_at)
    await message.answer(f"✅ Напоминание через {delta}:\n<i>{body[:100]}</i>")


@router.callback_query(F.data == "screen_reminders")
async def cb_reminders(cb: types.CallbackQuery):
    await cb.answer()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, text, remind_at, sent FROM reminders WHERE user_id = $1 ORDER BY remind_at ASC LIMIT 20",
            cb.from_user.id)
    if not rows:
        await cb.message.answer("Нет активных напоминаний. Напиши: <code>напомни 30м купить молоко</code>")
        return
    lines = []
    for r in rows:
        status = "✅" if r["sent"] else "⏳"
        ts = r["remind_at"].strftime("%d.%m %H:%M") if hasattr(r["remind_at"], "strftime") else str(r["remind_at"])
        lines.append(f"{status} {ts} — {r['text'][:50]}…")
    await cb.message.answer("⏰ <b>Напоминания</b>\n\n" + "\n".join(lines))
