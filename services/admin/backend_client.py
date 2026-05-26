"""HTTP client from admin-service to backend-service."""
import httpx
import structlog

_log = structlog.get_logger()
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        import os
        base_url = os.environ.get("BACKEND_URL", "http://backend:8092")
        _client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
