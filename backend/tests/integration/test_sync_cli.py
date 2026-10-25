import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.cli.sync_inventory import sync_inventory
from steel_core.db.enums import DatasetType, Role
from steel_core.db.models.accounts import User
from steel_core.db.models.inventory import InventoryItem, InventorySnapshot
from steel_core.db.models.market import MarketQuote, PricePoint
from steel_core.versioning.service import create_import_batch, create_version

pytestmark = pytest.mark.integration

DATE = date(2026, 10, 25)


async def _make_admin(session: AsyncSession) -> User:
    user = User(username="admin", password_hash="not-used", role=Role.ADMIN)
    session.add(user)
    await session.flush()
    return user


async def _make_inventory_snapshot(session: AsyncSession, user: User) -> None:
    batch = await create_import_batch(
        session,
        user_id=user.id,
        dataset_type=DatasetType.INVENTORY,
        effective_date=DATE,
        file_name="10.25库存状况表.xlsx",
        file_hash=uuid.uuid4().hex,
        rows_total=1,
        rows_ok=1,
        rows_failed=0,
    )
    version = await create_version(
        session,
        dataset_type=DatasetType.INVENTORY,
        effective_date=DATE,
        checksum=uuid.uuid4().hex,
        import_batch_id=batch.id,
    )
    snapshot = InventorySnapshot(
        version_id=version.id,
        snapshot_date=DATE,
        warehouse="昆明宝象库",
        source_file="10.25库存状况表.xlsx",
    )
    session.add(snapshot)
    await session.flush()
    session.add(
        InventoryItem(
            snapshot_id=snapshot.id,
            block="方管",
            spec="100*100*2.5*6m",
            unit_price=Decimal("3550"),
            weight_per_piece=Decimal("24.93"),
            pieces=230,
            row_no=4,
        )
    )
    await session.commit()


async def test_sync_inventory_from_active_snapshot(session: AsyncSession) -> None:
    admin = await _make_admin(session)
    await _make_inventory_snapshot(session, admin)

    outcome = await sync_inventory(
        session, admin_username="admin", effective_date=DATE, force=False
    )
    await session.commit()

    assert outcome is not None
    assert outcome.points_created == 1
    assert outcome.quotes_written == 1
    point = await session.scalar(
        select(PricePoint).where(PricePoint.code == "FANG_100X100X2.5X6M_KUNMING")
    )
    assert point is not None
    quote = await session.scalar(select(MarketQuote).where(MarketQuote.point_id == point.id))
    assert quote is not None
    assert quote.price == Decimal("3550")


async def test_sync_inventory_without_active_snapshot(session: AsyncSession) -> None:
    await _make_admin(session)

    outcome = await sync_inventory(
        session,
        admin_username="admin",
        effective_date=date(2026, 10, 24),
        force=False,
    )

    assert outcome is None
