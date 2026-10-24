from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from steel_core.db.enums import PointScope, Role
from steel_core.db.models.accounts import User
from steel_core.db.models.market import PricePoint
from steel_core.ingest.service import (
    ImportValidationError,
    import_quotes,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description="导入 Mysteel 报价 CSV")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--source", default="mysteel")
    args = parser.parse_args()

    engine = create_async_engine(get_settings().database_url_agent)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            admin = await session.scalar(
                select(User).where(User.role == Role.ADMIN).order_by(User.created_at).limit(1)
            )
            if admin is None:
                print("没有可用的 admin 用户，请先执行 seed")
                return 1
            points = list(
                (
                    await session.scalars(
                        select(PricePoint).where(
                            PricePoint.scope == PointScope.PUBLIC,
                            PricePoint.is_active.is_(True),
                        )
                    )
                ).all()
            )
            allowed = {point.code: point.id for point in points}
            try:
                outcome = await import_quotes(
                    session,
                    user_id=admin.id,
                    path=args.file,
                    allowed_points=allowed,
                    expected_point_codes=set(allowed),
                    default_source=args.source,
                )
            except ImportValidationError as exc:
                print("导入失败:")
                for issue in exc.errors:
                    print(f" - 第{issue.row_no}行 {issue.field}: {issue.message}")
                return 1
    finally:
        await engine.dispose()

    print(f"batch_id: {outcome.batch_id}")
    print(f"version_id: {outcome.version_id}")
    print(f"effective_date: {outcome.effective_date}")
    print(f"rows_ok: {outcome.rows_ok}, no_changes: {outcome.no_changes}")
    for warning in outcome.warnings:
        print(f"warning: {warning.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
