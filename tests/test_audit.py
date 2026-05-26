"""Тесты модуля аудита админки."""


def test_audit_log_action_import():
    """Импорт log_action не падает."""
    from services.admin.audit import log_action
    assert callable(log_action)


def test_audit_log_action_call_no_db():
    """log_action при отсутствии таблицы не роняет процесс."""
    from services.admin.audit import log_action
    # Таблица может не существовать — функция ловит Exception
    log_action("test_action", entity_id=123, details={"a": 1})
