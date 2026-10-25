from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import DatasetType, PointScope
from steel_core.db.models.governance import DatasetVersion
from steel_core.db.models.market import MarketQuote, PricePoint
from steel_core.ingest.derivation import sync_inventory_derivation
from steel_core.ingest.inventory import InventoryRow
from steel_core.ingest.service import ImportValidationError, import_inventory
from steel_core.versioning.service import get_active_version
from tests.integration.test_ingest_service import _make_user
from tests.unit.test_core.test_inventory_parser import _build_workbook

DATE = date(2026, 10, 25)


def _row(block: str, spec: str, price: str | None, pieces: int | None) -> InventoryRow:
    return InventoryRow(
        block=block,
        spec=spec,
        unit_price=None if price is None else Decimal(price),
        tax_add=Decimal("220"),
        weight_per_piece=Decimal("24.93"),
        pieces=pieces,
        total_weight=None,
        price_per_piece=None,
        packaging=None,
        manufacturer=None,
        row_no=1,
    )


async def _count(session: AsyncSession, model: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_inventory_import_derives_points_and_quotes(
    session: AsyncSession, tmp_path: Path
) -> None:
    user = await _make_user(session)
    path = tmp_path / "10.25库存状况表.xlsx"
    _build_workbook(path, invalid_row=False)

    out = await import_inventory(session, user_id=user.id, path=path, explicit_date=DATE)

    assert out.derived_points_created == 4
    assert out.derived_quotes == 4
    assert await _count(session, PricePoint) == 4
    assert await _count(session, MarketQuote) == 4
    point = await session.scalar(
        select(PricePoint).where(PricePoint.code == "FANG_100X100X2.5X6M_KUNMING")
    )
    assert point is not None
    assert point.scope == PointScope.PUBLIC
    assert point.source == "inventory"
    quote = await session.scalar(select(MarketQuote).where(MarketQuote.point_id == point.id))
    assert quote is not None
    assert quote.price == Decimal("3550")
    assert quote.source == "inventory"
    assert quote.change is None


async def test_duplicate_conflicting_price_warns_and_uses_max_pieces(
    session: AsyncSession,
) -> None:
    user = await _make_user(session)
    rows = [
        _row("方管", "120*120*3.75*6m", "3320", 2),
        _row("方管", "120*120*3.75*6m", "3300", 268),
    ]

    out = await sync_inventory_derivation(
        session,
        user_id=user.id,
        effective_date=DATE,
        warehouse="昆明宝象库",
        rows=rows,
        source_file="10.25库存状况表.xlsx",
    )
    await session.commit()

    assert out.points_created == 1
    assert out.quotes_written == 1
    assert any("单价" in warning.message for warning in out.warnings)
    quote = await session.scalar(select(MarketQuote))
    assert quote is not None
    assert quote.price == Decimal("3300")


async def test_reimport_is_idempotent_and_still_derives(
    session: AsyncSession, tmp_path: Path
) -> None:
    user = await _make_user(session)
    path = tmp_path / "10.25库存状况表.xlsx"
    _build_workbook(path, invalid_row=False)
    await import_inventory(session, user_id=user.id, path=path, explicit_date=DATE)

    out = await import_inventory(session, user_id=user.id, path=path, explicit_date=DATE)

    assert out.no_changes is True
    assert out.derived_quote_no_changes is True
    versions = await session.scalars(
        select(DatasetVersion).where(DatasetVersion.dataset_type == DatasetType.MARKET_QUOTE)
    )
    assert len(list(versions)) == 1


async def test_missing_price_creates_point_but_no_quote(session: AsyncSession) -> None:
    user = await _make_user(session)
    rows = [
        _row("方管", "100*100*2.5*6m", "3550", 230),
        _row("方管", "100*100*3.0*6m", None, 100),
        _row("矩形管", "100*150*2.5*6m", "3320", 128),
        _row("矩形管", "100*150*3.0*6m", "3320", 120),
    ]

    out = await sync_inventory_derivation(
        session,
        user_id=user.id,
        effective_date=DATE,
        warehouse="昆明宝象库",
        rows=rows,
        source_file="10.25库存状况表.xlsx",
    )
    await session.commit()

    assert out.points_created == 4
    assert out.quotes_written == 3
    assert any("单价" in warning.message for warning in out.warnings)


async def test_deactivation_guard_skips_mass_deactivate(session: AsyncSession) -> None:
    user = await _make_user(session)
    for index in range(25):
        session.add(
            PricePoint(
                scope=PointScope.PUBLIC,
                code=f"OLD_{index}",
                category="方管",
                spec=f"{index}*100*2.5*6m",
                region="昆明",
                source="inventory",
            )
        )
    await session.commit()

    out = await sync_inventory_derivation(
        session,
        user_id=user.id,
        effective_date=DATE,
        warehouse="昆明宝象库",
        rows=[_row("方管", "100*100*2.5*6m", "3550", 230)],
        source_file="10.25库存状况表.xlsx",
    )
    await session.commit()

    assert out.points_deactivated == 0
    assert any("停用" in warning.message for warning in out.warnings)
    assert await _count(session, PricePoint) == 26


async def _active_quote_count(session: AsyncSession) -> int:
    version = await get_active_version(session, DatasetType.MARKET_QUOTE, DATE)
    if version is None:
        return 0
    return int(
        await session.scalar(
            select(func.count())
            .select_from(MarketQuote)
            .where(MarketQuote.version_id == version.id)
        )
        or 0
    )


async def test_truncated_inventory_preserves_quotes_unless_forced(
    session: AsyncSession,
) -> None:
    user = await _make_user(session)
    full_rows = [
        _row("方管", f"{100 + index}*100*2.5*6m", str(3500 + index), 100)
        for index in range(16)
    ]
    first = await sync_inventory_derivation(
        session,
        user_id=user.id,
        effective_date=DATE,
        warehouse="昆明宝象库",
        rows=full_rows,
        source_file="full.xlsx",
    )
    await session.commit()
    assert first.quotes_written == 16
    assert await _active_quote_count(session) == 16

    truncated = await sync_inventory_derivation(
        session,
        user_id=user.id,
        effective_date=DATE,
        warehouse="昆明宝象库",
        rows=full_rows[:1],
        source_file="truncated.xlsx",
    )
    await session.commit()

    assert truncated.points_deactivated == 0
    assert truncated.quotes_written == 0
    assert truncated.quote_no_changes is True
    assert any("跳过" in warning.message for warning in truncated.warnings)
    assert await _active_quote_count(session) == 16

    forced = await sync_inventory_derivation(
        session,
        user_id=user.id,
        effective_date=DATE,
        warehouse="昆明宝象库",
        rows=full_rows[:1],
        source_file="truncated.xlsx",
        force=True,
    )
    await session.commit()

    assert forced.points_deactivated == 15
    assert forced.quotes_written == 1
    assert await _active_quote_count(session) == 1


async def test_historical_inventory_import_is_rejected(
    session: AsyncSession, tmp_path: Path
) -> None:
    user = await _make_user(session)
    path = tmp_path / "10.25库存状况表.xlsx"
    _build_workbook(path, invalid_row=False)
    await import_inventory(session, user_id=user.id, path=path, explicit_date=DATE)

    with pytest.raises(ImportValidationError) as exc_info:
        await import_inventory(
            session,
            user_id=user.id,
            path=path,
            explicit_date=DATE - timedelta(days=1),
        )

    assert any("早于" in error.message for error in exc_info.value.errors)
