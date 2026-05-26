"""НейроБокс — Balance, packs, price list, help."""
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.bot.handlers.model_select import IMAGE_MODELS
from shared.config import settings
from shared.domain.credits import (
    CREDIT_PRICES,
    FREE_MODELS,
    UNLIMITED_DAYS,
    VIDEO_MODELS,
    add_credits,
    confirm_payment_record,
    create_payment_record,
    get_balance,
    get_credit_pack,
    get_credit_packs,
    get_or_create_user,
    get_unlimited_ends_at,
    set_unlimited_until,
)

router = Router()

def _yookassa_configured():
    return bool(settings.enable_yookassa_payment and settings.yookassa_shop_id and settings.yookassa_secret_key)


def _cryptobot_configured():
    return bool(settings.enable_cryptobot_payment and settings.cryptobot_api_token)


def _stars_configured():
    return bool(settings.enable_stars_payment)

def _balance_kb():
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="🛒 Купить кредиты", callback_data="buy_credits"),
        types.InlineKeyboardButton(text="📊 История", callback_data="tx_history"),
    )
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    return b.as_markup()

async def _balance_text(bal: dict, unlimited_ends_at=None, user_id: int = 0) -> str:
    from datetime import datetime, timezone
    lines = [
        "💰 <b>Твой баланс</b>\n",
        f"🆓 Бесплатные: <b>{bal['free']} CR</b> (обновятся в 00:00)",
        f"💎 Купленные: <b>{bal['bought']} CR</b> (бессрочные)",
    ]
    if unlimited_ends_at:
        now = datetime.now(timezone.utc)
        end = unlimited_ends_at if unlimited_ends_at.tzinfo else unlimited_ends_at.replace(tzinfo=timezone.utc)
        if end > now:
            end_str = unlimited_ends_at.strftime("%d.%m.%Y") if hasattr(unlimited_ends_at, "strftime") else str(unlimited_ends_at)
            lines.append(f"♾️ Безлимит до <b>{end_str}</b>")
    lines.append("")
    lines.append(f"📊 Всего: <b>{bal['total']} CR</b>")
    # Расход за сегодня и 7 дней
    if user_id:
        try:
            from shared.db.database import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                spent_today = await conn.fetchval(
                    "SELECT COALESCE(SUM(ABS(amount)), 0) FROM credit_transactions WHERE user_id = $1 AND type = 'spend' AND created_at >= CURRENT_DATE",
                    user_id) or 0
                spent_week = await conn.fetchval(
                    "SELECT COALESCE(SUM(ABS(amount)), 0) FROM credit_transactions WHERE user_id = $1 AND type = 'spend' AND created_at >= CURRENT_DATE - INTERVAL '7 days'",
                    user_id) or 0
            lines.append(f"📉 Расход за сегодня: {spent_today} CR")
            lines.append(f"📉 Расход за 7 дней: {spent_week} CR")
        except Exception:
            pass
    lines.append(f"\n🆓 Бесплатно каждый день: {settings.free_daily_credits} CR")
    return "\n".join(lines)


