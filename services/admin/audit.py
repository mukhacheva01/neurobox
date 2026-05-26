"""Логирование действий админа в admin_audit_log."""
import json
import os

from services.admin.access import current_admin
from services.admin.db import get_conn

BOT_IDENTIFIER = os.environ.get("BOT_IDENTIFIER", "neurobox")


def log_action(action: str, entity_type: str = "user", entity_id=None, details: dict = None, ip: str = None):
    """Записать действие в admin_audit_log. При ошибке (таблица не создана) — молча игнорировать."""
    try:
        admin = current_admin()
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO admin_audit_log (
                bot_identifier, action, entity_type, entity_id, details, ip,
                admin_user_id, admin_login, admin_role
            )
            VALUES (%s, %s, %s, %s, %s, %s::inet, %s, %s, %s)
            """,
            (
                BOT_IDENTIFIER,
                action[:80],
                entity_type[:50] if entity_type else None,
                str(entity_id)[:500] if entity_id is not None else None,
                json.dumps(details, ensure_ascii=False)[:5000] if details else None,
                ip if ip else None,
                admin.get("id"),
                admin.get("login"),
                admin.get("role"),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
