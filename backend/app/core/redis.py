from __future__ import annotations

from functools import lru_cache
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings


@lru_cache
def get_redis_client() -> Any | None:
    settings = get_settings()
    try:
        return Redis.from_url(settings.redis_url, decode_responses=True)
    except Exception:  # noqa: BLE001
        return None
