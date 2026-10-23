import os
from collections.abc import AsyncIterator
from typing import Any

import fakeredis.aioredis
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from steel_core.db import models  # noqa: F401  (import registers all tables)
from steel_core.db.base import Base

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://steel_agent:steel_agent_dev@localhost:55432/steel_market_test",
)


@pytest_asyncio.fixture(scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True, connect_args={"timeout": 3})
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"PostgreSQL test database unavailable: {exc}")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with db_engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
        await db_session.rollback()


@pytest_asyncio.fixture
async def app_instance(db_engine: AsyncEngine) -> AsyncIterator[Any]:
    from app.core.db import get_db_session, get_db_session_factory
    from app.core.redis import get_redis_client
    from app.main import create_app

    app = create_app()
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def override_db() -> AsyncIterator[AsyncSession]:
        async with factory() as db_session:
            yield db_session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_db_session_factory] = lambda: factory
    app.dependency_overrides[get_redis_client] = lambda: fake_redis

    yield app

    app.dependency_overrides.clear()
    await fake_redis.aclose()


@pytest_asyncio.fixture
async def app_client(app_instance: Any) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app_instance)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
