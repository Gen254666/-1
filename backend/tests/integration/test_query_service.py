import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import DatasetType, PointScope, Role
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import DatasetVersion
from steel_core.db.models.inventory import InventoryItem, InventorySnapshot
from steel_core.db.models.market import MarketQuote, PricePoint
from steel_core.query.service import (
    QueryValidationError,
    find_inventory_item,
    get_inventory,
    get_price_history,
    get_quotes,
    list_points,
)
from steel_core.versioning.service import create_import_batch, create_version

pytestmark = pytest.mark.integration

QUOTE_DATE = date(2026, 10, 23)


async def _make_user(session: AsyncSession, role: Role = Role.USER) -> User:
    user = User(
        username=f"user-{uuid.uuid4().hex[:8]}",
        password_hash="not-used",
        role=role,
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
    *,
    dataset_type: DatasetType = DatasetType.MARKET_QUOTE,
    effective_date: date = QUOTE_DATE,
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
    price: str,
    *,
    quote_date: date = QUOTE_DATE,
    change: str | None = None,
) -> None:
    session.add(
        MarketQuote(
            version_id=version.id,
            point_id=point.id,
            quote_date=quote_date,
            price=Decimal(price),
            change=Decimal(change) if change is not None else None,
            source="mysteel",
        )
    )
    await session.flush()


async def test_list_points_respects_visibility(session: AsyncSession) -> None:
    owner_a = await _make_user(session)
    owner_b = await _make_user(session)
    admin = await _make_user(session, Role.ADMIN)
    public = await _make_point(session, "PUBLIC")
    private_a = await _make_point(session, "PRIVATE_A", owner=owner_a)
    private_b = await _make_point(session, "PRIVATE_B", owner=owner_b)

    points_a = await list_points(session, user_id=owner_a.id)
    points_b = await list_points(session, user_id=owner_b.id)
    points_admin = await list_points(session, user_id=admin.id)

    assert {point.code for point in points_a} == {"PUBLIC", "PRIVATE_A"}
    assert {point.code for point in points_b} == {"PUBLIC", "PRIVATE_B"}
    assert {point.code for point in points_admin} == {"PUBLIC"}
    assert public.code == "PUBLIC"
    assert private_a.owner_user_id == owner_a.id
    assert private_b.owner_user_id == owner_b.id


async def test_get_quotes_filters_and_paginates(session: AsyncSession) -> None:
    owner = await _make_user(session)
    other = await _make_user(session)
    public = await _make_point(session, "PUBLIC")
    private = await _make_point(session, "PRIVATE", owner=owner)
    hidden = await _make_point(session, "HIDDEN", owner=other)
    version = await _make_version(session, owner)
    await _add_quote(session, version, public, "3550", change="10")
    await _add_quote(session, version, private, "3600")
    await _add_quote(session, version, hidden, "3700")

    page = await get_quotes(session, user_id=owner.id, page=1, page_size=20)
    assert page.total == 2
    assert {item.code for item in page.items} == {"PUBLIC", "PRIVATE"}
    assert page.items[0].quote_date == QUOTE_DATE

    paged = await get_quotes(session, user_id=owner.id, page=1, page_size=1)
    assert paged.total == 2
    assert len(paged.items) == 1

    filtered = await get_quotes(session, user_id=owner.id, category="方管")
    assert filtered.total == 2

    admin = await _make_user(session, Role.ADMIN)
    admin_page = await get_quotes(session, user_id=admin.id)
    assert admin_page.total == 1
    assert admin_page.items[0].code == "PUBLIC"


async def test_get_quotes_uses_latest_date(session: AsyncSession) -> None:
    owner = await _make_user(session)
    point = await _make_point(session, "PUBLIC")
    first = await _make_version(session, owner, effective_date=QUOTE_DATE - timedelta(days=1))
    second = await _make_version(session, owner, effective_date=QUOTE_DATE)
    await _add_quote(session, first, point, "3500", quote_date=QUOTE_DATE - timedelta(days=1))
    await _add_quote(session, second, point, "3550", quote_date=QUOTE_DATE)

    page = await get_quotes(session, user_id=owner.id)

    assert page.total == 1
    assert page.items[0].price == Decimal("3550")


