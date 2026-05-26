"""Админ-панель: объединение роутеров."""
from aiogram import Router

# Импорт команд /admin и /админ из admin.py (рядом с пакетом admin/)
from services.bot.handlers.admin_cmd import router as admin_cmd_router

from . import (
    broadcast,
    dashboard,
    finance,
    moderation,
    promo,
    stats,
    subscriptions,
    system,
    users,
)

router = Router()
router.include_router(admin_cmd_router)  # /admin, /админ — первым
router.include_router(dashboard.router)
router.include_router(stats.router)
router.include_router(users.router)
router.include_router(finance.router)
router.include_router(promo.router)
router.include_router(broadcast.router)
router.include_router(moderation.router)
router.include_router(system.router)
router.include_router(subscriptions.router)
