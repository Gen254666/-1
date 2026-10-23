import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.analysis.service import calculate_spread, scan_anomalies
from steel_core.db.enums import DatasetType, PointScope, Role
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import DatasetVersion
from steel_core.db.models.inventory import InventoryItem, InventorySnapshot
from steel_core.db.models.market import MarketQuote, PricePoint
from steel_core.versioning.service import create_import_batch, create_version

pytestmark = pytest.mark.integration

REPORT_DATE = date(2026, 10, 23)


async def _make_user(session: AsyncSession) -> User:
    user = User(
        username=f"user-{uuid.uuid4().hex[:8]}",
        password_hash="not-used",
        role=Role.USER,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_point(
    session: AsyncSession,
    code: str,
    *,
    owner: User | None = None,
    category: str = "方管",
    spec: str = "100*100*2.5*6m",
    region: str = "昆明",
) -> PricePoint:
    point = PricePoint(
        scope=PointScope.PRIVATE if owner is not None else PointScope.PUBLIC,
        owner_user_id=owner.id if owner is not None else None,
        code=code,
        category=category,
        spec=spec,
        region=region,
        source="mysteel",
        unit="元/吨",
    )
    session.add(point)
    await session.flush()
    return point


async def _make_version(
    session: AsyncSession,
    user: User,
    effective_date: date,
    *,
    dataset_type: DatasetType = DatasetType.MARKET_QUOTE,
) -> DatasetVersion:
    batch = await create_import_batch(
        session,
        user_id=user.id,
        dataset_type=dataset_type,
        effective_date=effective_date,
        file_name="data.csv",
        file_hash=uuid.uuid4().hex,
        rows_total=1,
        rows_ok=1,
        rows_failed=0,
    )
    return await create_version(
        session,
        dataset_type=dataset_type,
        effective_date=effective_date,
        checksum=uuid.uuid4().hex,
        import_batch_id=batch.id,
    )


async def _add_quote(
    session: AsyncSession,
    version: DatasetVersion,
    point: PricePoint,
    quote_date: date,
    price: str,
) -> None:
    session.add(
        MarketQuote(
            version_id=version.id,
            point_id=point.id,
            quote_date=quote_date,
            price=Decimal(price),
            source="mysteel",
        )
    )
    await session.flush()


async def _add_snapshot(
    session: AsyncSession,
    owner: User,
    snapshot_date: date,
    pieces: int,
) -> None:
    version = await _make_version(session, owner, snapshot_date, dataset_type=DatasetType.INVENTORY)
    snapshot = InventorySnapshot(
        version_id=version.id,
        snapshot_date=snapshot_date,
        warehouse="昆明宝象库",
        source_file=f"{snapshot_date}.xlsx",
    )
    session.add(snapshot)
    await session.flush()
    session.add(
        InventoryItem(
            snapshot_id=snapshot.id,
            block="方管",
            spec="100*100*2.5*6m",
            unit_price=Decimal("3550"),
            pieces=pieces,
            total_weight=Decimal("1.0"),
            price_per_piece=Decimal("88.5"),
            manufacturer="正大",
            row_no=4,
        )
    )
    await session.flush()


async def test_calculate_spread_aligns_dates(session: AsyncSession) -> None:
    owner = await _make_user(session)
    left = await _make_point(session, "LEFT", category="热卷")
    right = await _make_point(session, "RIGHT", category="热卷")
    for offset, left_price, right_price in [
        (1, "3560", "3500"),
        (0, "3600", "3700"),
    ]:
        quote_date = REPORT_DATE - timedelta(days=offset)
        version = await _make_version(session, owner, quote_date)
        await _add_quote(session, version, left, quote_date, left_price)
        await _add_quote(session, version, right, quote_date, right_price)

    result = await calculate_spread(
        session,
        user_id=owner.id,
        left_point_id=left.id,
        right_point_id=right.id,
        start_date=REPORT_DATE - timedelta(days=7),
        end_date=REPORT_DATE,
    )

    assert result is not None
    assert [point.value for point in result.points] == [
        Decimal("60"),
        Decimal("-100"),
    ]
    assert result.latest == Decimal("-100")
    assert result.maximum == Decimal("60")
    assert result.minimum == Decimal("-100")


async def test_calculate_spread_without_permission_returns_none(
    session: AsyncSession,
) -> None:
    owner = await _make_user(session)
    other = await _make_user(session)
    public = await _make_point(session, "PUBLIC")
    private = await _make_point(session, "PRIVATE", owner=owner)
    version = await _make_version(session, owner, REPORT_DATE)
    await _add_quote(session, version, public, REPORT_DATE, "3500")
    await _add_quote(session, version, private, REPORT_DATE, "3600")

    result = await calculate_spread(
        session,
        user_id=other.id,
        left_point_id=private.id,
        right_point_id=public.id,
        start_date=REPORT_DATE - timedelta(days=7),
        end_date=REPORT_DATE,
    )

    assert result is None


async def test_scan_anomalies_detects_price_consecutive_and_stock(
    session: AsyncSession,
) -> None:
    owner = await _make_user(session)
    consecutive = await _make_point(session, "CONSECUTIVE")
    jump = await _make_point(session, "JUMP")
    prices = ["3500", "3530", "3560", "3600"]
    for offset, price in enumerate(prices):
        quote_date = REPORT_DATE - timedelta(days=len(prices) - 1 - offset)
        version = await _make_version(session, owner, quote_date)
        await _add_quote(session, version, consecutive, quote_date, price)
        if offset >= 2:
            jump_price = "3500" if offset == 2 else "3700"
            await _add_quote(session, version, jump, quote_date, jump_price)

    for offset, pieces in [(3, 100), (2, 100), (1, 100), (0, 5)]:
        await _add_snapshot(session, owner, REPORT_DATE - timedelta(days=offset), pieces)

    anomalies = await scan_anomalies(session, user_id=owner.id, quote_date=REPORT_DATE)
    kinds = {anomaly.kind for anomaly in anomalies}

    assert "price_change" in kinds
    assert "consecutive" in kinds
    assert "low_stock" in kinds
    assert "inventory_deviation" in kinds
