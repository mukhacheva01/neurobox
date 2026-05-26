"""HTTP helpers from admin-service to backend-service."""
from __future__ import annotations

import os

import httpx


def _base_url() -> str:
    return os.environ.get("BACKEND_URL", "http://backend:8092").rstrip("/")


def post_json(
    path: str,
    *,
    payload: dict | None = None,
    token: str | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.post(
        f"{_base_url()}{path}",
        json=payload,
        headers=headers,
        timeout=timeout,
    )
