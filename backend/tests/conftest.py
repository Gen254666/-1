import os
from collections.abc import AsyncIterator

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
