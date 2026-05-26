"""HTTP client from bot-service to backend-service."""
import httpx
import structlog

_log = structlog.get_logger()
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        from shared.config import settings
        base_url = getattr(settings, "backend_url", "http://backend:8092")
        _client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get_or_create_user(user_id: int, username: str | None = None, first_name: str | None = None, referral_code: str | None = None) -> dict:
    """Создать или получить пользователя через backend."""
    try:
        r = await _get_client().post("/bot/users/get_or_create", json={
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "referral_code": referral_code,
        })
        return r.json()
    except Exception as e:
        _log.error("backend_client_error", method="get_or_create_user", error=str(e))
        return {}


async def get_balance(user_id: int) -> dict:
    try:
        r = await _get_client().get(f"/bot/users/{user_id}/balance")
        return r.json()
    except Exception as e:
        _log.error("backend_client_error", method="get_balance", error=str(e))
        return {"credits_bought": 0, "credits_free_today": 0}


async def spend_credits(user_id: int, amount: int, model: str, task_type: str, description: str = "") -> dict:
    try:
        r = await _get_client().post("/bot/credits/spend", json={
            "user_id": user_id, "amount": amount, "model": model,
            "task_type": task_type, "description": description,
        })
        return r.json()
    except Exception as e:
        _log.error("backend_client_error", method="spend_credits", error=str(e))
        return {"ok": False, "error": str(e)}


async def refund_credits(user_id: int, amount: int, model: str, task_type: str) -> dict:
    try:
        r = await _get_client().post("/bot/credits/refund", json={
            "user_id": user_id, "amount": amount, "model": model, "task_type": task_type,
        })
        return r.json()
    except Exception as e:
        _log.error("backend_client_error", method="refund_credits", error=str(e))
        return {"ok": False}