async def test_price_history_stats_and_validation(session: AsyncSession) -> None:
    owner = await _make_user(session)
    point = await _make_point(session, "PUBLIC")
    first = await _make_version(session, owner, effective_date=QUOTE_DATE - timedelta(days=2))
    second = await _make_version(session, owner, effective_date=QUOTE_DATE)
    await _add_quote(session, first, point, "3500", quote_date=QUOTE_DATE - timedelta(days=2))
    await _add_quote(session, second, point, "3570", quote_date=QUOTE_DATE)

    series = await get_price_history(
        session,
        user_id=owner.id,
        point_ids=[point.id],
        start_date=QUOTE_DATE - timedelta(days=7),
        end_date=QUOTE_DATE,
    )

    assert len(series) == 1
    assert series[0].latest == Decimal("3570")
    assert series[0].minimum == Decimal("3500")
    assert series[0].maximum == Decimal("3570")
    assert series[0].average == Decimal("3535")
    assert series[0].change == Decimal("70")
    assert series[0].change_pct == Decimal("2")

    with pytest.raises(QueryValidationError):
        await get_price_history(
            session,
            user_id=owner.id,
            point_ids=[point.id],
            start_date=QUOTE_DATE - timedelta(days=731),
            end_date=QUOTE_DATE,
        )

    with pytest.raises(QueryValidationError):
        await get_price_history(
            session,
            user_id=owner.id,
            point_ids=[point.id] * 21,
            start_date=QUOTE_DATE - timedelta(days=30),
            end_date=QUOTE_DATE,
        )


async def test_price_history_hides_other_private_points(
    session: AsyncSession,
) -> None:
    owner = await _make_user(session)
    other = await _make_user(session)
    private = await _make_point(session, "PRIVATE", owner=owner)
    version = await _make_version(session, owner)
    await _add_quote(session, version, private, "3600")

    series = await get_price_history(
        session,
        user_id=other.id,
        point_ids=[private.id],
        start_date=QUOTE_DATE - timedelta(days=7),
        end_date=QUOTE_DATE,
    )

    assert series == []


async def test_get_inventory_filters_and_paginates(session: AsyncSession) -> None:
    owner = await _make_user(session)
    version = await _make_version(session, owner, dataset_type=DatasetType.INVENTORY)
    snapshot = InventorySnapshot(
        version_id=version.id,
        snapshot_date=QUOTE_DATE,
        warehouse="昆明宝象库",
        source_file="10.23.xlsx",
    )
    session.add(snapshot)
    await session.flush()
    session.add_all(
        [
            InventoryItem(
                snapshot_id=snapshot.id,
                block="方管",
                spec="100*100*2.5*6m",
                unit_price=Decimal("3550"),
                pieces=230,
                total_weight=Decimal("5.662"),
                price_per_piece=Decimal("88.5"),
                manufacturer="正大",
                row_no=4,
            ),
            InventoryItem(
                snapshot_id=snapshot.id,
                block="矩形管",
                spec="100*150*2.5*6m",
                unit_price=Decimal("3320"),
                pieces=128,
                total_weight=Decimal("6.884"),
                price_per_piece=Decimal("180.81"),
                manufacturer="汇丰",
                row_no=5,
            ),
        ]
    )
    await session.flush()

    page = await get_inventory(session, page=1, page_size=20)
    assert page.snapshot_date == QUOTE_DATE
    assert page.warehouse == "昆明宝象库"
    assert page.total == 2

    filtered = await get_inventory(session, category="方管")
    assert filtered.total == 1
    assert filtered.items[0].spec == "100*100*2.5*6m"

    paged = await get_inventory(session, page=2, page_size=1)
    assert paged.total == 2
    assert len(paged.items) == 1

    found = await find_inventory_item(session, spec="100×150×2.5×6m")
    assert found is not None
    assert found.spec == "100*150*2.5*6m"
    assert found.unit_price == Decimal("3320")


async def test_get_inventory_without_snapshot(session: AsyncSession) -> None:
    page = await get_inventory(session)

    assert page.snapshot_date is None
    assert page.items == []
    assert page.total == 0
