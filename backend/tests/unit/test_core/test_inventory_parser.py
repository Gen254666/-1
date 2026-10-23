from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from steel_core.ingest.inventory import parse_inventory_workbook

REAL_INVENTORY_FILE = Path(__file__).resolve().parents[4] / "10.23库存状况表（部分价格已调）.xlsx"

HEADERS = [
    "规格型号",
    "单价",
    "含税加",
    "支重",
    "支数",
    "重量",
    "支售价",
    "包装",
    "厂家",
]


def _build_workbook(path: Path, footer_date: date = date(2026, 10, 23)) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "第一页"
    sheet["I1"] = "库存状况表"
    sheet["A2"] = "宝象库：方管"
    sheet["J2"] = "宝象库：矩形管"

    for index, header in enumerate(HEADERS, start=1):
        sheet.cell(row=3, column=index, value=header)
        sheet.cell(row=3, column=index + 9, value=header)

    left_rows = [
        ["100*100*2.5*6m", 3550, 220, 24.93, 230, 5.662, 88.5, 25, "正大"],
        ["100*100*3.0*6m", 3500, 220, 35.0, 100, 3.5, 100.0, 25, "友发"],
        ["100*100*3.5*6m", "bad-price", 220, 40.0, 50, 2.0, 142.0, 25, "友发"],
    ]
    right_rows = [
        ["100*150*2.5*6m", 3320, 220, 54.46, 128, 6.884, 180.81, 20, "汇丰"],
        ["100*150*3.0*6m", 3320, 220, 66.19, 120, 7.943, 219.75, 12, "正大"],
    ]

    for offset, values in enumerate(left_rows):
        for column, value in enumerate(values, start=1):
            sheet.cell(row=4 + offset, column=column, value=value)
    for offset, values in enumerate(right_rows):
        for column, value in enumerate(values, start=10):
            sheet.cell(row=4 + offset, column=column, value=value)

    footer_row = 9
    sheet.cell(row=footer_row, column=1, value="制表人:测试")
    sheet.cell(row=footer_row, column=2, value="打印日期:")
    sheet.cell(row=footer_row, column=4, value=footer_date)

    workbook.save(path)


def test_parse_inventory_workbook(tmp_path: Path) -> None:
    path = tmp_path / "10.23库存状况表.xlsx"
    _build_workbook(path)

    result = parse_inventory_workbook(path, today=date(2026, 10, 23))

    assert result.effective_date == date(2026, 10, 23)
    assert result.warehouse == "昆明宝象库"
    assert len(result.rows) == 5
    assert {row.block for row in result.rows} == {"方管", "矩形管"}

    first = result.rows[0]
    assert first.spec == "100*100*2.5*6m"
    assert first.unit_price == 3550
    assert first.weight_per_piece == Decimal("24.93")
    assert first.pieces == 230
    assert first.price_per_piece == Decimal("88.5")
    assert first.manufacturer == "正大"
    assert first.row_no == 4

    assert any("支售价" in warning.message for warning in result.warnings)
    assert any(error.field == "单价" and error.row_no == 6 for error in result.errors)


def test_explicit_date_overrides_filename(tmp_path: Path) -> None:
    path = tmp_path / "10.23库存状况表.xlsx"
    _build_workbook(path)

    result = parse_inventory_workbook(
        path, explicit_date=date(2025, 12, 31), today=date(2026, 10, 23)
    )

    assert result.effective_date == date(2025, 12, 31)


def test_filename_date_rolls_back_year_when_in_future(tmp_path: Path) -> None:
    path = tmp_path / "12.31库存状况表.xlsx"
    _build_workbook(path, footer_date=date(2026, 12, 31))

    result = parse_inventory_workbook(path, today=date(2026, 10, 23))

    assert result.effective_date == date(2025, 12, 31)


def test_footer_date_mismatch_produces_warning(tmp_path: Path) -> None:
    path = tmp_path / "10.23库存状况表.xlsx"
    _build_workbook(path, footer_date=date(2026, 10, 22))

    result = parse_inventory_workbook(path, today=date(2026, 10, 23))

    assert any("打印日期" in warning.message for warning in result.warnings)


@pytest.mark.skipif(not REAL_INVENTORY_FILE.exists(), reason="real inventory file is not present")
def test_real_inventory_file_smoke() -> None:
    result = parse_inventory_workbook(REAL_INVENTORY_FILE, explicit_date=date(2026, 10, 23))

    assert result.effective_date == date(2026, 10, 23)
    assert len(result.rows) >= 150
    assert not result.errors
    assert {row.block for row in result.rows} == {"方管", "矩形管"}