@router.message(Command("balance"))
@router.message(F.text == "💰 Баланс")
async def msg_balance(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    bal = await get_balance(message.from_user.id)
    unlimited_ends_at = await get_unlimited_ends_at(message.from_user.id)
    await message.answer(await _balance_text(bal, unlimited_ends_at, message.from_user.id), reply_markup=_balance_kb())


@router.callback_query(F.data == "balance")
async def cb_balance(cb: types.CallbackQuery):
    await cb.answer()
    user_id = cb.from_user.id
    bal = await get_balance(user_id)
    unlimited_ends_at = await get_unlimited_ends_at(user_id)
    await cb.message.answer(await _balance_text(bal, unlimited_ends_at, user_id), reply_markup=_balance_kb())

# Порядок пакетов в «Купить кредиты»: по цене по возрастанию
BUY_PACK_ORDER = (
    "welcome", "trial", "start", "lite", "basic", "standard", "advanced", "pro", "proplus", "mega", "ultra", "unlimited",
)


async def _buy_packs() -> dict[str, dict]:
    return await get_credit_packs()


@router.callback_query(F.data == "buy_credits")
async def cb_buy(cb: types.CallbackQuery):
    await cb.answer()
    b = InlineKeyboardBuilder()
    packs = await _buy_packs()
    for pid in BUY_PACK_ORDER:
        if pid not in packs:
            continue
        pack = packs[pid]
        disc = f" 🔥{pack['discount']}" if pack.get('discount') else ""
        b.row(types.InlineKeyboardButton(
            text=f"{pack['label']} {pack['credits']:,} CR — {pack['price_rub']} ₽{disc}",
            callback_data=f"buy_{pid}"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    await cb.message.answer(
        "🛒 <b>Купить кредиты</b>\n\nЧем больше пакет — тем дешевле 💎\nНе сгорают ♾️",
        reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("buy_") & ~F.data.startswith("buy_credits"))
async def cb_buy_pack(cb: types.CallbackQuery):
    pid = cb.data.replace("buy_", "")
    pack = await get_credit_pack(pid)
    if not pack:
        await cb.answer("Не найден", show_alert=True)
        return
    await cb.answer()
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(
        text=f"✅ Оплатить {pack['price_rub']} ₽", callback_data=f"confirm_buy_{pid}"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="buy_credits"))
    if pid == "unlimited":
        await cb.message.answer(
            f"🛒 <b>{pack['label']}</b>\n\n"
            f"💰 <b>{pack['price_rub']} ₽</b> — 30 календарных дней\n\n"
            f"• Все активные функции бота — без списания CR\n"
            f"• После 30 дней период закончится автоматически",
            reply_markup=b.as_markup())
        return
    cr = pack["credits"]
    ppc = round(pack["price_rub"] / cr, 2)
    ex = [f"💬 {cr} чатов GPT nano", f"🎨 {cr // 5} картинок Flux"]
    if cr >= 75:
        ex.append(f"🎬 {cr // 75} видео Hailuo")
    if cr >= 300:
        ex.append(f"🎬 {cr // 300} видео Kling")
    disc = f"\n🏷 Скидка: <b>{pack['discount']}</b>" if pack["discount"] else ""
    await cb.message.answer(
        f"🛒 <b>{pack['label']}</b>\n\n"
        f"💎 <b>{cr:,} CR</b>\n💰 <b>{pack['price_rub']} ₽</b> ({ppc} ₽/CR){disc}\n\n"
        f"Хватит на:\n" + "\n".join(f"• {e}" for e in ex),
        reply_markup=b.as_markup())

@router.callback_query(F.data.startswith("confirm_buy_"))
async def cb_confirm(cb: types.CallbackQuery):
    """Экран выбора способа оплаты."""
    pid = cb.data.replace("confirm_buy_", "")
    pack = await get_credit_pack(pid)
    if not pack:
        await cb.answer("Не найден", show_alert=True)
        return
    await cb.answer()

    try:
        from shared.domain.analytics import track_plan_selected

        await track_plan_selected(
            user_id=cb.from_user.id,
            pack_name=pid,
            price_rub=float(pack.get("price_rub") or 0),
            credits=int(pack.get("credits") or 0),
            source="checkout",
        )
    except Exception:
        pass

    yk = {"available": False}
    if _yookassa_configured():
        try:
            from shared.domain.yookassa import get_yookassa_availability

            yk = await get_yookassa_availability()
        except Exception:
            yk = {"available": False, "message": "Карта/СБП временно недоступны."}

    b = InlineKeyboardBuilder()
    if yk.get("available"):
        b.row(
            types.InlineKeyboardButton(
                text=f"💳 Карта / СБП ({pack['price_rub']} ₽)",
                callback_data=f"pay_yoo_{pid}",
            )
        )

    stars = pack.get("price_stars", 0)
    if _stars_configured() and stars:
        b.row(
            types.InlineKeyboardButton(
                text=f"⭐ Telegram Stars ({stars} Stars)",
                callback_data=f"pay_stars_{pid}",
            )
        )

    usd = pack.get("price_usd", 0)
    has_crypto = bool(usd and _cryptobot_configured())
    if has_crypto:
        b.row(
            types.InlineKeyboardButton(
                text=f"💰 Крипта USDT/TON ({usd}$)",
                callback_data=f"pay_crypto_{pid}",
            )
        )

    if settings.enable_test_payments and not yk.get("available") and not has_crypto and not stars:
        b.row(types.InlineKeyboardButton(text="🧪 Тест (бесплатно)", callback_data=f"pay_test_{pid}"))

    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="buy_credits"))
    b.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))

    if pid == "unlimited":
        header = f"🛒 <b>{pack['label']}</b> — 30 дней"
    else:
        header = f"🛒 <b>{pack['label']}</b> — {pack['credits']:,} CR"

    hints = []
    if _yookassa_configured() and not yk.get("available"):
        hints.append("⚠️ Карта/СБП временно недоступны.")
    elif not _yookassa_configured() and not _stars_configured() and not has_crypto:
        hints.append("⚠️ Способы оплаты пока не подключены.")

    if not settings.enable_test_payments and not yk.get("available") and not has_crypto and not (_stars_configured() and stars):
        hints.append("⚠️ Сейчас нет доступного способа оплаты. Напиши в поддержку.")
    elif settings.enable_test_payments and not yk.get("available") and not has_crypto and not stars:
        hints.append("ℹ️ Сейчас доступен только тестовый режим оплаты.")

    extra = "\n" + "\n".join(hints) if hints else ""
    await cb.message.answer(
        f"{header}\n\nВыбери способ оплаты:{extra}",
        reply_markup=b.as_markup(),
    )


