from decimal import Decimal
from typing import Any

import pytest

from steel_core.analysis.thresholds import (
    DEFAULT_THRESHOLDS,
    ThresholdValidationError,
    parse_thresholds,
)


def test_defaults_when_missing() -> None:
    assert parse_thresholds(None) == DEFAULT_THRESHOLDS


def test_partial_override_keeps_defaults() -> None:
    value: dict[str, Any] = {"daily_change_pct": 3, "low_stock_pieces": 5}

    thresholds = parse_thresholds(value)

    assert thresholds.daily_change_pct == Decimal("3")
    assert thresholds.low_stock_pieces == 5
    assert thresholds.consecutive_days == DEFAULT_THRESHOLDS.consecutive_days
    assert thresholds.inventory_deviation_pct == DEFAULT_THRESHOLDS.inventory_deviation_pct


@pytest.mark.parametrize(
    "value",
    [
        {"daily_change_pct": -1},
        {"consecutive_days": 0},
        {"inventory_deviation_pct": -5},
        {"low_stock_pieces": -1},
    ],
)
def test_invalid_values_raise(value: dict[str, Any]) -> None:
    with pytest.raises(ThresholdValidationError):
        parse_thresholds(value)
