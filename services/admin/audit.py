"""Audit logging via backend admin API."""
import os

from services.admin.access import current_admin
from services.admin.backend_client import post_json

BOT_IDENTIFIER = os.environ.get("BOT_IDENTIFIER", "neurobox")


def log_action(action: str, entity_type: str = "user", entity_id=None, details: dict = None, ip: str = None):
    """Write audit events through backend and ignore failures for admin UX."""
    try:
        admin = current_admin()
        token = admin.get("token")
        if not token:
            return
        response = post_json(
            "/api/v1/admin/audit/log",
            payload={
                "bot_identifier": BOT_IDENTIFIER,
                "action": action[:80],
                "entity_type": entity_type[:50] if entity_type else None,
                "entity_id": str(entity_id)[:500] if entity_id is not None else None,
                "details": details or None,
                "ip": ip or None,
            },
            token=token,
        )
        response.raise_for_status()
    except Exception:
        pass