# --- ЮKassa ---
PAYMENT_RATE_LIMIT_PER_MIN = 5


async def _check_payment_rate_limit(user_id: int) -> bool:
    """True если можно создавать платёж (лимит 5/мин не превышен)."""
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if not r:
            return True
        key = f"nbox:payment_count:{user_id}"
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 60)
        if n > PAYMENT_RATE_LIMIT_PER_MIN:
            return False
        return True
    except Exception:
        return True


@router.callback_query(F.data.startswith("pay_yoo_"))
async def cb_pay_yookassa(cb: types.CallbackQuery):
    pid = cb.data.replace("pay_yoo_", "")
    pack = await get_credit_pack(pid)
    if not pack:
        await cb.answer("Не найден", show_alert=True)
        return
    user_id = cb.from_user.id
    amount_rub = pack["price_rub"]
    credits = pack["credits"]
    pack_label = pack["label"]

    async def _track_failed(reason: str, payment_id: str = "") -> None:
        try:
            from shared.domain.analytics import track_payment_failed

            await track_payment_failed(
                user_id=user_id,
                method="yookassa",
                pack_name=pid,
                amount_rub=float(amount_rub or 0),
                credits=int(credits or 0),
                reason=reason,
                payment_id=payment_id,
            )
        except Exception:
            pass

    if not await _check_payment_rate_limit(user_id):
        await cb.answer("⏳ Слишком много платежей. Подожди минуту.", show_alert=True)
        return

    try:
        from shared.redis.store import _get_redis

        r = await _get_redis()
        if r:
            lock_key = f"payment_lock:{user_id}"
            if await r.get(lock_key):
                await cb.answer("⏳ Платёж уже создаётся.", show_alert=True)
                return
            await r.set(lock_key, "1", ex=15)
    except Exception:
        pass

    if not _yookassa_configured():
        await _track_failed("config_missing")
        await cb.answer(
            "ЮKassa не настроена. Добавь в .env: YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY.",
            show_alert=True,
        )
        return
    if not (getattr(settings, "bot_username", None) or "").strip():
        await _track_failed("bot_username_missing")
        await cb.answer(
            "ЮKassa: укажи BOT_USERNAME в .env (ник бота без @), чтобы была ссылка возврата после оплаты.",
            show_alert=True,
        )
        return

    from shared.domain.yookassa import create_payment, get_yookassa_availability

    health = await get_yookassa_availability()
    if not health.get("available"):
        msg = health.get("message") or "Карта/СБП временно недоступны."
        await _track_failed(health.get("reason") or "unavailable")
        await cb.answer("Карта/СБП временно недоступны", show_alert=True)

        fallback_kb = InlineKeyboardBuilder()
        stars = pack.get("price_stars", 0)
        if _stars_configured() and stars:
            fallback_kb.row(
                types.InlineKeyboardButton(
                    text=f"⭐ Telegram Stars ({stars} Stars)",
                    callback_data=f"pay_stars_{pid}",
                )
            )
        usd = pack.get("price_usd", 0)
        if _cryptobot_configured() and usd:
            fallback_kb.row(
                types.InlineKeyboardButton(
                    text=f"💰 Крипта USDT/TON ({usd}$)",
                    callback_data=f"pay_crypto_{pid}",
                )
            )
        fallback_kb.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
        fallback_kb.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="buy_credits"))
        await cb.message.answer(
            f"❌ {msg}\n\nПопробуй доступный альтернативный способ оплаты ниже.",
            reply_markup=fallback_kb.as_markup(),
        )
        return

    bot_username = settings.bot_username.strip().lstrip("@")
    return_url = f"https://t.me/{bot_username}?start=pay"
    result = await create_payment(
        amount_rub=amount_rub,
        pack_name=pid,
        credits=credits,
        user_id=user_id,
        return_url=return_url,
    )
    if not result["ok"]:
        err = result.get("error", "Ошибка ЮKassa")
        if "receipt" in (err or "").lower():
            err += " Добавь в .env: YOOKASSA_RECEIPT_EMAIL=твой@email (для чека 54-ФЗ)."
        await _track_failed(err)
        await cb.answer("Ошибка создания платежа", show_alert=True)
        err_msg = (err or "")[:400]
        err_kb = InlineKeyboardBuilder()
        err_kb.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
        err_kb.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="buy_credits"))
        await cb.message.answer(
            f"❌ <b>Не удалось создать платёж ЮKassa</b>\n\n{err_msg}\n\n"
            "Проверь в .env: YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, BOT_USERNAME. "
            "Если в ЛК ЮKassa включены чеки — укажи YOOKASSA_RECEIPT_EMAIL.",
            reply_markup=err_kb.as_markup(),
        )
        return
    yoo_id = str(result["payment_id"]).strip()
    confirmation_url = (result.get("confirmation_url") or "").strip()
    if not confirmation_url:
        await _track_failed("missing_confirmation_url", payment_id=yoo_id)
        await cb.answer("Нет ссылки на оплату", show_alert=True)
        no_url_kb = InlineKeyboardBuilder()
        no_url_kb.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
        no_url_kb.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="buy_credits"))
        await cb.message.answer(
            "❌ Платёж создан без ссылки подтверждения. Напиши в поддержку — поможем завершить оплату.",
            reply_markup=no_url_kb.as_markup(),
        )
        return
    try:
        await create_payment_record(user_id, yoo_id, amount_rub, credits, pid)
    except Exception as e:
        import structlog

        structlog.get_logger().error("create_payment_record failed", user_id=user_id, payment_id=yoo_id, error=str(e))
        await cb.answer("Ошибка сохранения платежа. Ссылка ниже — оплата может пройти.", show_alert=True)

    try:
        from shared.domain.analytics import track_payment_started

        await track_payment_started(
            user_id=user_id,
            payment_id=yoo_id,
            method="yookassa",
            pack_name=pid,
            amount_rub=float(amount_rub or 0),
            credits=int(credits or 0),
        )
    except Exception:
        pass

    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text=f"💳 Оплатить {amount_rub} ₽ — переход в ЮKassa", url=confirmation_url))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    await cb.answer()
    await cb.message.answer(
        f"🛒 <b>{pack_label}</b>\n\n"
        f"💎 <b>{credits:,} CR</b> — <b>{amount_rub} ₽</b>\n\n"
        "Нажми кнопку ниже — откроется страница оплаты ЮKassa (карты, СБП).\n\n"
        f"Или открой ссылку: <a href=\"{confirmation_url}\">перейти к оплате</a>\n\n"
        "После оплаты вернись в бота — кредиты начислятся автоматически.",
        reply_markup=b.as_markup(),
    )


