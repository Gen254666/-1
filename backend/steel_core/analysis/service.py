from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.analysis.thresholds import AnomalyThresholds, load_thresholds
from steel_core.db.enums import DatasetType, VersionStatus
from steel_core.db.models.governance import DatasetVersion
from steel_core.db.models.inventory import InventoryItem, InventorySnapshot
from steel_core.db.models.market import MarketQuote, PricePoint
from steel_core.query.service import (
    get_inventory,
    get_price_history,
    get_quotes,
    version_visibility,
    visible_clause,
)


@dataclass(frozen=True)
class SpreadPoint:
    quote_date: date
    value: Decimal


@dataclass
class SpreadSeries:
    left_point_id: UUID
    right_point_id: UUID
    left_code: str
    right_code: str
    points: list[SpreadPoint]
    latest: Decimal
    minimum: Decimal
    maximum: Decimal
    average: Decimal


@dataclass(frozen=True)
class Anomaly:
    kind: str
    name: str
    value: Decimal
    threshold: Decimal
    message: str
    point_id: UUID | None = None
    spec: str | None = None


async def calculate_spread(
    session: AsyncSession,
    *,
    user_id: UUID,
    left_point_id: UUID,
    right_point_id: UUID,
    start_date: date,
    end_date: date,
) -> SpreadSeries | None:
    history = await get_price_history(
        session,
        user_id=user_id,
        point_ids=[left_point_id, right_point_id],
        start_date=start_date,
        end_date=end_date,
    )
    by_id = {series.point_id: series for series in history}
    left = by_id.get(left_point_id)
    right = by_id.get(right_point_id)
    if left is None or right is None:
        return None

    right_prices = {point.quote_date: point.price for point in right.points}
    points = [
        SpreadPoint(quote_date=point.quote_date, value=point.price - right_prices[point.quote_date])
        for point in left.points
        if point.quote_date in right_prices
    ]
    if not points:
        return None

    values = [point.value for point in points]
    return SpreadSeries(
        left_point_id=left_point_id,
        right_point_id=right_point_id,
        left_code=left.code,
        right_code=right.code,
        points=points,
        latest=values[-1],
        minimum=min(values),
        maximum=max(values),
        average=sum(values, Decimal("0")) / Decimal(len(values)),
    )


async def scan_anomalies(
    session: AsyncSession,
    *,
    user_id: UUID,
    quote_date: date | None = None,
    category: str | None = None,
) -> list[Anomaly]:
    thresholds = await load_thresholds(session)
    anomalies: list[Anomaly] = []

    quotes = await _load_all_quotes(
        session, user_id=user_id, quote_date=quote_date, category=category
    )
    effective_date = quotes[0].quote_date if quotes else quote_date

    if effective_date is not None and quotes:
        recent_prices = await _recent_prices_batch(
            session,
            user_id=user_id,
            point_ids=[quote.point_id for quote in quotes],
            end_date=effective_date,
            limit=thresholds.consecutive_days + 1,
        )
        for quote in quotes:
            prices = recent_prices.get(quote.point_id, [])
            name = f"{quote.category} {quote.spec} {quote.region}"
            anomalies.extend(_price_anomalies(quote.point_id, name, prices, thresholds))

    snapshot_date, _, inventory_items = await _all_inventory_items(session, category=category)
    if snapshot_date is not None:
        specs = {item.spec for item in inventory_items if item.pieces is not None}
        inventory_history = await _inventory_history_batch(
            session, specs=specs, snapshot_date=snapshot_date
        )
        for item in inventory_items:
            if item.pieces is None:
                continue
            name = f"{item.block} {item.spec}"
            if item.pieces < thresholds.low_stock_pieces:
                anomalies.append(
                    Anomaly(
                        kind="low_stock",
                        name=name,
                        value=Decimal(item.pieces),
                        threshold=Decimal(thresholds.low_stock_pieces),
                        message=(
                            f"{name} 库存 {item.pieces} 支，低于阈值 "
                            f"{thresholds.low_stock_pieces} 支"
                        ),
                        spec=item.spec,
                    )
                )

            deviation = _deviation_from_history(
                item.pieces,
                inventory_history.get(item.spec, []),
                snapshot_date,
            )
            if deviation is not None and deviation >= thresholds.inventory_deviation_pct:
                anomalies.append(
                    Anomaly(
                        kind="inventory_deviation",
                        name=name,
                        value=deviation,
                        threshold=thresholds.inventory_deviation_pct,
                        message=(
                            f"{name} 库存较近 7 日均值偏离 {deviation:.2f}%，"
                            f"超过阈值 {thresholds.inventory_deviation_pct}%"
                        ),
                        spec=item.spec,
                    )
                )

    return anomalies


async def _all_inventory_items(
    session: AsyncSession, *, category: str | None
) -> tuple[date | None, str | None, list[Any]]:
    page = 1
    items: list[Any] = []
    snapshot_date: date | None = None
    warehouse: str | None = None
    while True:
        page_result = await get_inventory(session, category=category, page=page, page_size=100)
        if snapshot_date is None:
            snapshot_date = page_result.snapshot_date
            warehouse = page_result.warehouse
        items.extend(page_result.items)
        if len(items) >= page_result.total or not page_result.items:
            return snapshot_date, warehouse, items
        page += 1


