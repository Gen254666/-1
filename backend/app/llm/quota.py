from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from datetime import time as dt_time
from typing import Any
from uuid import UUID

CHINA_TZ = timezone(timedelta(hours=8))
_MEMORY: dict[str, tuple[int, int]] = {}


def _quota_key(user_id: UUID) -> tuple[str, int]:
    now = datetime.now(CHINA_TZ)
    reset_at = datetime.combine(now.date() + timedelta(days=1), dt_time.min, CHINA_TZ)
    return f"quota:llm:{now.date().isoformat()}:{user_id}", int(reset_at.timestamp())


async def consume_llm_quota(
    redis: Any | None,
    *,
    user_id: UUID,
    limit: int,
) -> bool:
    if limit <= 0:
        return False

    key, reset_at = _quota_key(user_id)
    if redis is not None:
        try:
            count = int(await redis.incr(key))
            if count == 1 or int(await redis.ttl(key)) < 0:
                await redis.expireat(key, reset_at)
            return count <= limit
        except Exception:  # noqa: BLE001
            pass

    now = time.time()
    count, expires_at = _MEMORY.get(key, (0, reset_at))
    if expires_at <= now:
        count, expires_at = 0, reset_at
    count += 1
    _MEMORY[key] = (count, expires_at)
    return count <= limit
