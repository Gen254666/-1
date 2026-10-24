import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.providers import AllProvidersFailed
from app.report.service import generate_and_save_report
from steel_core.db.enums import DatasetType, PointScope, Role
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import AppConfig
from steel_core.db.models.inventory import InventoryItem, InventorySnapshot
from steel_core.db.models.market import MarketQuote, PricePoint
from steel_core.security import hash_password
from steel_core.versioning.service import create_import_batch, create_version

pytestmark = pytest.mark.integration

TODAY = date(2026, 10, 23)


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        return "# 今日行情\n方管价格稳定。"


async def _seed(session: AsyncSession) -> User:
    user = User(
        username=f"user-{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("secret-123"),
        role=Role.USER,
    )
    session.add(user)
    await session.flush()

    point = PricePoint(
        scope=PointScope.PUBLIC,
        code="P1",
        category="方管",
        spec="100*100*2.5*6m",
        region="昆明",
        source="mysteel",
        unit="元/吨",
    )
    session.add(point)
    await session.flush()

    batch = await create_import_batch(
        session,
        user_id=user.id,
        dataset_type=DatasetType.MARKET_QUOTE,
        effective_date=TODAY,
        file_name="quotes.csv",
        file_hash=uuid.uuid4().hex,
        rows_total=1,
        rows_ok=1,
        rows_failed=0,
    )
    version = await create_version(
        session,
        dataset_type=DatasetType.MARKET_QUOTE,
        effective_date=TODAY,
        checksum=uuid.uuid4().hex,
        import_batch_id=batch.id,
    )
    session.add(
        MarketQuote(
            version_id=version.id,
            point_id=point.id,
            quote_date=TODAY,
            price=Decimal("3550"),
            source="mysteel",
        )
    )
    private = PricePoint(
        scope=PointScope.PRIVATE,
        owner_user_id=user.id,
        code="PRIVATE",
        category="方管",
        spec="100*100*2.5*6m",
        region="昆明",
        source="manual",
        unit="元/吨",
    )
    session.add(private)
    await session.flush()
    session.add(
        MarketQuote(
            version_id=version.id,
            point_id=private.id,
            quote_date=TODAY,
            price=Decimal("9999"),
            source="manual",
        )
    )

    inventory_batch = await create_import_batch(
        session,
        user_id=user.id,
        dataset_type=DatasetType.INVENTORY,
        effective_date=TODAY,
        file_name="inventory.xlsx",
        file_hash=uuid.uuid4().hex,
        rows_total=1,
        rows_ok=1,
        rows_failed=0,
    )
    inventory_version = await create_version(
        session,
        dataset_type=DatasetType.INVENTORY,
        effective_date=TODAY,
        checksum=uuid.uuid4().hex,
        import_batch_id=inventory_batch.id,
    )
    snapshot = InventorySnapshot(
        version_id=inventory_version.id,
        snapshot_date=TODAY,
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
            weight_per_piece=Decimal("24.93"),
            pieces=100,
            total_weight=Decimal("2.493"),
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
    await session.commit()
    return user


async def test_generate_and_save_report(session: AsyncSession) -> None:
    user = await _seed(session)
    llm = FakeLLM()

    report = await generate_and_save_report(session, llm=llm, user_id=user.id, report_date=TODAY)

    assert report.report_date == TODAY
    assert report.version_no == 1
    assert report.markdown.startswith("# 今日行情")
    assert report.disclaimer == "报告免责"
    assert llm.calls == 1
    assert all(source.get("code") != "PRIVATE" for source in report.sources)

    second = await generate_and_save_report(session, llm=llm, user_id=user.id, report_date=TODAY)
    assert second.version_no == 2


async def test_generate_report_falls_back_to_facts(session: AsyncSession) -> None:
    user = await _seed(session)

    class FailingLLM:
        async def complete(self, messages: list[dict[str, str]]) -> str:
            raise AllProvidersFailed("all down")

    report = await generate_and_save_report(
        session, llm=FailingLLM(), user_id=user.id, report_date=TODAY
    )

    assert report.model == "facts-only"
    assert "事实稿" in report.markdown
    assert "3550" in report.markdown
    assert report.disclaimer == "报告免责"
