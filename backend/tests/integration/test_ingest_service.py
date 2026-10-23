import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import DatasetType, ImportStatus, PointScope, Role, VersionStatus
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import AuditLog, DatasetVersion, ImportBatch
from steel_core.db.models.inventory import InventoryItem, InventorySnapshot
from steel_core.db.models.market import MarketQuote, PricePoint
from steel_core.ingest.service import (
    ImportValidationError,
    import_inventory,
    import_quotes,
)
from tests.unit.test_core.test_inventory_parser import _build_workbook

pytestmark = pytest.mark.integration

EFFECTIVE_DATE = date(2026, 10, 23)


async def _make_user(session: AsyncSession) -> User:
    user = User(
        username=f"user-{uuid.uuid4().hex[:8]}",
        password_hash="not-used",
        role=Role.USER,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_point(session: AsyncSession, code: str) -> PricePoint:
    point = PricePoint(
        scope=PointScope.PUBLIC,
        code=code,
        category="方管",
        spec="100*100*2.5*6m",
        region="昆明",
        source="mysteel",
        unit="元/吨",
    )
    session.add(point)
    await session.flush()
    return point


def _write_quotes(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


async def _count(session: AsyncSession, model: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_import_quotes_creates_version_and_quotes(
    session: AsyncSession, tmp_path: Path
) -> None:
    user = await _make_user(session)
    first = await _make_point(session, "P1")
    second = await _make_point(session, "P2")
    path = tmp_path / "quotes.csv"
    _write_quotes(
        path,
        "point_id,date,price,change,source,note\n"
        "P1,2026-10-23,3550,10,mysteel,ok\n"
        "P2,2026-10-23,3480,-10,mysteel,\n",
    )

    outcome = await import_quotes(
        session,
        user_id=user.id,
        path=path,
        allowed_points={"P1": first.id, "P2": second.id},
        expected_point_codes={"P1", "P2"},
    )

    assert not outcome.no_changes
    assert outcome.version_id is not None
    assert outcome.rows_ok == 2
    assert await _count(session, MarketQuote) == 2

    version = await session.get(DatasetVersion, outcome.version_id)
    assert version is not None
    assert version.status == VersionStatus.ACTIVE

    batch = await session.get(ImportBatch, outcome.batch_id)
    assert batch is not None
    assert batch.status == ImportStatus.SUCCESS
    assert batch.dataset_type == DatasetType.MARKET_QUOTE

    audit_count = await session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "import.market_quote")
    )
    assert audit_count == 1


async def test_import_quotes_is_idempotent(session: AsyncSession, tmp_path: Path) -> None:
    user = await _make_user(session)
    point = await _make_point(session, "P1")
    path = tmp_path / "quotes.csv"
    _write_quotes(
        path,
        "point_id,date,price,change,source,note\nP1,2026-10-23,3550,,mysteel,\n",
    )

    first = await import_quotes(
        session,
        user_id=user.id,
        path=path,
        allowed_points={"P1": point.id},
    )
    second = await import_quotes(
        session,
        user_id=user.id,
        path=path,
        allowed_points={"P1": point.id},
    )

    assert not first.no_changes
    assert second.no_changes
    assert await _count(session, DatasetVersion) == 1
    assert await _count(session, MarketQuote) == 1


async def test_invalid_quotes_record_failed_batch_and_rollback(
    session: AsyncSession, tmp_path: Path
) -> None:
    user = await _make_user(session)
    point = await _make_point(session, "P1")
    path = tmp_path / "quotes.csv"
    _write_quotes(
        path,
        "point_id,date,price,change,source,note\nP1,2026-10-23,0,,mysteel,\n",
    )

    with pytest.raises(ImportValidationError) as exc_info:
        await import_quotes(
            session,
            user_id=user.id,
            path=path,
            allowed_points={"P1": point.id},
        )

    error = exc_info.value
    assert error.batch_id is not None
    batch = await session.get(ImportBatch, error.batch_id)
    assert batch is not None
    assert batch.status == ImportStatus.FAILED
    assert batch.rows_failed == 1

    assert await _count(session, DatasetVersion) == 0
    assert await _count(session, MarketQuote) == 0


async def test_import_inventory_creates_snapshot_and_items(
    session: AsyncSession, tmp_path: Path
) -> None:
    user = await _make_user(session)
    path = tmp_path / "10.23库存状况表.xlsx"
    _build_workbook(path, invalid_row=False)

    outcome = await import_inventory(
        session,
        user_id=user.id,
        path=path,
        explicit_date=EFFECTIVE_DATE,
    )

    assert not outcome.no_changes
    assert outcome.version_id is not None
    assert outcome.rows_ok == 4
    assert await _count(session, InventorySnapshot) == 1
    assert await _count(session, InventoryItem) == 4

    snapshot = await session.scalar(select(InventorySnapshot))
    assert snapshot is not None
    assert snapshot.snapshot_date == EFFECTIVE_DATE
    assert snapshot.warehouse == "昆明宝象库"
    assert snapshot.version_id == outcome.version_id


async def test_invalid_inventory_records_failed_batch(
    session: AsyncSession, tmp_path: Path
) -> None:
    user = await _make_user(session)
    path = tmp_path / "10.23库存状况表.xlsx"
    _build_workbook(path)

    with pytest.raises(ImportValidationError) as exc_info:
        await import_inventory(
            session,
            user_id=user.id,
            path=path,
            explicit_date=EFFECTIVE_DATE,
        )

    assert exc_info.value.batch_id is not None
    assert await _count(session, InventorySnapshot) == 0
    assert await _count(session, DatasetVersion) == 0
