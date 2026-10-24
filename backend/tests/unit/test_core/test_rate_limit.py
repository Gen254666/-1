import uuid
from typing import Any

import fakeredis.aioredis
import pytest

from app.core.errors import ApiError
from app.core.rate_limit import RateLimiter, data_rate_limit
from steel_core.db.models.accounts import User


async def test_allows_limit_then_blocks() -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    limiter = RateLimiter(client)

    for _ in range(3):
        assert await limiter.allow(scope="login", identifier="1.2.3.4", limit=3, window_seconds=60)

    assert not await limiter.allow(scope="login", identifier="1.2.3.4", limit=3, window_seconds=60)
    assert await limiter.allow(scope="login", identifier="5.6.7.8", limit=3, window_seconds=60)


async def test_data_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    user = User(id=uuid.uuid4(), username="test", password_hash="x")
    monkeypatch.setattr(
        "app.core.rate_limit.get_settings",
        lambda: type(
            "Settings",
            (),
            {"data_rate_limit": 2, "rate_limit_window_seconds": 60},
        )(),
    )

    await data_rate_limit(user=user, redis=client)
    await data_rate_limit(user=user, redis=client)

    with pytest.raises(ApiError) as exc:
        await data_rate_limit(user=user, redis=client)

    assert exc.value.status_code == 429
    assert exc.value.code == "RATE_LIMITED"


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
