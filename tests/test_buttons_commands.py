"""Контракт меню: кнопки и команды должны иметь обработчики."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _expected_menu_commands() -> list[str]:
    from shared.config import settings

    main_src = _read("services/bot/main.py")
    commands = re.findall(r'BotCommand\(command="([a-z0-9_]+)"', main_src)
    if not getattr(settings, "enable_video", False):
        commands = [cmd for cmd in commands if cmd not in {"video", "setvideo"}]
    if not getattr(settings, "enable_music", False):
        commands = [cmd for cmd in commands if cmd not in {"music"}]
    if not getattr(settings, "enable_tts", False):
        commands = [cmd for cmd in commands if cmd not in {"voice", "settts", "setvoice", "tts"}]
    if not (getattr(settings, "serper_api_key", "") or "").strip():
        commands = [cmd for cmd in commands if cmd != "search"]
    return commands


def test_persistent_reply_buttons_have_message_handlers():
    kb_src = _read("services/bot/keyboards/main.py")
    handlers_src = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "services/bot/handlers").rglob("*.py"))

    labels = re.findall(r'KeyboardButton\(text="([^"]+)"\)', kb_src)
    labels = list(dict.fromkeys(labels))

    missing = []
    for label in labels:
        if f'F.text == "{label}"' in handlers_src:
            continue
        if re.search(r'F\.text\.in_\([^\)]*"' + re.escape(label) + r'"', handlers_src):
            continue
        missing.append(label)

    assert not missing, f"Нет message-handler для кнопок: {missing}"


def test_bot_menu_commands_have_handlers():
    handlers_src = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "services/bot/handlers").rglob("*.py"))

    commands = _expected_menu_commands()
    assert commands, "В bot.set_my_commands нет команд"

    missing = []
    for cmd in commands:
        if cmd == "start":
            if "CommandStart()" not in handlers_src:
                missing.append(cmd)
            continue
        if f'Command("{cmd}")' in handlers_src or f"Command('{cmd}')" in handlers_src:
            continue
        missing.append(cmd)

    assert not missing, f"Команды в меню без handler: {missing}"
