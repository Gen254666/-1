from __future__ import annotations

import argparse
import asyncio
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from steel_core.db.enums import Role
from steel_core.db.models.accounts import User
from steel_core.ingest.derivation import DerivationOutcome, derive_from_active_snapshot


async def sync_inventory(
    session: AsyncSession,
    *,
    admin_username: str,
    effective_date: date,
    force: bool = False,
) -> DerivationOutcome | None:
    admin = await session.scalar(select(User).where(User.username == admin_username))
    if admin is None or admin.role != Role.ADMIN:
        raise ValueError(f"管理员不存在或权限不足: {admin_username}")
    return await derive_from_active_snapshot(
        session,
        user_id=admin.id,
        effective_date=effective_date,
        force=force,
    )


async def _run(args: argparse.Namespace) -> int:
    from app.core.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url_agent, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            try:
                outcome = await sync_inventory(
                    session,
                    admin_username=args.admin_username,
                    effective_date=args.effective_date,
                    force=args.force,
                )
            except ValueError as exc:
                print(str(exc))
                return 1
            if outcome is None:
                print(f"没有找到 {args.effective_date.isoformat()} 的 active 库存快照")
                return 1
            await session.commit()
    finally:
        await engine.dispose()

    print(f"点位新增: {outcome.points_created}")
    print(f"点位更新: {outcome.points_updated}")
    print(f"点位停用: {outcome.points_deactivated}")
    print(f"行情写入: {outcome.quotes_written}")
    print(f"行情无变化: {outcome.quote_no_changes}")
    print(f"行情版本: {outcome.quote_version_id}")
    for warning in outcome.warnings:
        print(f"warning: {warning.message}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="从 active 库存快照重推导点位与行情")
    parser.add_argument("--date", dest="effective_date", type=date.fromisoformat, required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--admin-username", default="admin")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
