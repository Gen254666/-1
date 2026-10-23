from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from steel_core.db.enums import DatasetType, PointScope, VersionStatus
from steel_core.db.models.governance import DatasetVersion
from steel_core.db.models.inventory import InventoryItem, InventorySnapshot
from steel_core.db.models.market import MarketQuote, PricePoint

MAX_PAGE_SIZE = 100
MAX_HISTORY_DAYS = 730
MAX_HISTORY_POINTS = 20


class QueryValidationError(Exception):
    pass


@dataclass(frozen=True)
class QuoteRecord:
    point_id: UUID
    code: str
    category: str
    spec: str
    region: str
    quote_date: date
    price: Decimal
    change: Decimal | None
    source: str


@dataclass
class QuotePage:
    items: list[QuoteRecord]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class HistoryPoint:
    quote_date: date
    price: Decimal


@dataclass
class HistorySeries:
    point_id: UUID
    code: str
    name: str
    points: list[HistoryPoint]
    latest: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    average: Decimal | None
    change: Decimal | None
    change_pct: Decimal | None


@dataclass(frozen=True)
class InventoryRecord:
    block: str
    spec: str
    unit_price: Decimal | None
    tax_add: Decimal | None
    weight_per_piece: Decimal | None
    pieces: int | None
    total_weight: Decimal | None
    price_per_piece: Decimal | None
    manufacturer: str | None
    row_no: int


@dataclass
class InventoryPage:
    snapshot_date: date | None
    warehouse: str | None
    items: list[InventoryRecord]
    total: int
    page: int
    page_size: int


def visible_clause(user_id: UUID) -> ColumnElement[bool]:
    return or_(PricePoint.scope == PointScope.PUBLIC, PricePoint.owner_user_id == user_id)


def _validate_pagination(page: int, page_size: int) -> None:
    if page < 1:
        msg = "page 必须大于等于 1"
        raise QueryValidationError(msg)
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        msg = f"page_size 必须在 1 到 {MAX_PAGE_SIZE} 之间"
        raise QueryValidationError(msg)


def _validate_history_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        msg = "start_date 不能晚于 end_date"
        raise QueryValidationError(msg)
    if (end_date - start_date).days > MAX_HISTORY_DAYS:
        msg = f"时间跨度不能超过 {MAX_HISTORY_DAYS} 天"
        raise QueryValidationError(msg)


def _active_quote_select() -> Any:
    return (
        select(MarketQuote, PricePoint)
        .join(DatasetVersion, MarketQuote.version_id == DatasetVersion.id)
        .join(PricePoint, MarketQuote.point_id == PricePoint.id)
        .where(DatasetVersion.status == VersionStatus.ACTIVE)
    )


async def list_points(
    session: AsyncSession,
    *,
    user_id: UUID,
    category: str | None = None,
    region: str | None = None,
) -> list[PricePoint]:
    statement = (
        select(PricePoint)
        .where(PricePoint.is_active.is_(True), visible_clause(user_id))
        .order_by(PricePoint.category, PricePoint.spec, PricePoint.region)
    )
    if category is not None:
        statement = statement.where(PricePoint.category == category)
    if region is not None:
        statement = statement.where(PricePoint.region == region)
    return list((await session.scalars(statement)).all())