# --- Тестовый режим ---
@router.callback_query(F.data.startswith("pay_test_"))
async def cb_pay_test(cb: types.CallbackQuery):
    if not settings.enable_test_payments:
        await cb.answer("Тестовый режим оплаты отключен.", show_alert=True)
        return

    pid = cb.data.replace("pay_test_", "")
    pack = await get_credit_pack(pid)
    if not pack:
        await cb.answer("Не найден", show_alert=True)
        return
    user_id = cb.from_user.id
    payment_id = f"test_{pid}_{user_id}"

    try:
        from shared.domain.analytics import track_payment_started

        await track_payment_started(
            user_id=user_id,
            payment_id=payment_id,
            method="test",
            pack_name=pid,
            amount_rub=float(pack.get("price_rub") or 0),
            credits=int(pack.get("credits") or 0),
            is_test=True,
        )
    except Exception:
        pass

    if pid == "unlimited":
        await set_unlimited_until(user_id, days=UNLIMITED_DAYS)
        end_at = await get_unlimited_ends_at(user_id)
        end_str = end_at.strftime("%d.%m.%Y") if end_at and hasattr(end_at, "strftime") else ""
        await cb.answer("✅ Безлимит!", show_alert=True)
        bal = await get_balance(user_id)
        await cb.message.answer(
            f"✅ <b>Покупка!</b>\n\n♾️ {pack['label']} до <b>{end_str}</b>\n"
            f"💰 Баланс: <b>{bal['total']} CR</b>\n\n⚠️ <i>Тестовый режим.</i>"
        )
        try:
            from shared.domain.analytics import track_payment_success

            await track_payment_success(
                user_id=user_id,
                payment_id=payment_id,
                method="test",
                pack_name=pid,
                amount_rub=float(pack.get("price_rub") or 0),
                credits=int(pack.get("credits") or 0),
                is_test=True,
            )
        except Exception:
            pass
    else:
        await add_credits(user_id, pack["credits"], "purchase", f"{pack['label']} (тест)")
        await cb.answer(f"✅ +{pack['credits']:,} CR!", show_alert=True)
        bal = await get_balance(user_id)
        await cb.message.answer(
            f"✅ <b>Покупка!</b>\n\n📦 {pack['label']}\n💎 +{pack['credits']:,} CR\n"
            f"💰 Баланс: <b>{bal['total']} CR</b>\n\n⚠️ <i>Тестовый режим.</i>"
        )
        try:
            from shared.domain.analytics import track_payment_success

            await track_payment_success(
                user_id=user_id,
                payment_id=payment_id,
                method="test",
                pack_name=pid,
                amount_rub=float(pack.get("price_rub") or 0),
                credits=int(pack.get("credits") or 0),
                is_test=True,
            )
        except Exception:
            pass

