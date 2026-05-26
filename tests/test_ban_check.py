"""Тесты проверки бана (логика без БД)."""


def test_is_admin_user_logic():
    """Проверка: при пустом admin_ids только явный админ в списке."""
    from shared.config import settings
    from shared.domain.credits import _is_admin_user
    # Если в .env задан ADMIN_IDS, то эти id должны быть админами
    admin_list = settings.admin_id_list
    if admin_list:
        assert _is_admin_user(admin_list[0]) is True
    # Случайный id не в списке — не админ (при непустом admin_ids)
    if admin_list:
        fake_id = max(admin_list) + 99999
        assert _is_admin_user(fake_id) is False
