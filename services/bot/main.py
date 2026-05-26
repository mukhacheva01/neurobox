"""НейроБокс — Main. v4.2: +Sentry, +signal handlers."""
import asyncio
import logging
import signal

import structlog
from aiogram import Bot, Dispatcher, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

from shared.config import settings
from shared.config.settings import BOT_VERSION

if settings.sentry_dsn:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.1,
            environment="production",
            release=f"neurobox@{BOT_VERSION}",
        )
    except Exception:
        pass


def _redact_sensitive(logger, method_name, event_dict):
    """Скрыть в логах значения ключей с токенами/паролями."""
    del logger, method_name
    sensitive_keys = ("token", "password", "secret", "api_key", "key")
    for k, v in list(event_dict.items()):
        if any(s in (k or "").lower() for s in sensitive_keys) and v:
            event_dict[k] = "***REDACTED***"
    return event_dict


structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        _redact_sensitive,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer() if settings.log_level == "DEBUG" else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(settings.log_level)),
)
log = structlog.get_logger()


def _get_fsm_storage():
    """RedisStorage если доступен, иначе MemoryStorage."""
    try:
        from aiogram.fsm.storage.redis import RedisStorage
        from redis.asyncio import Redis

        redis = Redis.from_url(settings.redis_url)
        return RedisStorage(redis=redis)
    except Exception as e:
        log.warning("Redis FSM unavailable, using MemoryStorage", error=str(e))
        return MemoryStorage()