# --- Telegram Stars ---
@router.callback_query(F.data.startswith("pay_stars_"))
async def cb_pay_stars(cb: types.CallbackQuery):
    pid = cb.data.replace("pay_stars_", "")
    pack = await get_credit_pack(pid)
    if not pack:
        await cb.answer("Не найден", show_alert=True)
        return
    stars = pack.get("price_stars", 0)
    if not stars:
        await cb.answer("Stars не доступны для этого пакета", show_alert=True)
        return
    await cb.answer()
    from aiogram.types import LabeledPrice

    payload = f"stars_{pid}_{cb.from_user.id}"
    await cb.message.answer_invoice(
        title=f"НейроБокс: {pack['label']}",
        description=f"{pack['credits']:,} кредитов",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label=f"{pack['credits']} CR", amount=stars)],
    )
    try:
        from shared.domain.analytics import track_payment_started

        await track_payment_started(
            user_id=cb.from_user.id,
            payment_id=payload,
            method="stars",
            pack_name=pid,
            amount_rub=0.0,
            credits=int(pack.get("credits") or 0),
            amount_stars=int(stars or 0),
        )
    except Exception:
        pass


@router.pre_checkout_query()
async def on_pre_checkout(pre_checkout: types.PreCheckoutQuery):
    """Подтверждение Stars-платежа."""
    await pre_checkout.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: types.Message):
    """Начисление CR после успешной оплаты Stars."""
    payment = message.successful_payment
    payload = payment.invoice_payload or ""
    # payload = "stars_{pack}_{user_id}"
    parts = payload.split("_", 2)
    if len(parts) < 3 or parts[0] != "stars":
        return
    pid = parts[1]
    user_id = message.from_user.id
    pack = await get_credit_pack(pid)
    if not pack:
        return
    stars_paid = payment.total_amount
    payment_id = f"stars_{payment.telegram_payment_charge_id}"
    created = await create_payment_record(user_id, payment_id, 0.0, int(pack.get("credits") or 0), pid)
    if not created:
        await message.answer("ℹ️ Этот платёж уже обработан.")
        return
    confirmed = await confirm_payment_record(payment_id)
    if not confirmed:
        await message.answer("ℹ️ Этот платёж уже обработан.")
        return
    if pid == "unlimited":
        await set_unlimited_until(user_id, days=UNLIMITED_DAYS)
        end_at = await get_unlimited_ends_at(user_id)
        end_str = end_at.strftime("%d.%m.%Y") if end_at and hasattr(end_at, "strftime") else ""
        bal = await get_balance(user_id)
        await message.answer(
            f"✅ <b>Оплата прошла!</b>\n\n♾️ Безлимит до <b>{end_str}</b>\n💰 Баланс: <b>{bal['total']} CR</b>"
        )
        try:
            from shared.domain.analytics import track_payment_success

            await track_payment_success(
                user_id=user_id,
                payment_id=payment_id,
                method="stars",
                pack_name=pid,
                amount_rub=0.0,
                credits=int(pack.get("credits") or 0),
                is_test=False,
                amount_stars=int(stars_paid or 0),
            )
        except Exception:
            pass
    else:
        await add_credits(user_id, pack["credits"], "purchase", f"{pack['label']} ({stars_paid} Stars)")
        bal = await get_balance(user_id)
        credits = pack["credits"]
        await message.answer(
            f"✅ <b>Оплата прошла!</b>\n\n💎 +{credits} CR зачислены\n"
            f"💰 Баланс: <b>{bal['total']} CR</b>\n\n"
            f"Хватит на ~{credits//5} картинок или {credits} чатов."
        )
        try:
            from shared.domain.analytics import track_payment_success

            await track_payment_success(
                user_id=user_id,
                payment_id=payment_id,
                method="stars",
                pack_name=pid,
                amount_rub=0.0,
                credits=int(credits or 0),
                is_test=False,
                amount_stars=int(stars_paid or 0),
            )
        except Exception:
            pass


