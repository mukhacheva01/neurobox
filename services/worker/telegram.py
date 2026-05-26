"""Singleton Bot instance for worker — output-only, no polling/webhook."""
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

_bot: Bot | None = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        from shared.config import settings
        _bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return _bot


async def close_bot() -> None:
    global _bot
    if _bot is not None:
        await _bot.session.close()
        _bot = None
