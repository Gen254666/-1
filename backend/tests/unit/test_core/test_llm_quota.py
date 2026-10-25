import uuid

import fakeredis.aioredis

from app.llm.quota import consume_llm_quota


async def test_quota_blocks_after_limit() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    user_id = uuid.uuid4()
    try:
        assert await consume_llm_quota(redis, user_id=user_id, limit=2) is True
        assert await consume_llm_quota(redis, user_id=user_id, limit=2) is True
        assert await consume_llm_quota(redis, user_id=user_id, limit=2) is False
    finally:
        await redis.aclose()


async def test_quota_memory_fallback() -> None:
    user_id = uuid.uuid4()

    assert await consume_llm_quota(None, user_id=user_id, limit=1) is True
    assert await consume_llm_quota(None, user_id=user_id, limit=1) is False
