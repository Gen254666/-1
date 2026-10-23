from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

MONEY = Decimal("0.01")
WEIGHT = Decimal("0.0001")


class QuoteValidationError(Exception):
    pass


@dataclass(frozen=True)
class QuoteLine:
    spec: str
    unit_price: Decimal
    tax_add: Decimal | None
    weight_per_piece: Decimal
    pieces: int
    price_per_piece: Decimal
    subtotal: Decimal
    ton_price: Decimal


@dataclass
class QuoteCalculation:
    lines: list[QuoteLine]
    freight: Decimal
    processing_fee: Decimal
    total: Decimal
    total_weight: Decimal
    average_ton_price: Decimal
    tax_mode: str
    warnings: list[str] = field(default_factory=list)


def calculate_quote(
    *,
    spec: str,
    unit_price: Decimal,
    weight_per_piece: Decimal,
    pieces: int,
    tax_add: Decimal | None = None,
    freight: Decimal = Decimal("0"),
    processing_fee: Decimal = Decimal("0"),
    tax_mode: str = "as_is",
) -> QuoteCalculation:
    if unit_price <= 0:
        msg = "unit_price 必须大于 0"
        raise QuoteValidationError(msg)
    if weight_per_piece <= 0:
        msg = "weight_per_piece 必须大于 0"
        raise QuoteValidationError(msg)
    if pieces <= 0:
        msg = "pieces 必须大于 0"
        raise QuoteValidationError(msg)
    if freight < 0 or processing_fee < 0:
        msg = "运费和加工费不能为负数"
        raise QuoteValidationError(msg)
    if tax_mode not in {"as_is", "add_tax"}:
        msg = f"不支持的含税口径: {tax_mode}"
        raise QuoteValidationError(msg)
    if tax_mode == "add_tax" and tax_add is None:
        msg = "add_tax 口径需要提供 tax_add"
        raise QuoteValidationError(msg)

    ton_price = unit_price + (tax_add or Decimal("0")) if tax_mode == "add_tax" else unit_price
    price_per_piece = (unit_price * weight_per_piece / Decimal("1000")).quantize(
        MONEY, rounding=ROUND_HALF_UP
    )
    subtotal = (price_per_piece * pieces).quantize(MONEY, rounding=ROUND_HALF_UP)
    total = (subtotal + freight + processing_fee).quantize(MONEY, rounding=ROUND_HALF_UP)
    total_weight = (weight_per_piece * pieces / Decimal("1000")).quantize(WEIGHT)

    warnings: list[str] = []
    if tax_mode == "as_is":
        warnings.append("含税口径沿用库存表单价，待业务确认")

    return QuoteCalculation(
        lines=[
            QuoteLine(
                spec=spec,
                unit_price=unit_price,
                tax_add=tax_add,
                weight_per_piece=weight_per_piece,
                pieces=pieces,
                price_per_piece=price_per_piece,
                subtotal=subtotal,
                ton_price=ton_price,
            )
        ],
        freight=freight,
        processing_fee=processing_fee,
        total=total,
        total_weight=total_weight,
        average_ton_price=ton_price,
        tax_mode=tax_mode,
        warnings=warnings,
    )
