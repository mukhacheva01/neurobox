"""Универсальная админка: конфиг из env для любого бота сети."""
import os

# BOT_TYPE: neurobox | tarot | food | zoo | lawyer | garage
BOT_TYPE = (os.environ.get("BOT_TYPE", "neurobox") or "neurobox").strip().lower()

# Человекочитаемое название для заголовков (можно задать явно через BOT_DISPLAY_NAME)
_DISPLAY_NAMES = {
    "neurobox": "НейроБокс",
    "tarot": "Знак Вселенной",
    "food": "Ням AI",
    "zoo": "Zoo Бот",
    "lawyer": "НейроЮрист",
    "garage": "Гараж AI",
}
BOT_DISPLAY_NAME = (os.environ.get("BOT_DISPLAY_NAME", "").strip() or _DISPLAY_NAMES.get(BOT_TYPE, "Админка"))

# Порт внутри контейнера (внешний маппится в docker-compose)
ADMIN_PANEL_PORT = int(os.environ.get("ADMIN_PANEL_PORT", "8091"))
ADMIN_API_PORT = int(os.environ.get("ADMIN_API_PORT", "8092"))
