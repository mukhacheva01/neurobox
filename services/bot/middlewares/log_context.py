"""Middleware: привязка request_id и user_id к логам (без PII)."""
import uuid

import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


def _user_id_from_event(event: TelegramObject) -> int | None:
    if isinstance(event, Message) and event.from_user:
        return event.from_user.id
    if isinstance(event, CallbackQuery) and event.from_user:
        return event.from_user.id
    return None


class LogContextMiddleware(BaseMiddleware):
    """Устанавливает request_id и user_id в contextvars для structlog (без PII)."""

    async def __call__(self, handler, event: TelegramObject, data: dict):
        request_id = str(uuid.uuid4())[:8]
        user_id = _user_id_from_event(event)
        update = getattr(event, "update", None)
        update_id = getattr(update, "update_id", None) or request_id
        with structlog.contextvars.bound_contextvars(
            request_id=request_id,
            update_id=update_id,
            user_id=user_id,
        ):
            return await handler(event, data)
