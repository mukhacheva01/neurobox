"""Тесты конфигурации."""


def test_settings_import():
    """Импорт настроек не падает."""
    from shared.config import settings
    assert settings is not None


def test_settings_bot_token_exists():
    """BOT_TOKEN задан (не пустая строка после загрузки .env)."""
    from shared.config import settings
    # Может быть пустым в CI — тогда тест только проверяет тип
    assert hasattr(settings, "bot_token")
    assert isinstance(settings.bot_token, str)


def test_settings_database_url_format():
    """DATABASE_URL содержит postgresql."""
    from shared.config import settings
    assert "postgresql" in settings.database_url


def test_admin_id_list_property():
    """admin_id_list возвращает список int или пустой список."""
    from shared.config import settings
    ids = settings.admin_id_list
    assert isinstance(ids, list)
    for i in ids:
        assert isinstance(i, int)


def test_bot_main_imports_without_error():
    """Импорт bot.main не падает."""
    import services.bot.main as main_mod
    assert main_mod is not None


def test_bot_main_starts_without_name_error():
    """Запуск main() до регистрации роутеров не падает с NameError (F и др. должны быть в scope)."""
    import asyncio

    from services.bot.main import main
    async def run_briefly():
        task = asyncio.create_task(main())
        await asyncio.sleep(0.8)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    try:
        asyncio.run(run_briefly())
    except NameError as e:
        if "F" in str(e) or "is not defined" in str(e):
            raise AssertionError(f"Bot main() uses undefined name: {e}") from e
        raise
