"""Умный пейволл: сообщение при нехватке кредитов с выгодой и релевантными пакетами."""

from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shared.domain.admin_runtime import get_admin_text
from shared.domain.credits import get_balance, get_credit_packs

BUY_PACK_ORDER = (
    "trial",
    "start",
    "lite",
    "basic",
    "standard",
    "advanced",
    "pro",
    "proplus",
    "mega",
    "ultra",
)

# Контекстные описания выгоды для каждого типа задачи
_BENEFIT_HINTS = {
    "Чат с AI": "Разблокируй GPT-5, Claude и 25+ моделей",
    "Генерация картинки": "Создавай арт, логотипы, баннеры за секунды",
    "Генерация видео": "Профессиональное видео из текста или фото",
    "Генерация музыки": "Уникальные треки под любое настроение",
    "Убрать фон с фото": "Чистый результат за 5 секунд",
    "Стилизация фото": "Превращай фото в арт любого стиля",
    "Текст с фото (OCR)": "Извлекай текст из любого изображения",
    "Веб-поиск": "AI + актуальные данные из интернета",
    "Резюме статьи": "Ключевые тезисы за 10 секунд",
    "Разбор кода": "Найди ошибки и получи улучшенный код",
    "Создание документа": "Готовый документ за минуту",
    "Озвучка текста": "Естественная озвучка на любом языке",
}


def _recommended_packs(need_cr: int, current_balance: int, packs_map: dict[str, dict], max_packs: int = 3) -> list:
    del current_balance
    out = []
    for pid in BUY_PACK_ORDER:
        if pid not in packs_map or pid == "unlimited":
            continue
        pack = packs_map[pid]
        if pack["credits"] >= need_cr:
            out.append((pid, pack))
            if len(out) >= max_packs:
                break
    if not out:
        out = [(pid, packs_map[pid]) for pid in BUY_PACK_ORDER if pid in packs_map][:max_packs]
    return out


async def smart_paywall_message(
    task_description: str,
    need_cr: int,
    user_id: int,
) -> tuple[str, types.InlineKeyboardMarkup]:
    bal = await get_balance(user_id)
    total = bal["total"]
    packs_map = await get_credit_packs()
    packs = _recommended_packs(need_cr, total, packs_map)

    try:
        from shared.domain.analytics import track_paywall_view

        await track_paywall_view(
            user_id,
            task_description=task_description,
            need_cr=need_cr,
            balance_cr=total,
            recommended_packs=[pid for pid, _ in packs],
            source="smart_paywall",
        )
    except Exception:
        pass

    benefit = _BENEFIT_HINTS.get(task_description, "Продолжай использовать все возможности AI")

    lines = [
        f"🔒 <b>Нужно {need_cr} CR</b> (у тебя {total})",
        "",
        f"💡 {benefit}",
        "",
    ]
    for index, (_, pack) in enumerate(packs):
        prefix = "⭐" if index == 0 else "•"
        discount = f" (−{pack['discount']})" if pack.get("discount") else ""
        lines.append(f"{prefix} {pack['label']} — <b>{pack['credits']} CR</b> за {pack['price_rub']} ₽{discount}")
    lines.append("")
    lines.append(await get_admin_text("paywall_trust_note", "💚 Если генерация не удалась — кредиты вернутся."))

    b = InlineKeyboardBuilder()
    for index, (pid, pack) in enumerate(packs):
        label = f"⭐ {pack['label']} — {pack['price_rub']} ₽" if index == 0 else f"{pack['label']} — {pack['price_rub']} ₽"
        b.row(types.InlineKeyboardButton(text=label, callback_data=f"buy_{pid}"))
    b.row(types.InlineKeyboardButton(text="🛒 Все пакеты", callback_data="buy_credits"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return "\n".join(lines), b.as_markup()


async def soft_paywall_hint(user_id: int, bot) -> None:
    try:
        from shared.redis.store import _get_redis

        r = await _get_redis()
        if r:
            key = f"soft_paywall:{user_id}"
            if await r.get(key):
                return
            await r.set(key, "1", ex=1800)
    except Exception:
        pass

    bal = await get_balance(user_id)
    if bal["total"] >= 5:
        return

    b = InlineKeyboardBuilder()

    try:
        from shared.db.database import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            paid_count = (
                await conn.fetchval(
                    "SELECT count(*) FROM payments WHERE user_id = $1 AND status = 'confirmed'",
                    user_id,
                )
                or 0
            )

        packs = await get_credit_packs()
        if paid_count == 0 and "welcome" in packs:
            pack = packs["welcome"]
            b.row(
                types.InlineKeyboardButton(
                    text=f"🎉 {pack['credits']} CR за {pack['price_rub']} ₽ (скидка {pack['discount']})",
                    callback_data="buy_welcome",
                )
            )
    except Exception:
        pass

    b.row(types.InlineKeyboardButton(text="🛒 Пополнить", callback_data="buy_credits"))
    try:
        await bot.send_message(
            user_id,
            f"💡 Осталось <b>{bal['total']} CR</b>. Пополни, чтобы продолжить!",
            reply_markup=b.as_markup(),
        )
    except Exception:
        pass