async def _load_all_quotes(
    session: AsyncSession,
    *,
    user_id: UUID,
    quote_date: date | None,
    category: str | None,
) -> list[Any]:
    items: list[Any] = []
    page = 1
    while True:
        result = await get_quotes(
            session,
            user_id=user_id,
            quote_date=quote_date,
            category=category,
            page=page,
            page_size=100,
        )
        items.extend(result.items)
        if len(items) >= result.total or not result.items:
            break
        page += 1
    return items


async def _recent_prices_batch(
    session: AsyncSession,
    *,
    user_id: UUID,
    point_ids: list[UUID],
    end_date: date,
    limit: int,
) -> dict[UUID, list[Decimal]]:
    if not point_ids:
        return {}
    row_number = (
        func.row_number()
        .over(
            partition_by=MarketQuote.point_id,
            order_by=MarketQuote.quote_date.desc(),
        )
        .label("row_number")
    )
    ranked = (
        select(
            MarketQuote.point_id.label("point_id"),
            MarketQuote.quote_date.label("quote_date"),
            MarketQuote.price.label("price"),
            row_number,
        )
        .join(DatasetVersion, MarketQuote.version_id == DatasetVersion.id)
        .join(PricePoint, MarketQuote.point_id == PricePoint.id)
        .where(
            DatasetVersion.status == VersionStatus.ACTIVE,
            visible_clause(user_id),
            version_visibility(user_id),
            PricePoint.is_active.is_(True),
            MarketQuote.point_id.in_(point_ids),
            MarketQuote.quote_date <= end_date,
        )
        .subquery()
    )
    rows: Any = (
        await session.execute(
            select(ranked.c.point_id, ranked.c.quote_date, ranked.c.price)
            .where(ranked.c.row_number <= limit)
            .order_by(ranked.c.point_id, ranked.c.quote_date)
        )
    ).all()
    prices: dict[UUID, list[Decimal]] = {}
    for point_id, _, price in rows:
        prices.setdefault(point_id, []).append(price)
    return prices


def _price_anomalies(
    point_id: UUID,
    name: str,
    prices: list[Decimal],
    thresholds: AnomalyThresholds,
) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    if len(prices) < 2:
        return anomalies

    previous, current = prices[-2], prices[-1]
    if previous != 0:
        change_pct = abs((current - previous) / previous * Decimal("100"))
        if change_pct >= thresholds.daily_change_pct:
            anomalies.append(
                Anomaly(
                    kind="price_change",
                    name=name,
                    value=change_pct,
                    threshold=thresholds.daily_change_pct,
                    message=(
                        f"{name} 单日涨跌幅 {change_pct:.2f}%，"
                        f"超过阈值 {thresholds.daily_change_pct}%"
                    ),
                    point_id=point_id,
                )
            )

    changes = [prices[index + 1] - prices[index] for index in range(len(prices) - 1)][
        -thresholds.consecutive_days :
    ]
    if len(changes) == thresholds.consecutive_days and (
        all(change > 0 for change in changes) or all(change < 0 for change in changes)
    ):
        direction = "上涨" if changes[-1] > 0 else "下跌"
        anomalies.append(
            Anomaly(
                kind="consecutive",
                name=name,
                value=Decimal(len(changes)),
                threshold=Decimal(thresholds.consecutive_days),
                message=(
                    f"{name} 连续{direction} {len(changes)} 天，"
                    f"达到阈值 {thresholds.consecutive_days} 天"
                ),
                point_id=point_id,
            )
        )
    return anomalies


async def _inventory_history_batch(
    session: AsyncSession,
    *,
    specs: set[str],
    snapshot_date: date,
) -> dict[str, list[tuple[date, int | None]]]:
    if not specs:
        return {}
    statement = (
        select(
            InventoryItem.spec,
            InventorySnapshot.snapshot_date,
            func.sum(InventoryItem.pieces),
        )
        .join(InventorySnapshot, InventoryItem.snapshot_id == InventorySnapshot.id)
        .join(DatasetVersion, InventorySnapshot.version_id == DatasetVersion.id)
        .where(
            DatasetVersion.status == VersionStatus.ACTIVE,
            DatasetVersion.dataset_type == DatasetType.INVENTORY,
            InventorySnapshot.snapshot_date >= snapshot_date - timedelta(days=7),
            InventorySnapshot.snapshot_date <= snapshot_date,
            InventoryItem.spec.in_(specs),
        )
        .group_by(InventoryItem.spec, InventorySnapshot.snapshot_date)
    )
    rows: Any = (await session.execute(statement)).all()

    history: dict[str, list[tuple[date, int | None]]] = {}
    for spec, day, total in rows:
        history.setdefault(spec, []).append((day, total))
    return history


def _deviation_from_history(
    current_pieces: int,
    history: list[tuple[date, int | None]],
    snapshot_date: date,
) -> Decimal | None:
    previous_totals = [
        Decimal(total) for day, total in history if day < snapshot_date and total is not None
    ]
    if len(previous_totals) < 2:
        return None
    average = sum(previous_totals, Decimal("0")) / Decimal(len(previous_totals))
    if average == 0:
        return None
    return abs(Decimal(current_pieces) - average) / average * Decimal("100")
