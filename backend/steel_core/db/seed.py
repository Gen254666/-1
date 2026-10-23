from __future__ import annotations

import asyncio
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import PointScope, Role
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import AppConfig
from steel_core.db.models.market import PricePoint
from steel_core.security import hash_password

PUBLIC_POINTS: list[dict[str, Any]] = [
    {
        "code": "FANG_100X100X2.5_KUNMING",
        "category": "方管",
        "spec": "100×100×2.5×6m",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "FANG_150X150X3.0_KUNMING",
        "category": "方管",
        "spec": "150×150×3.0×6m",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "JU_100X150X2.5_KUNMING",
        "category": "矩管",
        "spec": "100×150×2.5×6m",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "JU_100X200X3.0_KUNMING",
        "category": "矩管",
        "spec": "100×200×3.0×6m",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "HANGUAN_4IN_3.75_KUNMING",
        "category": "圆管",
        "spec": "4寸×3.75",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "DUXINGUAN_4IN_3.75_KUNMING",
        "category": "镀锌管",
        "spec": "4寸×3.75",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "JIAOGANG_50X5_KUNMING",
        "category": "角钢",
        "spec": "50×5",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "CAOGANG_16_KUNMING",
        "category": "槽钢",
        "spec": "16#",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "HXINGGANG_300X300_KUNMING",
        "category": "H型钢",
        "spec": "300×300",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "ZHONGHOUBAN_20_KUNMING",
        "category": "中厚板",
        "spec": "20mm",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "REJUAN_4.75X1500_KUNMING",
        "category": "热卷",
        "spec": "4.75×1500×C",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "GAOXIAN_PHI8_KUNMING",
        "category": "高线",
        "spec": "Φ8",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "PANLUO_PHI8_KUNMING",
        "category": "盘螺",
        "spec": "Φ8",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "LUOWENG_HBR400E_PHI20_KUNMING",
        "category": "螺纹钢",
        "spec": "HRB400E Φ20",
        "region": "昆明",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "REJUAN_4.75X1500_CHENGDU",
        "category": "热卷",
        "spec": "4.75×1500×C",
        "region": "成都",
        "source": "mysteel",
        "unit": "元/吨",
    },
    {
        "code": "LUOWENG_HBR400E_PHI20_GUIYANG",
        "category": "螺纹钢",
        "spec": "HRB400E Φ20",
        "region": "贵阳",
        "source": "mysteel",
        "unit": "元/吨",
    },
]

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
    created_points = 0
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

    existing_codes = set(await session.scalars(select(PricePoint.code)))
    for point in PUBLIC_POINTS:
        if point["code"] not in existing_codes:
            session.add(PricePoint(scope=PointScope.PUBLIC, **point))
            created_points += 1

    existing_keys = set(await session.scalars(select(AppConfig.key)))
    for key, value in DEFAULT_APP_CONFIG.items():
        if key not in existing_keys:
            session.add(AppConfig(key=key, value=value))
            created_configs += 1

    await session.commit()
    return {
        "users": created_users,
        "points": created_points,
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