async def get_quotes(
    session: AsyncSession,
    *,
    user_id: UUID,
    quote_date: date | None = None,
    category: str | None = None,
    region: str | None = None,
    point_ids: list[UUID] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> QuotePage:
    _validate_pagination(page, page_size)
    visibility = visible_clause(user_id)

    if quote_date is None:
        latest_statement = (
            select(func.max(MarketQuote.quote_date))
            .select_from(MarketQuote)
            .join(DatasetVersion, MarketQuote.version_id == DatasetVersion.id)
            .join(PricePoint, MarketQuote.point_id == PricePoint.id)
            .where(DatasetVersion.status == VersionStatus.ACTIVE, visibility)
        )
        quote_date = await session.scalar(latest_statement)
        if quote_date is None:
            return QuotePage(items=[], total=0, page=page, page_size=page_size)

    conditions: list[Any] = [
        DatasetVersion.status == VersionStatus.ACTIVE,
        visibility,
        MarketQuote.quote_date == quote_date,
    ]
    if category is not None:
        conditions.append(PricePoint.category == category)
    if region is not None:
        conditions.append(PricePoint.region == region)
    if point_ids:
        conditions.append(MarketQuote.point_id.in_(point_ids))

    total = int(
        await session.scalar(
            select(func.count())
            .select_from(MarketQuote)
            .join(DatasetVersion, MarketQuote.version_id == DatasetVersion.id)
            .join(PricePoint, MarketQuote.point_id == PricePoint.id)
            .where(*conditions)
        )
        or 0
    )

    statement = (
        _active_quote_select()
        .where(*conditions)
        .order_by(PricePoint.category, PricePoint.spec, PricePoint.region, PricePoint.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows: Any = (await session.execute(statement)).all()
    items = [
        QuoteRecord(
            point_id=point.id,
            code=point.code,
            category=point.category,
            spec=point.spec,
            region=point.region,
            quote_date=quote.quote_date,
            price=quote.price,
            change=quote.change,
            source=quote.source,
        )
        for quote, point in rows
    ]
    return QuotePage(items=items, total=total, page=page, page_size=page_size)


async def get_price_history(
    session: AsyncSession,
    *,
    user_id: UUID,
    point_ids: list[UUID],
    start_date: date,
    end_date: date,
) -> list[HistorySeries]:
    _validate_history_range(start_date, end_date)
    if not point_ids or len(point_ids) > MAX_HISTORY_POINTS:
        msg = f"point_ids 数量必须在 1 到 {MAX_HISTORY_POINTS} 之间"
        raise QueryValidationError(msg)

    statement = (
        _active_quote_select()
        .where(
            visible_clause(user_id),
            MarketQuote.point_id.in_(point_ids),
            MarketQuote.quote_date >= start_date,
            MarketQuote.quote_date <= end_date,
        )
        .order_by(MarketQuote.point_id, MarketQuote.quote_date)
    )
    rows: Any = (await session.execute(statement)).all()

    grouped: dict[UUID, tuple[PricePoint, list[HistoryPoint]]] = {}
    for quote, point in rows:
        _, points = grouped.setdefault(point.id, (point, []))
        points.append(HistoryPoint(quote_date=quote.quote_date, price=quote.price))

    series: list[HistorySeries] = []
    for point, points in grouped.values():
        prices = [item.price for item in points]
        first = prices[0]
        latest = prices[-1]
        change = latest - first
        change_pct = (change / first * Decimal("100")) if first != 0 else None
        series.append(
            HistorySeries(
                point_id=point.id,
                code=point.code,
                name=f"{point.category} {point.spec} {point.region}",
                points=points,
                latest=latest,
                minimum=min(prices),
                maximum=max(prices),
                average=sum(prices, Decimal("0")) / Decimal(len(prices)),
                change=change,
                change_pct=change_pct,
            )
        )

    return series


async def get_inventory(
    session: AsyncSession,
    *,
    snapshot_date: date | None = None,
    category: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> InventoryPage:
    _validate_pagination(page, page_size)

    if snapshot_date is None:
        snapshot_date = await session.scalar(
            select(func.max(InventorySnapshot.snapshot_date))
            .join(DatasetVersion, InventorySnapshot.version_id == DatasetVersion.id)
            .where(
                DatasetVersion.status == VersionStatus.ACTIVE,
                DatasetVersion.dataset_type == DatasetType.INVENTORY,
            )
        )
        if snapshot_date is None:
            return InventoryPage(
                snapshot_date=None,
                warehouse=None,
                items=[],
                total=0,
                page=page,
                page_size=page_size,
            )

    snapshot = await session.scalar(
        select(InventorySnapshot)
        .join(DatasetVersion, InventorySnapshot.version_id == DatasetVersion.id)
        .where(
            DatasetVersion.status == VersionStatus.ACTIVE,
            DatasetVersion.dataset_type == DatasetType.INVENTORY,
            InventorySnapshot.snapshot_date == snapshot_date,
        )
        .limit(1)
    )
    if snapshot is None:
        return InventoryPage(
            snapshot_date=None,
            warehouse=None,
            items=[],
            total=0,
            page=page,
            page_size=page_size,
        )

    conditions: list[Any] = [InventoryItem.snapshot_id == snapshot.id]
    if category is not None:
        conditions.append(InventoryItem.block == category)

    total = int(
        await session.scalar(select(func.count()).select_from(InventoryItem).where(*conditions))
        or 0
    )
    items = list(
        (
            await session.scalars(
                select(InventoryItem)
                .where(*conditions)
                .order_by(InventoryItem.row_no)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )

    return InventoryPage(
        snapshot_date=snapshot.snapshot_date,
        warehouse=snapshot.warehouse,
        items=[
            InventoryRecord(
                block=item.block,
                spec=item.spec,
                unit_price=item.unit_price,
                tax_add=item.tax_add,
                weight_per_piece=item.weight_per_piece,
                pieces=item.pieces,
                total_weight=item.total_weight,
                price_per_piece=item.price_per_piece,
                manufacturer=item.manufacturer,
                row_no=item.row_no,
            )
            for item in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
