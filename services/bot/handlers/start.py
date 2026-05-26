"""НейроБокс — /start, /menu, /admin, главное меню, экраны по кнопкам."""
import structlog
from aiogram import F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.bot.keyboards.main import (
    back_to_main_kb,
    get_main_menu_kb,
    persistent_menu_kb,
)
from shared.config import settings
from shared.domain.admin_runtime import get_admin_text, save_user_acquisition
from shared.domain.credits import (
    get_balance,
    get_onboarded,
    get_or_create_user,
    get_trial_status,
    set_onboarded,
    start_trial,
    try_grant_daily_login_bonus,
)

router = Router()
_log = structlog.get_logger()

def _is_admin(user_id: int) -> bool:
    if user_id in settings.admin_id_list:
        return True
    if not settings.admin_ids:
        return False
    try:
        ids = [int(x.strip()) for x in settings.admin_ids.split(",") if x.strip()]
        return user_id in ids
    except (ValueError, AttributeError):
        return False


async def _admin_denied(event, context: str = "") -> None:
    """Тихий отказ неадмину: логирование + закрытие callback без текста."""
    user_id = getattr(event.from_user, "id", None) if getattr(event, "from_user", None) else None
    _log.warning("admin_access_denied", user_id=user_id, context=context or "admin")
    if isinstance(event, types.CallbackQuery):
        try:
            await event.answer()
        except Exception:
            pass

START_BODY = """🤖 <b>НейроБокс</b> — AI в одном боте

✍️ Тексты · 🎨 Картинки · 💻 Код · 📄 Документы · 🎤 Транскрибация

💰 Баланс: <b>{credits}</b> кредитов"""

START_BODY_PERSONAL = """👋 {name}, привет!

🤖 <b>НейроБокс</b> — AI в одном боте
✍️ Тексты · 🎨 Картинки · 💻 Код · 📄 Документы · 🎤 Транскрибация

💰 Баланс: <b>{credits}</b> кредитов"""

START_BODY_TRIAL_ACTIVE = """🤖 <b>НейроБокс</b> — AI в одном боте

✍️ Тексты · 🎨 Картинки · 💻 Код · 📄 Документы · 🎤 Транскрибация

⏱ <b>Безлимит: осталось {expires}</b>
💰 Баланс: <b>{credits}</b> кредитов"""

async def _send_onboarding_if_new(message: types.Message, user: dict) -> None:
    """Компактный онбординг для нового пользователя (создан менее 2 мин назад)."""
    from datetime import datetime, timezone
    created = user.get("created_at")
    if not created:
        return
    if getattr(created, "tzinfo", None) is None:
        created = created.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - created).total_seconds() < 120:
        free = getattr(settings, "free_daily_credits", 20)
        template = await get_admin_text(
            "welcome_text",
            (
                "👋 Добро пожаловать в НейроБокс, {first_name}!\n\n"
                "Текст, картинки, документы и транскрибация — в одном боте.\n\n"
                "🎁 Тебе начислено {free} CR — попробуй прямо сейчас!\n\n"
                "Напиши вопрос, пришли фото или отправь голосовое — бот сразу даст результат."
            ),
        )
        welcome = template.format(
            first_name=message.from_user.first_name or "друг",
            free=free,
        )
        b = InlineKeyboardBuilder()
        b.row(types.InlineKeyboardButton(text="🚀 Активировать 45 мин безлимита", callback_data="trial_activate"))
        b.row(
            types.InlineKeyboardButton(text="💬 Задай вопрос", callback_data="screen_text"),
            types.InlineKeyboardButton(text="🎨 Картинка", callback_data="screen_images"),
        )
        b.row(types.InlineKeyboardButton(text="🎉 150 CR за 29 ₽ (скидка 70%)", callback_data="buy_welcome"))
        b.row(types.InlineKeyboardButton(text="📖 Как пользоваться", callback_data="guide:start"))
        try:
            await message.answer(welcome, reply_markup=b.as_markup())
        except Exception:
            pass


def _ref_code_from_start(text: str) -> str | None:
    t = (text or "").strip()
    if t.startswith("/start ref_"):
        return t.replace("/start ref_", "").strip().split()[0]
    return None


async def _get_user_models(user_id: int) -> dict:
    """Fetch all model preferences in a single DB query."""
    from shared.domain.credits import get_all_user_models

    return await get_all_user_models(user_id)


