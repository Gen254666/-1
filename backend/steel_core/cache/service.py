from __future__ import annotations

import hashlib
import json
import time
from datetime import date
from typing import Any
from uuid import UUID


def _filters_suffix(filters: dict[str, Any] | None) -> str:
    payload = json.dumps(filters or {}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def build_quotes_cache_key(
    *,
    quote_date: date,
    user_id: UUID | None,
    has_private: bool,
    filters: dict[str, Any] | None = None,
) -> str:
    suffix = _filters_suffix(filters)
    if has_private:
        if user_id is None:
            msg = "私有查询的缓存 key 必须包含 user_id"
            raise ValueError(msg)
        return f"cache:quotes:user:{user_id}:{quote_date.isoformat()}:{suffix}"
    return f"cache:quotes:{quote_date.isoformat()}:{suffix}"


def build_dashboard_cache_key(
    *,
    quote_date: date,
    user_id: UUID | None,
    has_private: bool,
    filters: dict[str, Any] | None = None,
) -> str:
    suffix = _filters_suffix(filters)
    if has_private:
        if user_id is None:
            msg = "私有查询的缓存 key 必须包含 user_id"
            raise ValueError(msg)
        return f"cache:dashboard:user:{user_id}:{quote_date.isoformat()}:{suffix}"
    return f"cache:dashboard:{quote_date.isoformat()}:{suffix}"


class Cache:
    def __init__(self, client: Any | None = None, *, default_ttl: int = 300) -> None:
        self._client = client
        self._default_ttl = default_ttl
        self._fallback = client is None
        self._memory: dict[str, tuple[str, float]] = {}

    async def get_json(self, key: str) -> Any | None:
        client = self._client
        if client is not None and not self._fallback:
            try:
                raw = await client.get(key)
                if raw is None:
                    return None
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                return json.loads(raw)
            except Exception:  # noqa: BLE001
                self._fallback = True
        return self._memory_get(key)

    async def set_json(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        client = self._client
        if client is not None and not self._fallback:
            try:
                await client.set(key, payload, ex=ttl or self._default_ttl)
                return
            except Exception:  # noqa: BLE001
                self._fallback = True
        self._memory[key] = (
            payload,
            time.monotonic() + (ttl or self._default_ttl),
        )

    async def delete(self, key: str) -> None:
        client = self._client
        if client is not None and not self._fallback:
            try:
                await client.delete(key)
            except Exception:  # noqa: BLE001
                self._fallback = True
        self._memory.pop(key, None)

    async def invalidate_date(self, quote_date: date) -> None:
        marker = quote_date.isoformat()
        client = self._client
        if client is not None and not self._fallback:
            try:
                keys = [key async for key in client.scan_iter(match="cache:*")]
                to_delete = [key for key in keys if marker in key]
                if to_delete:
                    await client.delete(*to_delete)
            except Exception:  # noqa: BLE001
                self._fallback = True
        for key in [key for key in self._memory if marker in key]:
            del self._memory[key]

    def _memory_get(self, key: str) -> Any | None:
        item = self._memory.get(key)
        if item is None:
            return None
        payload, expires_at = item
        if time.monotonic() >= expires_at:
            del self._memory[key]
            return None
        return json.loads(payload)
