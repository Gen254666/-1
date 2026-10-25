import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import DatasetType, PointScope, Role
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import AppConfig, DatasetVersion
from steel_core.db.models.inventory import InventoryItem, InventorySnapshot
from steel_core.db.models.market import MarketQuote, PricePoint
from steel_core.report.facts import build_daily_report_facts
from steel_core.versioning.service import create_import_batch, create_version

pytestmark = pytest.mark.integration

REPORT_DATE = date(2026, 10, 23)
FANG_CODE = "FANG_100X100X2.5X6M_KUNMING"
JU_CODE = "JU_100X150X2.5X6M_KUNMING"


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
    session: AsyncSession, code: str, region: str, *, category: str, spec: str
) -> PricePoint:
    point = PricePoint(
        scope=PointScope.PUBLIC,
        owner_user_id=None,
        code=code,
        category=category,
        spec=spec,
        region=region,
        source="inventory",
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


async def test_build_daily_report_facts(session: AsyncSession) -> None:
    owner = await _make_user(session)
    fang = await _make_point(
        session, FANG_CODE, "昆明", category="方管", spec="100×100×2.5×6m"
    )
    ju = await _make_point(
        session, JU_CODE, "昆明", category="矩管", spec="100×150×2.5×6m"
    )

    for offset, fang_price, ju_price in [
        (1, "3500", "3400"),
        (0, "3550", "3480"),
    ]:
        quote_date = REPORT_DATE - timedelta(days=offset)
        version = await _make_version(session, owner, quote_date)
        await _add_quote(session, version, fang, quote_date, fang_price)
        await _add_quote(session, version, ju, quote_date, ju_price)

    inventory_version = await _make_version(
        session, owner, REPORT_DATE, dataset_type=DatasetType.INVENTORY
    )
    snapshot = InventorySnapshot(
        version_id=inventory_version.id,
        snapshot_date=REPORT_DATE,
        warehouse="昆明宝象库",
        source_file="10.23.xlsx",
    )
    session.add(snapshot)
    await session.flush()
    session.add(
        InventoryItem(
            snapshot_id=snapshot.id,
            block="方管",
            spec="100*100*2.5*6m",
            unit_price=Decimal("3550"),
            pieces=20,
            total_weight=Decimal("1.0"),
            price_per_piece=Decimal("88.5"),
            manufacturer="正大",
            row_no=4,
        )
    )
    session.add(
        AppConfig(
            key="disclaimer",
            value={"quote": "报价免责", "report": "报告免责"},
        )
    )
    await session.flush()

    facts = await build_daily_report_facts(session, user_id=owner.id, report_date=REPORT_DATE)

    assert facts.as_of == REPORT_DATE
    assert len(facts.quotes) == 2
    assert facts.inventory.snapshot_date == REPORT_DATE
    assert len(facts.spreads) == 1
    assert facts.spreads[0].latest == Decimal("70")
    assert facts.disclaimer == "报告免责"
    assert {source["code"] for source in facts.sources if source["type"] == "quote"} == {
        FANG_CODE,
        JU_CODE,
    }
    assert any(source["type"] == "inventory" for source in facts.sources)