async def _main_menu_text_and_kb(user_id: int):
    """Текст и клавиатура главного меню с учётом пробного периода и launch-флагов."""
    bal = await get_balance(user_id)
    trial = await get_trial_status(user_id)
    add_48h = False
    if settings.enable_full_access_48h:
        from shared.domain.credits import get_48h_status

        status_48h = await get_48h_status(user_id)
        add_48h = status_48h["can_activate"]
    if trial["is_active"] and trial.get("expires_at"):
        from datetime import datetime, timezone
        exp = trial["expires_at"]
        now = datetime.now(timezone.utc)
        if getattr(exp, "tzinfo", None) is None and exp is not None:
            exp = exp.replace(tzinfo=timezone.utc)
        mins_left = max(0, int((exp - now).total_seconds() // 60))
        expires_str = f"{mins_left} мин" if mins_left > 0 else "0 мин"
        text = START_BODY_TRIAL_ACTIVE.format(credits=bal["total"], expires=expires_str)
        return text, get_main_menu_kb(
            bal["total"],
            add_trial_button=False,
            add_48h_button=add_48h,
            user_id=user_id,
        )
    if trial["can_activate"]:
        return START_BODY.format(credits=bal["total"]), get_main_menu_kb(
            bal["total"],
            add_trial_button=True,
            add_48h_button=add_48h,
            user_id=user_id,
        )
    return START_BODY.format(credits=bal["total"]), get_main_menu_kb(
        bal["total"],
        add_trial_button=False,
        add_48h_button=add_48h,
        user_id=user_id,
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    text, kb = await _main_menu_text_and_kb(message.from_user.id)
    await message.answer("✅ Текущий сценарий отменён.", reply_markup=kb)


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    text = (message.text or "").strip()
    ref_code = _ref_code_from_start(text)
    if " pay" in text or text == "pay":
        from shared.db.database import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT * FROM payments
                   WHERE user_id = $1
                     AND status = 'pending'
                     AND payment_id NOT LIKE 'stars_%'
                     AND payment_id NOT LIKE 'crypto_%'
                     AND payment_id NOT LIKE 'test_%'
                   ORDER BY created_at DESC
                   LIMIT 1""",
                user_id,
            )
        if row:
            from shared.domain.yookassa import get_payment

            res = await get_payment(row["payment_id"])
            if res.get("ok") and res.get("status") == "succeeded":
                from shared.domain.credits import (
                    UNLIMITED_DAYS,
                    add_credits,
                    confirm_payment_record,
                    get_credit_pack,
                    get_unlimited_ends_at,
                    set_unlimited_until,
                )
                confirmed = await confirm_payment_record(row["payment_id"])
                if confirmed:
                    pack_name = confirmed["pack_name"]
                    if pack_name == "unlimited":
                        await set_unlimited_until(user_id, days=UNLIMITED_DAYS)
                        end_at = await get_unlimited_ends_at(user_id)
                        end_str = end_at.strftime("%d.%m.%Y") if end_at and hasattr(end_at, "strftime") else ""
                        text, kb = await _main_menu_text_and_kb(user_id)
                        await message.answer(
                            f"✅ <b>Оплата прошла!</b>\n\n"
                            f"♾️ Безлимит активен до <b>{end_str}</b> (30 дн.).\n\n" + text,
                            reply_markup=kb,
                        )
                    else:
                        pack = await get_credit_pack(pack_name) or {}
                        await add_credits(
                            user_id,
                            confirmed["credits_amount"],
                            "purchase",
                            f"{pack.get('label', pack_name)} ({confirmed['amount_rub']} ₽)",
                        )
                        text, kb = await _main_menu_text_and_kb(user_id)
                        await message.answer(
                            f"✅ <b>Оплата прошла!</b>\n\n"
                            f"💎 +{confirmed['credits_amount']:,} CR начислены.\n\n" + text,
                            reply_markup=kb,
                        )
                    return

            text, kb = await _main_menu_text_and_kb(user_id)
            status = (res.get("status") or "").strip()
            if res.get("ok") and status in {"pending", "waiting_for_capture"}:
                prefix = (
                    "⏳ Платёж ещё не завершён в ЮKassa. "
                    "Если уже оплатил, подожди 10–30 секунд и снова открой /start."
                )
            elif res.get("ok") and status:
                prefix = f"ℹ️ Текущий статус платежа в ЮKassa: <b>{status}</b>."
            else:
                err = (res.get("error") or "").strip()
                prefix = "⚠️ Не удалось автоматически проверить статус платежа."
                if err:
                    prefix += f"\nПричина: {err}"
                prefix += "\nПопробуй ещё раз позже или выбери другой способ оплаты."
            await message.answer(prefix + "\n\n" + text, reply_markup=kb)
            return

        await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name, ref_code)
        await save_user_acquisition(user_id, text.replace("/start", "", 1).strip())
        text, kb = await _main_menu_text_and_kb(user_id)
        await message.answer("Платёж для проверки не найден.\n\n" + text, reply_markup=kb)
        return

    user = await get_or_create_user(
        user_id, message.from_user.username, message.from_user.first_name, ref_code)
    await save_user_acquisition(user_id, text.replace("/start", "", 1).strip())
    # Analytics: bot_start
    try:
        from shared.domain.analytics import track
        is_new = user.get("credits_total_spent", 0) == 0 and user.get("credits_bought", 0) <= 50
        await track("bot_start", user_id, is_new=is_new, ref_code=ref_code or "")
    except Exception:
        pass
    onboarded = await get_onboarded(user_id)
    show_quickstart = False
    if not onboarded:
        show_quickstart = True
        try:
            from shared.domain.analytics import track

            await track("onboarding_started", user_id, variant="quickstart")
        except Exception:
            pass
        await set_onboarded(user_id)
    bonus = await try_grant_daily_login_bonus(user_id)
    text, kb = await _main_menu_text_and_kb(user_id)
    trial = await get_trial_status(user_id)
    can_trial = trial["can_activate"]
    if bonus and isinstance(bonus, dict):
        amt = bonus.get("amount", 5)
        streak = bonus.get("streak", 1)
        streak_bonus = bonus.get("streak_bonus", 0)
        bonus_text = f"🎁 <b>Ежедневный бонус:</b> +{amt} CR!"
        if streak > 1:
            bonus_text += f"\n🔥 Серия входов: <b>{streak} дн. подряд</b>"
        if streak_bonus:
            bonus_text += f" (+{streak_bonus} бонус)"
        reply_kb = persistent_menu_kb(amt, add_trial=can_trial)
        await message.answer(bonus_text, reply_markup=reply_kb)
        await message.answer(text, reply_markup=reply_kb)
    elif bonus:
        reply_kb = persistent_menu_kb(5, add_trial=can_trial)
        await message.answer("🎁 <b>Ежедневный бонус:</b> +5 CR!", reply_markup=reply_kb)
        await message.answer(text, reply_markup=reply_kb)
    else:
        await message.answer(text, reply_markup=persistent_menu_kb(0, add_trial=can_trial))

    if show_quickstart:
        try:
            from shared.domain.analytics import track

            await track("onboarding_completed", user_id, variant="quickstart")
        except Exception:
            pass
        await _send_onboarding_if_new(message, user)


@router.message(F.text == "📋 Главное меню")
async def btn_main_menu(message: types.Message):
    """Обработка нажатия постоянной кнопки 'Главное меню' (если оставлена где-то)."""
    await get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.first_name)
    await try_grant_daily_login_bonus(message.from_user.id)
    text, _ = await _main_menu_text_and_kb(message.from_user.id)
    trial = await get_trial_status(message.from_user.id)
    await message.answer(text, reply_markup=persistent_menu_kb(0, add_trial=trial["can_activate"]))


@router.message(Command("restart"))
async def cmd_restart(message: types.Message):
    """Перезапуск бота — показать главное меню с постоянными кнопками."""
    await get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.first_name)
    await try_grant_daily_login_bonus(message.from_user.id)
    text, _ = await _main_menu_text_and_kb(message.from_user.id)
    trial = await get_trial_status(message.from_user.id)
    await message.answer(text, reply_markup=persistent_menu_kb(0, add_trial=trial["can_activate"]))


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(cb: types.CallbackQuery):
    await cb.answer()
    text, _ = await _main_menu_text_and_kb(cb.from_user.id)
    trial = await get_trial_status(cb.from_user.id)
    await cb.message.answer(text, reply_markup=persistent_menu_kb(0, add_trial=trial["can_activate"]))


@router.callback_query(F.data == "onboarding_step_1")
async def cb_onboarding_step_1(cb: types.CallbackQuery):
    await cb.answer()
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="Дальше →", callback_data="onboarding_step_2"))
    await cb.message.answer(
        "1️⃣ <b>Я умею решать рабочие задачи через AI.</b>\n\n"
        "💬 Вопрос — ответ в чате\n🎨 Описание — картинка\n📄 Файл — разбор документа\n🎙 Голосовое — транскрибация",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data == "onboarding_step_2")
async def cb_onboarding_step_2(cb: types.CallbackQuery):
    await cb.answer()
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="Попробовать", callback_data="screen_text"),
        types.InlineKeyboardButton(text="Дальше →", callback_data="onboarding_step_3"),
    )
    await cb.message.answer(
        "2️⃣ <b>Выбирай модель под задачу</b> — от быстрых до продвинутых.\n\n"
        "GPT-5, Claude, Gemini, DeepSeek, Flux и другие — в одном месте.",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data == "onboarding_step_3")
async def cb_onboarding_step_3(cb: types.CallbackQuery):
    await cb.answer()
    free = getattr(settings, "free_daily_credits", 20)
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="Поехали 🚀", callback_data="onboarding_done"))
    await cb.message.answer(
        f"3️⃣ <b>У тебя {free} бесплатных кредитов каждый день.</b>\n\n"
        "Пополняй при необходимости — пакеты от 29 ₽. Начнём?",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data == "onboarding_done")
async def cb_onboarding_done(cb: types.CallbackQuery):
    await cb.answer()
    await set_onboarded(cb.from_user.id)
    text, _ = await _main_menu_text_and_kb(cb.from_user.id)
    trial = await get_trial_status(cb.from_user.id)
    await cb.message.answer(text, reply_markup=persistent_menu_kb(0, add_trial=trial["can_activate"]))


@router.callback_query(F.data == "trial_activate")
async def cb_trial_activate(cb: types.CallbackQuery):
    ok = await start_trial(cb.from_user.id)
    if ok:
        from shared.domain.credits import TRIAL_DURATION_MINUTES
        await cb.answer("Безлимит на 45 минут активирован!", show_alert=True)
        text, _ = await _main_menu_text_and_kb(cb.from_user.id)
        trial = await get_trial_status(cb.from_user.id)
        await cb.message.answer(
            f"✅ <b>Безлимит на {TRIAL_DURATION_MINUTES} мин активирован!</b>\n\n"
            f"С этого момента 45 минут — все функции без списания CR.\n\n" + text,
            reply_markup=persistent_menu_kb(0, add_trial=trial["can_activate"]))
    else:
        await cb.answer("Ты уже использовал пробный период ранее.", show_alert=True)


@router.message(F.text == "🚀 45 мин безлимита")
async def btn_trial_activate(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    ok = await start_trial(message.from_user.id)
    if ok:
        from shared.domain.credits import TRIAL_DURATION_MINUTES

        text, _ = await _main_menu_text_and_kb(message.from_user.id)
        trial = await get_trial_status(message.from_user.id)
        await message.answer(
            f"✅ <b>Безлимит на {TRIAL_DURATION_MINUTES} мин активирован!</b>\n\n"
            f"С этого момента 45 минут — все функции без списания CR.\n\n" + text,
            reply_markup=persistent_menu_kb(0, add_trial=trial["can_activate"]),
        )
    else:
        await message.answer("Ты уже использовал пробный период ранее.")


@router.callback_query(F.data == "full_access_48h_activate")
async def cb_full_access_48h(cb: types.CallbackQuery):
    """Активация полного доступа на 48 часов (строго один раз на пользователя)."""
    if not settings.enable_full_access_48h:
        await cb.answer("Акция сейчас недоступна", show_alert=True)
        return

    from shared.domain.credits import (
        FULL_ACCESS_48H_HOURS,
        activate_48h_full_access,
        get_48h_status,
    )

    await cb.answer()
    user_id = cb.from_user.id
    activated_now = await activate_48h_full_access(user_id)
    status = await get_48h_status(user_id)
    text, kb = await _main_menu_text_and_kb(user_id)

    if status["is_active"] and status.get("ends_at"):
        end = status["ends_at"]
        end_str = end.strftime("%d.%m.%Y %H:%M") if hasattr(end, "strftime") else str(end)
        if activated_now:
            await cb.message.answer(
                f"✅ <b>Полный доступ на {FULL_ACCESS_48H_HOURS} ч активирован!</b>\n\n"
                f"До <b>{end_str}</b> весь функционал бота без списания кредитов.\n\n{text}",
                reply_markup=kb,
            )
        else:
            await cb.message.answer(
                f"ℹ️ Полный доступ уже был активирован ранее и сейчас действует до <b>{end_str}</b>.\n\n{text}",
                reply_markup=kb,
            )
    else:
        await cb.message.answer(
            "ℹ️ Полный доступ на 48 часов можно активировать только один раз.\n"
            f"Ты уже использовал эту возможность.\n\n{text}",
            reply_markup=kb,
        )


# ── Экраны функций (по кнопкам главного меню и постоянной клавиатуре) ──

async def _reply_screen_text(target, user_id: int):
    from services.bot.keyboards.main import _short
    from shared.domain.credits import CREDIT_PRICES, get_user_model
    model = await get_user_model(user_id, "text")
    cost = CREDIT_PRICES.get(model, "?")
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="⚙️ Сменить модель", callback_data="select_text_model"))
    b.row(types.InlineKeyboardButton(text="🗑 Очистить контекст", callback_data=f"clear_yes:{user_id}"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    await target.answer(
        f"💬 <b>Чат с AI</b>\n\n"
        f"Просто напиши сообщение — бот ответит.\n"
        f"Отправь фото/видео с подписью — бот проанализирует или отредактирует.\n"
        f"Голосовое сообщение — бот распознает и ответит.\n\n"
        f"🤖 Модель: <b>{_short(model)}</b> ({cost} CR)\n"
        f"🔄 /clear — очистить контекст диалога",
        reply_markup=b.as_markup())


@router.message(F.text == "💬 Чат")
async def btn_chat(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _reply_screen_text(message, message.from_user.id)


@router.callback_query(F.data == "screen_text")
async def cb_screen_text(cb: types.CallbackQuery):
    await cb.answer()
    await _reply_screen_text(cb.message, cb.from_user.id)

async def _reply_screen_images(target, user_id: int):
    from services.bot.keyboards.main import _short
    from shared.domain.credits import CREDIT_PRICES, get_user_model
    model = await get_user_model(user_id, "image")
    cost = CREDIT_PRICES.get(model, "?")
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="⚙️ Сменить модель", callback_data="select_image_model"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    await target.answer(
        f"🎨 <b>Генерация картинок</b>\n\n"
        f"Открой раздел и введи описание картинки.\n"
        f"📷 Фото + подпись «измени...» — редактирование\n\n"
        f"🖼 Модель: <b>{_short(model)}</b> ({cost} CR)",
        reply_markup=b.as_markup())


@router.message(F.text == "🎨 Картинка")
async def btn_images(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _reply_screen_images(message, message.from_user.id)


@router.callback_query(F.data == "screen_images")
async def cb_screen_images(cb: types.CallbackQuery):
    await cb.answer()
    await _reply_screen_images(cb.message, cb.from_user.id)

async def _reply_screen_video(target, user_id: int):
    if not settings.enable_video:
        b = InlineKeyboardBuilder()
        b.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
        b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
        await target.answer(
            "🎬 <b>Генерация видео</b> временно недоступна.\n\n"
            "Сейчас в боте доступны текст, картинки, документы и транскрибация.",
            reply_markup=b.as_markup(),
        )
        return
    from services.bot.keyboards.main import _short
    from shared.domain.credits import CREDIT_PRICES, get_user_model
    model = await get_user_model(user_id, "video")
    cost = CREDIT_PRICES.get(model, "?")
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="⚙️ Сменить модель", callback_data="vmodel_select"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    await target.answer(
        f"🎬 <b>Генерация видео</b>\n\n"
        f"Открой раздел Видео в меню и введи описание.\n"
        f"📷 Фото + подпись — из фото\n\n"
        f"🎥 Модель: <b>{_short(model)}</b> ({cost} CR)",
        reply_markup=b.as_markup())


@router.message(F.text == "🎬 Видео")
async def btn_video(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _reply_screen_video(message, message.from_user.id)


@router.callback_query(F.data == "screen_video")
async def cb_screen_video(cb: types.CallbackQuery):
    await cb.answer()
    await _reply_screen_video(cb.message, cb.from_user.id)

async def _reply_screen_voice(target, user_id: int):
    b = InlineKeyboardBuilder()
    if settings.enable_tts:
        from services.bot.keyboards.main import _short
        from shared.domain.credits import CREDIT_PRICES, get_user_model

        tts = await get_user_model(user_id, "tts")
        b.row(types.InlineKeyboardButton(text="⚙️ Сменить TTS", callback_data="tts_select_model"))
        b.row(types.InlineKeyboardButton(text="🎤 Сменить голос", callback_data="voice_select_menu"))
        b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
        await target.answer(
            "🎤 <b>Озвучка текста</b>\n\n"
            "Напиши текст — бот озвучит. Голосовое → распознаёт + ответ AI.\n"
            "Если озвучка временно недоступна, кредиты автоматически возвращаются.\n\n"
            f"🔊 Модель: <b>{_short(tts)}</b> ({CREDIT_PRICES.get(tts, '?')} CR)",
            reply_markup=b.as_markup(),
        )
        return

    b.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    await target.answer(
        "🎙 <b>Голосовые сообщения</b>\n\n"
        "Отправь голосовое сообщение или кружок — бот распознает речь и ответит текстом.\n\n"
        "🔊 Озвучка текста сейчас временно отключена до восстановления провайдера.",
        reply_markup=b.as_markup(),
    )


@router.message(F.text.in_({"🎤 Озвучка", "🎙 Голос"}))
async def btn_voice(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _reply_screen_voice(message, message.from_user.id)


@router.callback_query(F.data == "screen_voice")
async def cb_screen_voice(cb: types.CallbackQuery):
    await cb.answer()
    await _reply_screen_voice(cb.message, cb.from_user.id)

async def _reply_screen_music(target, user_id: int):
    if not settings.enable_music:
        b = InlineKeyboardBuilder()
        b.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
        b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
        await target.answer(
            "🎵 <b>Генерация музыки</b> временно недоступна.\n\n"
            "Оставили только стабильные сценарии: текст, картинки, документы и транскрибация.",
            reply_markup=b.as_markup(),
        )
        return
    from services.bot.keyboards.main import _short
    from shared.domain.credits import CREDIT_PRICES, get_user_model
    music = await get_user_model(user_id, "music")
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="⚙️ Сменить модель", callback_data="select_music_model"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    await target.answer(
        f"🎵 <b>Генерация музыки</b>\n\n"
        f"Открой раздел Музыка в меню и введи описание трека.\n\n"
        f"🎵 Модель: <b>{_short(music)}</b> ({CREDIT_PRICES.get(music, '?')} CR)",
        reply_markup=b.as_markup())


@router.message(F.text == "🎵 Музыка")
async def btn_music(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _reply_screen_music(message, message.from_user.id)


@router.callback_query(F.data == "screen_music")
async def cb_screen_music(cb: types.CallbackQuery):
    await cb.answer()
    await _reply_screen_music(cb.message, cb.from_user.id)

@router.callback_query(F.data == "screen_photo")
async def cb_screen_photo(cb: types.CallbackQuery):
    await cb.answer()
    from services.bot.keyboards.main import _short
    from shared.domain.credits import get_user_model
    text_model = await get_user_model(cb.from_user.id, "text")
    img_model = await get_user_model(cb.from_user.id, "image")
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    await cb.message.answer(
        f"📷 <b>Фото → AI</b>\n\n"
        f"Отправь фото с подписью:\n\n"
        f"<b>Анализ</b> (текстовая модель: {_short(text_model)}):\n"
        f"• «переведи текст» — прочитает и переведёт\n"
        f"• «реши задачу» — решит с фото\n"
        f"• «что здесь?» — опишет содержимое\n\n"
        f"<b>Редактирование</b> (модель картинок: {_short(img_model)}):\n"
        f"• «измени цвет» — изменит цвет\n"
        f"• «сделай в стиле аниме» — стилизует\n"
        f"• «замени фон» — заменит фон\n\n"
        f"<b>Инструменты</b> (команды в подписи):\n"
        f"• <code>/rmbg</code> — убрать фон (5 CR)\n"
        f"• <code>/style описание</code> — стилизация (8 CR)\n"
        f"• <code>/ocr</code> — извлечь текст (3 CR)",
        reply_markup=b.as_markup())

async def _reply_screen_docs(target, user_id: int):
    from services.bot.keyboards.main import _short
    from shared.domain.credits import CREDIT_PRICES, get_user_model
    model = await get_user_model(user_id, "text")
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="⚙️ Сменить модель", callback_data="select_text_model"))
    b.row(types.InlineKeyboardButton(text="◀️ Меню", callback_data="main_menu"))
    await target.answer(
        f"📄 <b>Документы</b>\n\n"
        f"Отправь файл — бот проанализирует (PDF, DOCX, TXT, изображения).\n"
        f"Подпись = вопрос к файлу.\n\n"
        f"🤖 Модель: <b>{_short(model)}</b> ({CREDIT_PRICES.get(model, '?')} CR)",
        reply_markup=b.as_markup())


@router.message(F.text == "📄 Документы")
async def btn_docs(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _reply_screen_docs(message, message.from_user.id)


@router.callback_query(F.data == "screen_docs")
async def cb_screen_docs(cb: types.CallbackQuery):
    await cb.answer()
    await _reply_screen_docs(cb.message, cb.from_user.id)

async def _reply_clear_confirm(target, user_id: int):
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="✅ Да, очистить", callback_data=f"clear_yes:{user_id}"),
        types.InlineKeyboardButton(text="❌ Нет", callback_data="main_menu"),
    )
    await target.answer("Очистить историю диалога? Это нельзя отменить.", reply_markup=b.as_markup())


@router.message(F.text == "🗑 Очистить контекст")
async def btn_clear(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _reply_clear_confirm(message, message.from_user.id)


@router.callback_query(F.data == "clear_confirm")
async def cb_clear_confirm(cb: types.CallbackQuery):
    await cb.answer()
    await _reply_clear_confirm(cb.message, cb.from_user.id)

async def _reply_screen_profile(target, user_id: int):
    from shared.db.database import get_pool
    from shared.domain.credits import get_balance, get_user_model
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT credits_total_spent, referral_count, total_payments_rub, created_at, username, first_name FROM users WHERE id = $1", user_id)
        # Статистика по типам
        by_type = await conn.fetch(
            "SELECT task_type, COUNT(*) AS cnt FROM ai_requests WHERE user_id = $1 GROUP BY task_type", user_id)
    if not user:
        await target.answer("👤 Профиль пока недоступен.", reply_markup=back_to_main_kb())
        return
    bal = await get_balance(user_id)
    model = await get_user_model(user_id, "text")
    created = user["created_at"].strftime("%d.%m.%Y") if hasattr(user["created_at"], "strftime") else str(user["created_at"])
    name = user["first_name"] or user["username"] or str(user_id)
    stats_map = {r["task_type"]: r["cnt"] for r in by_type}
    text = (
        f"👤 <b>Твой профиль</b>\n\n"
        f"📛 Имя: {name}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"📅 С нами с: {created}\n\n"
        f"💰 Баланс: <b>{bal['total']} CR</b>\n"
        f"🤖 Модель: <b>{model}</b>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"├ 💬 Текст: {stats_map.get('text', 0)}\n"
        f"├ 🎨 Картинки: {stats_map.get('image', 0)}\n"
        f"├ 🎬 Видео: {stats_map.get('video', 0)}\n"
        f"└ 🎤 Голос: {stats_map.get('voice', 0) + stats_map.get('tts', 0)}\n\n"
        f"🤝 Рефералов: {user['referral_count']}\n"
        f"💳 Оплат: {float(user['total_payments_rub'] or 0):,.0f} ₽"
    )
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="💳 Пополнить", callback_data="buy_credits"),
        types.InlineKeyboardButton(text="🎭 Режим чата", callback_data="mode_open"),
    )
    b.row(
        types.InlineKeyboardButton(text="🤝 Реф. ссылка", callback_data="screen_ref"),
        types.InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu"),
    )
    legal_url = getattr(settings, "legal_base_url", "").rstrip("/")
    if legal_url:
        b.row(
            types.InlineKeyboardButton(text="📜 Политика конфиденциальности", url=f"{legal_url}/privacy"),
            types.InlineKeyboardButton(text="📋 Оферта", url=f"{legal_url}/terms"),
        )
    b.row(
        types.InlineKeyboardButton(text="📥 Экспорт моих данных", callback_data="export_my_data"),
        types.InlineKeyboardButton(text="🗑 Удалить аккаунт", callback_data="delete_account"),
    )
    await target.answer(text, reply_markup=b.as_markup())


@router.message(F.text == "👤 Профиль")
async def btn_profile(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _reply_screen_profile(message, message.from_user.id)


@router.callback_query(F.data == "screen_profile")
async def cb_screen_profile(cb: types.CallbackQuery):
    await cb.answer()
    await _reply_screen_profile(cb.message, cb.from_user.id)

async def _reply_screen_tools(target):
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu"))
    await target.answer(
        "🛠 <b>Инструменты</b>\n\n"
        "Веб-поиск, резюме по ссылке, выполнение кода — открой раздел в меню.\n"
        "Фото: подпись «убери фон», «стилизуй …», «текст с фото».",
        reply_markup=b.as_markup())


@router.callback_query(F.data == "screen_tools")
async def cb_screen_tools(cb: types.CallbackQuery):
    await cb.answer()
    await _reply_screen_tools(cb.message)


@router.callback_query(F.data == "screen_ref")
async def cb_screen_ref(cb: types.CallbackQuery):
    await cb.answer()
    from shared.db.database import get_pool
    from shared.domain.credits import (
        REFEREE_CR,
        REFERRAL_LEVELS,
        REFERRER_CR,
        get_referral_code,
        get_referral_level,
    )
    user_id = cb.from_user.id
    code = await get_referral_code(user_id)
    bot_name = (settings.bot_username or "").strip().lstrip("@") or "neurobox_bot"
    link = f"https://t.me/{bot_name}?start=ref_{code}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        ref_count = await conn.fetchval("SELECT referral_count FROM users WHERE id = $1", user_id) or 0
    level_name, mult = get_referral_level(ref_count)
    bonus_cr = int(REFERRER_CR * mult)
    next_line = ""
    for min_ref, _, name in REFERRAL_LEVELS:
        if ref_count < min_ref:
            next_line = f"\n🎯 До уровня «{name}»: ещё {min_ref - ref_count} друг(ей)"
            break
    else:
        next_line = "\n🏆 Максимальный уровень!"
    share_text = "Попробуй НейроБокс — AI-бот для текста, картинок, документов и транскрибации. Бесплатные кредиты каждый день."
    import urllib.parse
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(link)}&text={urllib.parse.quote(share_text)}"
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share_url))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu"))
    await cb.message.answer(
        f"🤝 <b>Реферальная программа</b>\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"📤 Нажми кнопку ниже — ссылка отправится другу.\n\n"
        f"• Уровень: <b>{level_name}</b> (×{mult})\n"
        f"• За друга: <b>+{bonus_cr} CR</b> тебе, <b>+{REFEREE_CR} CR</b> другу\n"
        f"• Приведено: <b>{ref_count}</b>{next_line}",
        reply_markup=b.as_markup())


@router.callback_query(F.data == "screen_settings")
async def cb_screen_settings(cb: types.CallbackQuery):
    await cb.answer()
    from services.bot.i18n import get_user_lang
    lang = await get_user_lang(cb.from_user.id)
    lang_label = "🇷🇺 Русский" if lang == "ru" else "🇬🇧 English"
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="⚙️ Модель", callback_data="select_model"))
    b.row(types.InlineKeyboardButton(text=f"🌍 Язык: {lang_label}", callback_data="choose_lang"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu"))
    await cb.message.answer("⚙️ <b>Настройки</b>", reply_markup=b.as_markup())


@router.callback_query(F.data == "choose_lang")
async def cb_choose_lang(cb: types.CallbackQuery):
    await cb.answer()
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"),
        types.InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en"),
    )
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="screen_settings"))
    await cb.message.answer("🌍 Выбери язык / Choose language:", reply_markup=b.as_markup())


@router.callback_query(F.data.in_({"set_lang_ru", "set_lang_en"}))
async def cb_set_lang(cb: types.CallbackQuery):
    lang = "ru" if cb.data == "set_lang_ru" else "en"
    from services.bot.i18n import set_user_lang, t
    await set_user_lang(cb.from_user.id, lang)
    await cb.answer(t("lang_set", lang), show_alert=True)
    text, kb = await _main_menu_text_and_kb(cb.from_user.id)
    await cb.message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "noop")
async def cb_noop(cb: types.CallbackQuery):
    await cb.answer()


# Кросс-промо: боты сети AIXUP
OUR_BOTS = [
    ("🧠 НейроБокс", "https://t.me/ai_b0x_bot"),
    ("🔮 Знак Вселенной", "https://t.me/znakvse_bot"),
    ("🍽 Ням AI", "https://t.me/vkuysniy_bot"),
    ("🐾 Zoo Бот", "https://t.me/zoo_helping_bot"),
    ("⚖️ НейроЮрист", "https://t.me/yuirist_bot"),
    ("🔧 Гараж AI", "https://t.me/garazhe_ai_bot"),
]

OUR_BOTS_TEXT = (
    "🤖 <b>Наши боты</b>\n\n"
    "🧠 <b>НейроБокс</b> (@ai_b0x_bot) — AI-бот для текста, картинок, документов и транскрибации.\n\n"
    "🔮 <b>Знак Вселенной</b> (@znakvse_bot) — AI-таролог: Таро, матрица судьбы, нумерология, гороскопы.\n\n"
    "🍽 <b>Ням AI</b> (@vkuysniy_bot) — AI-нутрициолог: калории по фото, рецепты, дневник питания, тренировки.\n\n"
    "🐾 <b>Zoo Бот</b> (@zoo_helping_bot) — AI-ветеринар: симптомы, питание, прививки, уход за питомцами.\n\n"
    "⚖️ <b>НейроЮрист</b> (@yuirist_bot) — AI-юрист: консультации, договоры, шаблоны документов, калькуляторы.\n\n"
    "🔧 <b>Гараж AI</b> (@garazhe_ai_bot) — AI-механик: диагностика, OBD-II, запчасти, напоминания ТО."
)


@router.callback_query(F.data == "our_bots")
async def cb_our_bots(cb: types.CallbackQuery):
    await cb.answer()
    b = InlineKeyboardBuilder()
    for label, url in OUR_BOTS:
        b.row(types.InlineKeyboardButton(text=label, url=url))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu"))
    await cb.message.answer(OUR_BOTS_TEXT, reply_markup=b.as_markup())


@router.message(Command("privacy"))
async def cmd_privacy(message: types.Message):
    """Ссылка на политику конфиденциальности."""
    legal_url = getattr(settings, "legal_base_url", "").rstrip("/")
    if legal_url:
        await message.answer(f"📜 Политика конфиденциальности:\n{legal_url}/privacy")
    else:
        await message.answer("Ссылка на политику конфиденциальности не настроена.")


@router.message(Command("terms"))
async def cmd_terms(message: types.Message):
    """Ссылка на оферту."""
    legal_url = getattr(settings, "legal_base_url", "").rstrip("/")
    if legal_url:
        await message.answer(f"📋 Оферта (условия использования):\n{legal_url}/terms")
    else:
        await message.answer("Ссылка на оферту не настроена.")


@router.callback_query(F.data == "export_my_data")
async def cb_export_my_data(cb: types.CallbackQuery):
    """Экспорт данных пользователя: профиль, платежи, операции с кредитами, заметки админа."""
    await cb.answer()
    user_id = cb.from_user.id
    import json
    from datetime import datetime, timezone

    from shared.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id, username, first_name, language_code, credits_bought, credits_free_today, credits_total_spent, "
            "referral_count, total_payments_rub, created_at, updated_at FROM users WHERE id = $1", user_id)
        payments = await conn.fetch(
            "SELECT id, payment_id, amount_rub, credits_amount, pack_name, status, created_at, confirmed_at FROM payments WHERE user_id = $1 ORDER BY created_at DESC", user_id)
        transactions = await conn.fetch(
            "SELECT id, amount, type, description, model, created_at FROM credit_transactions WHERE user_id = $1 ORDER BY created_at DESC LIMIT 500", user_id)
        notes = await conn.fetch(
            "SELECT id, note, created_at FROM user_notes WHERE user_id = $1 ORDER BY created_at DESC", user_id)
    if not user:
        await cb.message.answer("Данные не найдены.")
        return
    def _serialize(obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if hasattr(obj, "__float__") and not isinstance(obj, (int, bool)):
            return float(obj)
        return obj
    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {k: _serialize(v) for k, v in dict(user).items()},
        "payments": [{k: _serialize(v) for k, v in dict(r).items()} for r in payments],
        "credit_transactions": [{k: _serialize(v) for k, v in dict(r).items()} for r in transactions],
        "admin_notes": [{k: _serialize(v) for k, v in dict(r).items()} for r in notes],
    }
    text = json.dumps(data, ensure_ascii=False, indent=2)
    from aiogram.types import BufferedInputFile
    file = BufferedInputFile(text.encode("utf-8"), filename=f"neurobox_export_{user_id}.json")
    await cb.message.answer_document(document=file, caption="📥 Экспорт твоих данных (профиль, платежи, операции, заметки).")


@router.callback_query(F.data == "delete_account")
async def cb_delete_account(cb: types.CallbackQuery):
    """Запрос подтверждения удаления аккаунта."""
    await cb.answer()
    b = InlineKeyboardBuilder()
    b.row(
        types.InlineKeyboardButton(text="✅ Да, удалить аккаунт", callback_data="delete_account_confirm"),
        types.InlineKeyboardButton(text="❌ Отмена", callback_data="screen_profile"),
    )
    await cb.message.answer(
        "🗑 <b>Удаление аккаунта</b>\n\n"
        "Будет заблокирован доступ к боту, персональные данные (имя, username) обнулены. "
        "Данные об оплатах сохраняются для бухгалтерии. Действие необратимо.",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data == "delete_account_confirm")
async def cb_delete_account_confirm(cb: types.CallbackQuery):
    """Блокировка и анонимизация пользователя."""
    await cb.answer()
    user_id = cb.from_user.id
    from shared.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_blocked = TRUE, username = NULL, first_name = 'Deleted', updated_at = NOW() WHERE id = $1",
            user_id,
        )
    await cb.message.answer("Аккаунт удалён. Доступ к боту заблокирован. Персональные данные обнулены.")
    # Бан-чек в middleware не даст пользователю больше писать


# /admin и /админ обрабатываются в bot.handlers.admin (статистика + клавиатура дашборда)





# ── Кнопки новых модулей (Reply keyboard) ──

@router.message(F.text == "🎵 Аудио")
async def btn_audio_menu(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    b = InlineKeyboardBuilder()
    if not settings.enable_tts and not settings.enable_music:
        b.row(types.InlineKeyboardButton(text="💬 Поддержка", callback_data="screen_support"))
        b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="more_menu"))
        await message.answer(
            '🎵 <b>Аудио-модуль</b> временно недоступен.\n\nСейчас можно отправлять голосовые и кружки на транскрибацию.',
            reply_markup=b.as_markup(),
        )
        return

    lines = ["🎵 <b>Аудио</b>"]
    if settings.enable_tts:
        b.row(types.InlineKeyboardButton(text="🗣 Озвучить текст", callback_data="audio_tts"))
        lines.append("🗣 Озвучить текст — AI-голоса")
    if settings.enable_music:
        b.row(types.InlineKeyboardButton(text="🎶 Создать музыку", callback_data="audio_music"))
        lines.append("🎶 Создать музыку — описание → трек")
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="more_menu"))
    await message.answer('\n\n'.join([lines[0], '\n'.join(lines[1:])]), reply_markup=b.as_markup())

@router.message(F.text.in_({"🎤 Транскриб.", "🎤 Транскрибация"}))
async def btn_transcribe_menu(message: types.Message):
    await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    b = InlineKeyboardBuilder()
    b.row(types.InlineKeyboardButton(text="📝 Расшифровать", callback_data="tr_mode:plain"))
    b.row(types.InlineKeyboardButton(text="📋 + Саммари", callback_data="tr_mode:summary"))
    b.row(types.InlineKeyboardButton(text="✅ + Протокол встречи", callback_data="tr_mode:protocol"))
    b.row(types.InlineKeyboardButton(text="◀️ Назад", callback_data="more_menu"))
    await message.answer(
        "🎤 <b>Транскрибация</b>\n\n"
        "Отправь голосовое, аудиофайл или видео-кружок.",
        reply_markup=b.as_markup())


# ── Обработка неподдерживаемых типов контента ──

@router.message(F.sticker)
async def handle_sticker(message: types.Message):
    await message.answer("😊 Классный стикер! Но я понимаю только текст, фото, голосовые и документы.\n\nНапиши вопрос или нажми /start")


@router.message(F.contact)
async def handle_contact(message: types.Message):
    await message.answer("📇 Спасибо, но я не работаю с контактами.\n\nНапиши текстовый вопрос или нажми /start")


@router.message(F.location)
async def handle_location(message: types.Message):
    await message.answer("📍 Спасибо, но я не работаю с геолокацией.\n\nНапиши текстовый вопрос или нажми /start")


@router.message(F.animation)
async def handle_animation(message: types.Message):
    await message.answer("🎞 Красивая гифка! Отправь как фото с подписью — и я проанализирую.\n\nНапиши вопрос или нажми /start")
