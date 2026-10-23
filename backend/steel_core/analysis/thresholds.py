from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.models.governance import AppConfig


class ThresholdValidationError(Exception):
    pass


@dataclass(frozen=True)
class AnomalyThresholds:
    daily_change_pct: Decimal
    consecutive_days: int
    inventory_deviation_pct: Decimal
    low_stock_pieces: int


DEFAULT_THRESHOLDS = AnomalyThresholds(
    daily_change_pct=Decimal("2"),
    consecutive_days=3,
    inventory_deviation_pct=Decimal("30"),
    low_stock_pieces=10,
)


def parse_thresholds(value: dict[str, Any] | None) -> AnomalyThresholds:
    if value is None:
        return DEFAULT_THRESHOLDS

    daily_change_pct = _as_decimal(
        value.get("daily_change_pct", DEFAULT_THRESHOLDS.daily_change_pct),
        "daily_change_pct",
    )
    if daily_change_pct <= 0:
        msg = "daily_change_pct 必须大于 0"
        raise ThresholdValidationError(msg)

    consecutive_days = _as_int(
        value.get("consecutive_days", DEFAULT_THRESHOLDS.consecutive_days),
        "consecutive_days",
    )
    if consecutive_days < 1:
        msg = "consecutive_days 必须大于等于 1"
        raise ThresholdValidationError(msg)

    inventory_deviation_pct = _as_decimal(
        value.get("inventory_deviation_pct", DEFAULT_THRESHOLDS.inventory_deviation_pct),
        "inventory_deviation_pct",
    )
    if inventory_deviation_pct < 0:
        msg = "inventory_deviation_pct 不能小于 0"
        raise ThresholdValidationError(msg)

    low_stock_pieces = _as_int(
        value.get("low_stock_pieces", DEFAULT_THRESHOLDS.low_stock_pieces),
        "low_stock_pieces",
    )
    if low_stock_pieces < 0:
        msg = "low_stock_pieces 不能小于 0"
        raise ThresholdValidationError(msg)

    return AnomalyThresholds(
        daily_change_pct=daily_change_pct,
        consecutive_days=consecutive_days,
        inventory_deviation_pct=inventory_deviation_pct,
        low_stock_pieces=low_stock_pieces,
    )


async def load_thresholds(session: AsyncSession) -> AnomalyThresholds:
    config = await session.scalar(select(AppConfig).where(AppConfig.key == "anomaly"))
    return parse_thresholds(config.value if config is not None else None)


def _as_decimal(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        msg = f"{field_name} 不是合法数字: {value!r}"
        raise ThresholdValidationError(msg) from exc


def _as_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        msg = f"{field_name} 不是合法整数: {value!r}"
        raise ThresholdValidationError(msg) from exc
