"""Task type definitions for Redis queue."""
from typing import Any, TypedDict


class BaseTask(TypedDict):
    type: str
    payload: dict[str, Any]