# --- CryptoBot ---
@router.callback_query(F.data.startswith("pay_crypto_"))
async def cb_pay_crypto(cb: types.CallbackQuery):
    pid = cb.data.replace("pay_crypto_", "")
    pack = await get_credit_pack(pid)
    if not pack:
        await cb.answer("Не найден", show_alert=True)
        return
    usd = pack.get("price_usd", 0)
    if not usd or not _cryptobot_configured():
        await cb.answer("Крипто-оплата не настроена", show_alert=True)
        return
    await cb.answer("💰 Создаю инвойс...")
    from shared.domain.cryptobot import create_crypto_invoice

    result = await create_crypto_invoice(usd, pid, pack["credits"], cb.from_user.id)
    if not result["ok"]:
        try:
            from shared.domain.analytics import track_payment_failed

            await track_payment_failed(
                user_id=cb.from_user.id,
                method="cryptobot",
                pack_name=pid,
                amount_rub=0.0,
                credits=int(pack.get("credits") or 0),
                reason=result.get("error", "CryptoBot error"),
            )
        except Exception:
            pass
        err_kb = InlineKeyboardBuilder()
        err_kb.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
        err_kb.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="buy_credits"))
        await cb.message.answer(
            f"❌ {result.get('error', 'Ошибка CryptoBot')}",
            reply_markup=err_kb.as_markup(),
        )
        return
    try:
        from shared.domain.analytics import track_payment_started

        await track_payment_started(
            user_id=cb.from_user.id,
            payment_id=f"crypto_{result.get('invoice_id')}",
            method="cryptobot",
            pack_name=pid,
            amount_rub=0.0,
            credits=int(pack.get("credits") or 0),
            amount_usd=float(usd or 0),
        )
    except Exception:
        pass
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text=f"💰 Оплатить {usd}$ в крипте", url=result["pay_url"]))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    await cb.message.answer(
        f"🛒 <b>{pack['label']}</b>\n\n"
        f"💎 <b>{pack['credits']:,} CR</b> — <b>{usd}$ USDT</b>\n\n"
        f"Нажми кнопку — откроется @CryptoBot для оплаты.\n"
        f"Кредиты начислятся автоматически после оплаты.",
        reply_markup=b.as_markup())


