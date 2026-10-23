import uuid
from datetime import date
from typing import Any

import fakeredis.aioredis

from steel_core.cache.service import (
    Cache,
    build_dashboard_cache_key,
    build_quotes_cache_key,
)

QUOTE_DATE = date(2026, 10, 23)


def test_private_cache_key_is_user_scoped() -> None:
    first_user = uuid.uuid4()
    second_user = uuid.uuid4()

    first = build_quotes_cache_key(quote_date=QUOTE_DATE, user_id=first_user, has_private=True)
    second = build_quotes_cache_key(quote_date=QUOTE_DATE, user_id=second_user, has_private=True)

    assert f"user:{first_user}" in first
    assert first != second


def test_public_cache_key_is_shared_between_users() -> None:
    first = build_quotes_cache_key(quote_date=QUOTE_DATE, user_id=uuid.uuid4(), has_private=False)
    second = build_quotes_cache_key(quote_date=QUOTE_DATE, user_id=uuid.uuid4(), has_private=False)

    assert first == second
    assert "user:" not in first

    dashboard_first = build_dashboard_cache_key(
        quote_date=QUOTE_DATE, user_id=uuid.uuid4(), has_private=False
    )
    dashboard_second = build_dashboard_cache_key(
        quote_date=QUOTE_DATE, user_id=uuid.uuid4(), has_private=False
    )
    assert dashboard_first == dashboard_second


async def test_cache_set_get_and_invalidate_date() -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cache = Cache(client)
    today_key = "cache:quotes:2026-10-23:a"
    yesterday_key = "cache:quotes:2026-10-22:b"

    await cache.set_json(today_key, {"value": 1})
    await cache.set_json(yesterday_key, {"value": 2})

    assert await cache.get_json(today_key) == {"value": 1}
    assert await cache.get_json(yesterday_key) == {"value": 2}

    await cache.invalidate_date(QUOTE_DATE)

    assert await cache.get_json(today_key) is None
    assert await cache.get_json(yesterday_key) == {"value": 2}


async def test_cache_falls_back_to_memory_when_redis_fails() -> None:
    class BrokenRedis:
        async def get(self, key: str) -> Any:
            raise RuntimeError("redis down")

        async def set(self, key: str, value: str, ex: int | None = None) -> Any:
            raise RuntimeError("redis down")

        async def scan_iter(self, match: str | None = None) -> Any:
            raise RuntimeError("redis down")

        async def delete(self, *keys: str) -> Any:
            raise RuntimeError("redis down")

    cache = Cache(BrokenRedis())

    await cache.set_json("cache:quotes:2026-10-23:x", {"value": 3})

    assert await cache.get_json("cache:quotes:2026-10-23:x") == {"value": 3}
