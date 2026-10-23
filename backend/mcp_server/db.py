from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_mcp_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.database_url_mcp, pool_pre_ping=True)


@lru_cache
def get_mcp_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_mcp_engine(), expire_on_commit=False)


@asynccontextmanager
async def mcp_session() -> AsyncIterator[AsyncSession]:
    factory = get_mcp_session_factory()
    async with factory() as session:
        yield session
