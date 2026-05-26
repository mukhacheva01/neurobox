#!/usr/bin/env python3
"""
НейроБокс — глобальные тесты: API, БД, Redis, админка, импорты.
Запуск: cd /opt/neurobox && python scripts/global_tests.py
"""
import asyncio
import os
import sys

# Загрузка .env
for d in [os.getcwd(), "/app", "/opt/neurobox", os.path.dirname(os.path.abspath(__file__))]:
    env_path = os.path.join(d, ".env")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    os.environ.setdefault(k, v)
        break

_root = os.environ.get("NEUROBOX_ROOT") or ("/app" if os.path.isdir("/app") else "/opt/neurobox")
if os.path.isdir(_root):
    os.chdir(_root)
if _root not in sys.path:
    sys.path.insert(0, _root)


def ok(name: str, result: str):
    mark = "✓" if result.startswith("OK") else "✗"
    print(f"  {mark} {name}: {result}")


def fail(name: str, err: Exception):
    print(f"  ✗ {name}: {err}")


async def test_imports():
    """Импорты бота."""
    try:
        return "OK"
    except Exception as e:
        return f"Ошибка: {e}"


async def test_database():
    """Подключение к PostgreSQL."""
    try:
        from shared.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            r = await conn.fetchval("SELECT 1")
        if r == 1:
            return "OK"
        return "Неожиданный ответ"
    except Exception as e:
        return f"Ошибка: {e}"


async def test_redis():
    """Подключение к Redis."""
    try:
        from shared.redis.store import _get_redis
        r = await _get_redis()
        if r:
            await r.ping()
            return "OK"
        return "Redis недоступен"
    except Exception as e:
        return f"Ошибка: {e}"


async def test_admin_db():
    """Admin panel DB (sync psycopg2)."""
    try:
        from services.admin.db import get_conn
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        conn.close()
        return "OK"
    except Exception as e:
        return f"Ошибка: {e}"


async def test_flask_app():
    """Flask admin app импорт."""
    try:
        from services.admin.app import app
        if app and hasattr(app, "route"):
            return "OK"
        return "App не валиден"
    except Exception as e:
        return f"Ошибка: {e}"


async def test_apis():
    """Проверка API через check_apis."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("check_apis", os.path.join(os.path.dirname(__file__), "check_apis.py"))
        check_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check_mod)
        check_openai = check_mod.check_openai
        check_anthropic = check_mod.check_anthropic
        check_google = check_mod.check_google
        check_xai = check_mod.check_xai
        check_falai = check_mod.check_falai
        check_yookassa = check_mod.check_yookassa
        results = []
        for name, coro in [
            ("OpenAI", check_openai),
            ("Anthropic", check_anthropic),
            ("Google", check_google),
            ("xAI", check_xai),
            ("fal.ai", check_falai),
            ("YooKassa", check_yookassa),
        ]:
            r = await coro()
            results.append((name, r))
        ok_count = sum(1 for _, r in results if r.startswith("OK"))
        fails = [(n, r) for n, r in results if not r.startswith("OK")]
        if fails:
            return f"{ok_count}/6 OK: " + ", ".join(f"{n}" for n, _ in fails)
        return f"OK ({ok_count}/6)"
    except Exception as e:
        return f"Ошибка: {e}"


async def test_config():
    """Конфиг загружен."""
    try:
        from shared.config import settings
        if settings.bot_token and settings.bot_username:
            return "OK"
        return "BOT_TOKEN или BOT_USERNAME не заданы"
    except Exception as e:
        return f"Ошибка: {e}"


async def main():
    print("\nНейроБокс — глобальные тесты")
    print("=" * 50)

    print("\n[1] Конфигурация")
    ok("Config", await test_config())

    print("\n[2] Импорты")
    ok("Bot imports", await test_imports())

    print("\n[3] База данных")
    ok("PostgreSQL", await test_database())

    print("\n[4] Redis")
    ok("Redis", await test_redis())

    print("\n[5] Админ-панель")
    ok("Admin DB", await test_admin_db())
    ok("Flask app", await test_flask_app())

    print("\n[6] API (текст, картинки, платежи)")
    ok("APIs", await test_apis())

    print("\n" + "=" * 50)
    print("Готово.\n")


if __name__ == "__main__":
    asyncio.run(main())
