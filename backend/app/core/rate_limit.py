from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from typing import Any

from fastapi import Depends, Request

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.redis import get_redis_client


class RateLimiter:
    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        self._fallback = client is None
        self._memory: dict[str, deque[float]] = defaultdict(deque)

    async def allow(
        self,
        *,
        scope: str,
        identifier: str,
        limit: int,
        window_seconds: int,
    ) -> bool:
        if self._fallback and self._client is not None:
            return await _FALLBACK_LIMITER.allow(
                scope=scope,
                identifier=identifier,
                limit=limit,
                window_seconds=window_seconds,
            )

        key = f"rl:{scope}:{identifier}"
        now = time.time()
        client = self._client

        if client is not None and not self._fallback:
            try:
                now_ms = int(now * 1000)
                window_ms = window_seconds * 1000
                await client.zremrangebyscore(key, 0, now_ms - window_ms)
                count = int(await client.zcard(key) or 0)
                if count >= limit:
                    return False
                await client.zadd(key, {f"{now_ms}-{uuid.uuid4().hex}": now_ms})
                await client.pexpire(key, window_ms)
                return True
            except Exception:  # noqa: BLE001
                self._fallback = True
                return await _FALLBACK_LIMITER.allow(
                    scope=scope,
                    identifier=identifier,
                    limit=limit,
                    window_seconds=window_seconds,
                )

        bucket = self._memory[key]
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


_FALLBACK_LIMITER = RateLimiter()


async def login_rate_limit(
    request: Request,
    redis: Any | None = Depends(get_redis_client),
) -> None:
    settings = get_settings()
    identifier = request.client.host if request.client else "unknown"
    limiter = RateLimiter(redis)
    allowed = await limiter.allow(
        scope="login",
        identifier=identifier,
        limit=settings.login_rate_limit,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if not allowed:
        raise ApiError(429, "RATE_LIMITED", "请求过于频繁，请稍后再试")
