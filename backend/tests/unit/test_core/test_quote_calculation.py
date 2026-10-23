from decimal import Decimal

import pytest

from steel_core.quote.service import QuoteValidationError, calculate_quote


def test_calculate_quote_as_is() -> None:
    result = calculate_quote(
        spec="100*100*2.5*6m",
        unit_price=Decimal("3550"),
        weight_per_piece=Decimal("24.93"),
        pieces=10,
        freight=Decimal("100"),
        processing_fee=Decimal("50"),
    )

    line = result.lines[0]
    assert line.price_per_piece == Decimal("88.50")
    assert line.subtotal == Decimal("885.00")
    assert result.total == Decimal("1035.00")
    assert result.total_weight == Decimal("0.2493")
    assert result.average_ton_price == Decimal("3550")
    assert any("含税" in warning for warning in result.warnings)


def test_calculate_quote_add_tax() -> None:
    result = calculate_quote(
        spec="100*100*2.5*6m",
        unit_price=Decimal("3550"),
        tax_add=Decimal("220"),
        weight_per_piece=Decimal("24.93"),
        pieces=10,
        tax_mode="add_tax",
    )

    assert result.lines[0].ton_price == Decimal("3770")
    assert result.average_ton_price == Decimal("3770")
    assert result.total == Decimal("885.00")
    assert not any("待业务确认" in warning for warning in result.warnings)


def test_invalid_quote_inputs_raise() -> None:
    with pytest.raises(QuoteValidationError):
        calculate_quote(
            spec="x",
            unit_price=Decimal("0"),
            weight_per_piece=Decimal("24.93"),
            pieces=1,
        )

    with pytest.raises(QuoteValidationError):
        calculate_quote(
            spec="x",
            unit_price=Decimal("3550"),
            weight_per_piece=Decimal("0"),
            pieces=1,
        )

    with pytest.raises(QuoteValidationError):
        calculate_quote(
            spec="x",
            unit_price=Decimal("3550"),
            weight_per_piece=Decimal("24.93"),
            pieces=0,
        )

    with pytest.raises(QuoteValidationError):
        calculate_quote(
            spec="x",
            unit_price=Decimal("3550"),
            weight_per_piece=Decimal("24.93"),
            pieces=1,
            tax_mode="add_tax",
        )
