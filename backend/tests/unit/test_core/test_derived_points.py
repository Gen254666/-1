from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from steel_core.ingest.derived import (
    PointCodeError,
    canonical_rows,
    category_for_block,
    point_code,
    region_for_warehouse,
)
from steel_core.ingest.inventory import InventoryRow, parse_inventory_workbook

REAL_INVENTORY_FILE = Path(__file__).resolve().parents[4] / "10.25库存状况表（部分价格已调）.xlsx"


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


def test_code_mapping_and_chinese_suffixes() -> None:
    assert category_for_block("方管") == "方管"
    assert category_for_block("矩形管") == "矩管"
    assert region_for_warehouse("昆明宝象库") == "昆明"
    assert point_code("方管", "100*100*2.5*6m", "昆明") == "FANG_100X100X2.5X6M_KUNMING"
    assert point_code("矩管", "100*150*7.75*12m", "昆明") == "JU_100X150X7.75X12M_KUNMING"
    assert point_code("方管", "250*250*12*9.3米", "昆明") == "FANG_250X250X12X9.3M_KUNMING"
    assert point_code("方管", "250*250*11.75*6m低", "昆明") == "FANG_250X250X11.75X6MDI_KUNMING"


def test_unknown_non_ascii_raises() -> None:
    with pytest.raises(PointCodeError):
        point_code("方管", "100*100*2.5*6m★", "昆明")


def test_canonical_rows_keeps_max_pieces() -> None:
    rows = [
        _row("方管", "120*120*3.75*6m", "3320", 2),
        _row("方管", "120*120*3.75*6m", "3320", 268),
        _row("矩形管", "100*150*2.5*6m", "3320", 128),
    ]
    result = canonical_rows(rows)
    assert len(result) == 2
    assert result[0].pieces == 268


@pytest.mark.skipif(not REAL_INVENTORY_FILE.exists(), reason="real inventory file is not present")
def test_real_inventory_codes_are_unique_and_ascii() -> None:
    parsed = parse_inventory_workbook(REAL_INVENTORY_FILE, explicit_date=date(2026, 10, 25))
    rows = canonical_rows(parsed.rows)
    assert len(rows) == 370

    region = region_for_warehouse(parsed.warehouse)
    codes = [point_code(category_for_block(row.block), row.spec, region) for row in rows]
    assert len(set(codes)) == 370
    assert all(code.isascii() for code in codes)
    assert max(len(code) for code in codes) <= 64
