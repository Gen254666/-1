from typing import Any

import fakeredis.aioredis

from app.core.rate_limit import RateLimiter


async def test_allows_limit_then_blocks() -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    limiter = RateLimiter(client)

    for _ in range(3):
        assert await limiter.allow(scope="login", identifier="1.2.3.4", limit=3, window_seconds=60)

    assert not await limiter.allow(scope="login", identifier="1.2.3.4", limit=3, window_seconds=60)
    assert await limiter.allow(scope="login", identifier="5.6.7.8", limit=3, window_seconds=60)


async def test_falls_back_to_memory_when_redis_fails() -> None:
    class BrokenRedis:
        async def zremrangebyscore(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("redis down")

        async def zcard(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("redis down")

        async def zadd(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("redis down")

        async def pexpire(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("redis down")

    limiter = RateLimiter(BrokenRedis())

    assert await limiter.allow(scope="login", identifier="1.2.3.4", limit=2, window_seconds=60)
    assert await limiter.allow(scope="login", identifier="1.2.3.4", limit=2, window_seconds=60)
    assert not await limiter.allow(scope="login", identifier="1.2.3.4", limit=2, window_seconds=60)