async def main():
    log.info("Starting НейроБокс", version=BOT_VERSION, log_level=settings.log_level)
    from services.bot.config.model_registry_guard import (
        assert_model_registry_consistency,
    )

    assert_model_registry_consistency()
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = _get_fsm_storage()
    dp = Dispatcher(storage=storage)

    from services.bot.middlewares.ban_check import BanCheckMiddleware
    from services.bot.middlewares.log_context import LogContextMiddleware
    from services.bot.middlewares.rate_limit import RateLimitMiddleware

    dp.message.middleware(LogContextMiddleware())
    dp.callback_query.middleware(LogContextMiddleware())
    dp.message.middleware(BanCheckMiddleware())
    dp.callback_query.middleware(BanCheckMiddleware())
    dp.message.middleware(RateLimitMiddleware())
    dp.callback_query.middleware(RateLimitMiddleware())

    from services.bot.handlers import (
        audiogen,
        balance,
        coming_soon,
        doc_handler,
        docgen,
        feedback,
        guide,
        image,
        model_select,
        modes,
        music,
        photo_tools,
        ref_promo_stats,
        saved_export,
        start,
        subscribe_remind,
        text,
        tools,
        transcribe,
        video,
        voice,
    )
    from services.bot.handlers.admin import router as admin_router

    @dp.errors()
    async def on_error(event: ErrorEvent):
        log.error(
            "Unhandled error",
            error=str(event.exception),
            update_type=type(event.update).__name__ if event.update else "?",
            exc_info=event.exception,
        )
        try:
            upd = event.update
            if upd and upd.message:
                await upd.message.answer("Произошла ошибка. Попробуйте ещё раз или напишите /start.")
            elif upd and upd.callback_query:
                await upd.callback_query.answer("Произошла ошибка. Попробуйте ещё раз.", show_alert=True)
        except Exception:
            pass

    dp.include_router(admin_router)
    dp.include_router(start.router)
    dp.include_router(guide.router)
    dp.include_router(image.router)
    dp.include_router(video.router)
    dp.include_router(voice.router)
    dp.include_router(music.router)
    dp.include_router(model_select.router)
    dp.include_router(balance.router)
    dp.include_router(modes.router)
    dp.include_router(saved_export.router)
    dp.include_router(ref_promo_stats.router)
    dp.include_router(photo_tools.router)
    dp.include_router(tools.router)
    dp.include_router(doc_handler.router)
    dp.include_router(coming_soon.router)
    dp.include_router(subscribe_remind.router)
    dp.include_router(feedback.router)
    dp.include_router(docgen.router)
    dp.include_router(audiogen.router)
    dp.include_router(transcribe.router)
    dp.include_router(text.router)

    stale_router = Router()

    @stale_router.callback_query()
    async def stale_callback(cb: types.CallbackQuery):
        await cb.answer()
        from services.bot.keyboards.main import persistent_menu_kb

        await cb.message.answer(
            "Кнопка устарела. Нажмите /start для обновления меню.",
            reply_markup=persistent_menu_kb(),
        )

    dp.include_router(stale_router)

    from shared.db.database import close_pool, get_pool
    from services.bot.services.chat_service import (
        get_due_reminders,
        get_users_for_balance_reminder,
    )
    from shared.domain.admin_runtime import sync_admin_text_defaults
    from shared.domain.credits import sync_billing_plans_defaults

    await get_pool()
    await sync_admin_text_defaults()
    await sync_billing_plans_defaults()
    log.info("Bot ready")

    has_search = bool((settings.serper_api_key or "").strip())
    commands = [
        BotCommand(command="start", description="▶️ Главное меню"),
        BotCommand(command="help", description="📖 Быстрый гайд"),
        BotCommand(command="guide", description="📚 Полный гайд"),
        BotCommand(command="balance", description="💰 Текущий баланс"),
        BotCommand(command="model", description="⚙️ Выбор моделей"),
        BotCommand(command="img", description="🎨 Картинка по описанию"),
        BotCommand(command="img4", description="🎨 4 варианта картинки"),
    ]
    if settings.enable_video:
        commands.extend(
            [
                BotCommand(command="video", description="🎬 Видео по описанию"),
                BotCommand(command="setvideo", description="🎬 Выбрать видео-модель"),
            ]
        )
    if settings.enable_music:
        commands.append(BotCommand(command="music", description="🎵 Музыка по описанию"))
    if settings.enable_tts:
        commands.extend(
            [
                BotCommand(command="voice", description="🔊 Озвучить текст"),
                BotCommand(command="settts", description="🎤 Выбрать TTS-модель"),
                BotCommand(command="setvoice", description="🎙 Выбрать голос"),
                BotCommand(command="tts", description="🗣 Озвучить текст"),
            ]
        )
    commands.extend(
        [
            BotCommand(command="doc", description="📄 Документ по описанию"),
            BotCommand(command="gendoc", description="📄 Генерация документа (формат)"),
            BotCommand(command="transcribe", description="🎤 Транскрибация аудио"),
            BotCommand(command="summary", description="📰 Резюме страницы по URL"),
            BotCommand(command="code", description="💻 Разбор кода"),
            BotCommand(command="save", description="⭐ Сохранить промпт"),
            BotCommand(command="favorites", description="📚 Избранные промпты"),
            BotCommand(command="export", description="📤 Экспорт чата"),
            BotCommand(command="clear", description="🗑 Очистить контекст"),
            BotCommand(command="privacy", description="📜 Политика конфиденциальности"),
            BotCommand(command="terms", description="📋 Оферта"),
            BotCommand(command="paysupport", description="💬 Поддержка по оплате"),
        ]
    )
    if has_search:
        commands.insert(7, BotCommand(command="search", description="🔎 AI + веб-поиск"))

    await bot.set_my_commands(commands)

    async def reminder_loop():
        while True:
            try:
                await asyncio.sleep(30)
                for r in await get_due_reminders():
                    try:
                        await bot.send_message(r["user_id"], f"⏰ <b>Напоминание</b>\n\n{r['text']}")
                    except Exception as e:
                        error_str = str(e).lower()
                        if "bot was blocked" in error_str or "user is deactivated" in error_str or "chat not found" in error_str:
                            log.info("reminder: user unavailable, marking blocked", user_id=r["user_id"])
                            from services.bot.services.chat_service import (
                                mark_user_blocked,
                            )
                            await mark_user_blocked(r["user_id"])
                        else:
                            log.warning("reminder send failed", user_id=r["user_id"], error=str(e))
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("reminder_loop", error=str(e))

    bg_tasks = []
    bg_tasks.append(asyncio.create_task(reminder_loop()))

    async def balance_reminder_loop():
        """Ежедневное напоминание о пополнении для пользователей с низким балансом."""
        from services.bot.services.chat_service import (
            mark_user_blocked,
            set_balance_reminder_sent,
        )

        throttle_sec = max(0.0, float(getattr(settings, "balance_reminder_throttle_sec", 1)))
        max_batch = max(1, int(getattr(settings, "balance_reminder_max_batch", 200)))
        while True:
            try:
                await asyncio.sleep(24 * 3600)
                for r in await get_users_for_balance_reminder(limit=max_batch):
                    try:
                        await bot.send_message(
                            r["user_id"],
                            "💡 Привет! Напомню, что у тебя мало кредитов. Пополни баланс — пакеты от 29 ₽. Напиши /balance",
                        )
                        await set_balance_reminder_sent(r["user_id"])
                        if throttle_sec:
                            await asyncio.sleep(throttle_sec)
                    except Exception as e:
                        error_str = str(e).lower()
                        if "bot was blocked" in error_str or "user is deactivated" in error_str or "chat not found" in error_str:
                            log.info("balance_reminder: user unavailable, marking blocked", user_id=r["user_id"])
                            await mark_user_blocked(r["user_id"])
                        else:
                            log.warning("balance_reminder send failed", user_id=r["user_id"], error=str(e))
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("balance_reminder_loop", error=str(e))

    bg_tasks.append(asyncio.create_task(balance_reminder_loop()))

    async def payment_reconcile_loop():
        interval = max(60, int(getattr(settings, "payment_reconcile_interval_sec", 600)))
        batch_size = max(1, int(getattr(settings, "payment_reconcile_batch_size", 25)))
        while True:
            try:
                await asyncio.sleep(interval)
                from shared.domain.yookassa import reconcile_pending_payments

                await reconcile_pending_payments(limit=batch_size)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("payment_reconcile_loop", error=str(e))

    bg_tasks.append(asyncio.create_task(payment_reconcile_loop()))

    _shutdown = asyncio.Event()

    def _signal_handler(sig):
        log.info("shutdown_signal", signal=sig)
        _shutdown.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler, sig)
        except NotImplementedError:
            pass

    try:
        await dp.start_polling(bot, polling_timeout=30, allowed_updates=['message', 'callback_query', 'pre_checkout_query'])
    finally:
        log.info("shutdown_starting")
        for task in bg_tasks:
            task.cancel()
        for task in bg_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        if pending:
            log.info("waiting_pending_tasks", count=len(pending))
            await asyncio.wait(pending, timeout=10)
        try:
            if hasattr(storage, "close"):
                await storage.close()
            elif hasattr(storage, "redis"):
                await storage.redis.close()
        except Exception:
            pass
        try:
            from shared.redis.store import close_redis

            await close_redis()
        except Exception:
            pass
        await close_pool()
        await bot.session.close()
        log.info("shutdown_complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
