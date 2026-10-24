from __future__ import annotations

import asyncio

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from steel_core.db.enums import Role
from steel_core.db.models.accounts import User
from steel_core.security import hash_password

E2E_USERNAME = "e2e_user"
E2E_PASSWORD = "E2ePass123!"


async def main() -> None:
    engine = create_async_engine(get_settings().database_url_agent)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(delete(User).where(User.username == E2E_USERNAME))
            session.add(
                User(
                    username=E2E_USERNAME,
                    password_hash=hash_password(E2E_PASSWORD),
                    role=Role.USER,
                    must_change_password=False,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
    print(f"e2e user ready: {E2E_USERNAME}")


if __name__ == "__main__":
    asyncio.run(main())