@router.callback_query(F.data == "price_list")
async def cb_price(cb: types.CallbackQuery):
    await cb.answer()
    from shared.config.text_models import TEXT_MODELS as TM

    L = ["💎 <b>Прайс-лист НейроБокс</b>\n", "\n<b>💬 Текст:</b>"]
    for name, mid, price_str, is_free, *_ in TM:
        del price_str, is_free
        cr = CREDIT_PRICES.get(mid, "?")
        f = " 🆓" if mid in FREE_MODELS else ""
        L.append(f"  {name} — <b>{cr} CR</b>{f}")
    L.append("\n<b>🎨 Картинки:</b>")
    for name, mid, _, _ in IMAGE_MODELS:
        f = " 🆓" if mid in FREE_MODELS else ""
        L.append(f"  {name} — <b>{CREDIT_PRICES.get(mid, '?')} CR</b>{f}")
    if settings.enable_video:
        L.append("\n<b>🎬 Видео:</b>")
        for mid, info in VIDEO_MODELS.items():
            L.append(f"  {info['label']} — <b>{info['cr']} CR</b>")
    L.append("\n<b>🎤 Голос:</b>")
    L.append("  Whisper (STT) — <b>5 CR</b>/мин")
    if settings.enable_tts:
        L.append("  Edge TTS — <b>0 CR</b> 🆓")
        L.append("  OpenAI TTS — <b>3 CR</b>")
        L.append("  OpenAI TTS HD — <b>8 CR</b>")
    else:
        L.append("  Озвучка текста временно отключена")
    if settings.enable_music:
        L.append("\n<b>🎵 Музыка:</b>")
        L.append(f"  MusicGen — <b>{CREDIT_PRICES.get('musicgen', 15)} CR</b>")
        L.append(f"  Suno v4 — <b>{CREDIT_PRICES.get('suno-v4', 50)} CR</b>")
    L.append("\n🆓 = бесплатные CR")
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="🛒 Купить CR", callback_data="buy_credits"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    await cb.message.answer("\n".join(L), reply_markup=b.as_markup())

@router.callback_query(F.data == "help_chat")
async def cb_hc(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.answer("💬 <b>Чат с AI</b>\n\nНапиши вопрос.\nСменить модель: /model")

@router.callback_query(F.data == "help_images")
async def cb_hi(cb: types.CallbackQuery):
    await cb.answer()
    await cb.message.answer("🎨 <b>Картинки</b>\n\n<code>/img описание</code>")

@router.callback_query(F.data == "help_video")
async def cb_hvid(cb: types.CallbackQuery):
    await cb.answer()
    if not settings.enable_video:
        await cb.message.answer("🎬 Видео временно недоступно. Напиши в поддержку, если нужен ранний доступ.")
        return
    await cb.message.answer(
        "🎬 <b>Видео</b>\n\n"
        "<code>/video описание</code>\n"
        "Или фото + <code>/video промпт</code>\n\n"
        "Выбрать модель: /setvideo"
    )
@router.callback_query(F.data == "help_voice")
async def cb_hv(cb: types.CallbackQuery):
    await cb.answer()
    if settings.enable_tts:
        await cb.message.answer(
            "🔊 <b>Голос</b>\n\n"
            "🎤 Голосовое → текст (5 CR/мин 🆓)\n"
            "🔊 <code>/voice текст</code>\n\n/settts /setvoice"
        )
        return
    await cb.message.answer(
        "🎙 <b>Голос</b>\n\n"
        "🎤 Голосовое → текст (5 CR/мин 🆓)\n"
        "Озвучка текста временно отключена до восстановления провайдера."
    )

@router.callback_query(F.data == "help_music")
async def cb_hm(cb: types.CallbackQuery):
    await cb.answer()
    if not settings.enable_music:
        await cb.message.answer("🎵 Генерация музыки временно недоступна.")
        return
    await cb.message.answer(
        "🎵 <b>Музыка</b>\n\n<code>/music описание</code>\n\n"
        f"<b>{CREDIT_PRICES['musicgen']}</b> за трек"
    )
@router.callback_query(F.data == "tx_history")
async def cb_tx_history(cb: types.CallbackQuery):
    """История последних транзакций пользователя."""
    await cb.answer()
    user_id = cb.from_user.id
    from shared.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT amount, type, description, model, created_at FROM credit_transactions "
            "WHERE user_id = $1 ORDER BY created_at DESC LIMIT 20", user_id)
    if not rows:
        b = InlineKeyboardBuilder()
        b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="balance"))
        await cb.message.answer("📭 История пуста. Напиши боту что-нибудь!", reply_markup=b.as_markup())
        return
    lines = ["📊 <b>Последние операции</b>\n"]
    for r in rows:
        dt = r["created_at"].strftime("%d.%m %H:%M") if hasattr(r["created_at"], "strftime") else ""
        amt = r["amount"]
        sign = f"+{amt}" if amt > 0 else str(amt)
        tp = r["type"] or ""
        desc = (r["description"] or r["model"] or tp)[:40]
        lines.append(f"<code>{dt}</code> | {sign} CR | {desc}")
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="◀️ К балансу", callback_data="balance"))
    await cb.message.answer("\n".join(lines), reply_markup=b.as_markup())
