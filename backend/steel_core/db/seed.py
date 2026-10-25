from __future__ import annotations

import asyncio
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import Role
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import AppConfig
from steel_core.security import hash_password

DEFAULT_APP_CONFIG: dict[str, dict[str, Any]] = {
    "anomaly": {
        "daily_change_pct": 2.0,
        "consecutive_days": 3,
        "inventory_deviation_pct": 30.0,
        "low_stock_pieces": 10,
    },
    "quote": {"tax_mode": "as_is"},
    "disclaimer": {
        "quote": "本报价基于当日库存与行情数据生成，仅供参考，最终成交价以合同为准。",
        "report": "本报告基于公开与内部数据整理，仅供参考，不构成投资或交易建议。",
    },
}

DEV_ADMIN_PASSWORD = "ChangeMe123!"


async def seed_all(
    session: AsyncSession, *, admin_username: str, admin_password: str
) -> dict[str, int]:
    created_users = 0
    created_configs = 0

    existing_admin = await session.scalar(select(User).where(User.username == admin_username))
    if existing_admin is None:
        session.add(
            User(
                username=admin_username,
                password_hash=hash_password(admin_password),
                role=Role.ADMIN,
                is_active=True,
                must_change_password=True,
            )
        )
        created_users = 1

    existing_keys = set(await session.scalars(select(AppConfig.key)))
    for key, value in DEFAULT_APP_CONFIG.items():
        if key not in existing_keys:
            session.add(AppConfig(key=key, value=value))
            created_configs += 1

    await session.commit()
    return {
        "users": created_users,
        "points": 0,
        "configs": created_configs,
    }


async def _main() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings

    settings = get_settings()
    username = os.getenv("INITIAL_ADMIN_USERNAME", "admin")
    password = os.getenv("INITIAL_ADMIN_PASSWORD")
    if not password:
        if settings.environment == "prod":
            raise SystemExit("INITIAL_ADMIN_PASSWORD is required in production")
        password = DEV_ADMIN_PASSWORD

    engine = create_async_engine(settings.database_url_agent, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            result = await seed_all(session, admin_username=username, admin_password=password)
    finally:
        await engine.dispose()

    print(f"seed complete: {result}")
    if not os.getenv("INITIAL_ADMIN_PASSWORD"):
        print("WARNING: development admin password in use; change it on first login")


if __name__ == "__main__":
    asyncio.run(_main())
