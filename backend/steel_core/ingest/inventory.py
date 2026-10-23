from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import openpyxl

DATE_IN_FILENAME = re.compile(r"(\d{1,2})\.(\d{1,2})")
ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
BLOCK_SEPARATORS = ("：", ":")
HEADER_ALIASES = {
    "规格型号": "spec",
    "单价": "unit_price",
    "含税加": "tax_add",
    "支重": "weight_per_piece",
    "支数": "pieces",
    "重量": "total_weight",
    "支售价": "price_per_piece",
    "包装": "packaging",
    "厂家": "manufacturer",
}
NUMERIC_FIELDS = {
    "unit_price",
    "tax_add",
    "weight_per_piece",
    "pieces",
    "total_weight",
    "price_per_piece",
}
FIELD_LABELS = {
    "unit_price": "单价",
    "tax_add": "含税加",
    "weight_per_piece": "支重",
    "pieces": "支数",
    "total_weight": "重量",
    "price_per_piece": "支售价",
}


@dataclass(frozen=True)
class ParseIssue:
    row_no: int | None
    field: str | None
    message: str


@dataclass(frozen=True)
class InventoryRow:
    block: str
    spec: str
    unit_price: Decimal | None
    tax_add: Decimal | None
    weight_per_piece: Decimal | None
    pieces: int | None
    total_weight: Decimal | None
    price_per_piece: Decimal | None
    packaging: str | None
    manufacturer: str | None
    row_no: int


@dataclass
class InventoryParseResult:
    effective_date: date | None
    warehouse: str
    rows: list[InventoryRow] = field(default_factory=list)
    warnings: list[ParseIssue] = field(default_factory=list)
    errors: list[ParseIssue] = field(default_factory=list)


def parse_inventory_workbook(
    path: Path,
    *,
    explicit_date: date | None = None,
    today: date | None = None,
) -> InventoryParseResult:
    today = today or date.today()
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheet = workbook.worksheets[0]
    matrix = [list(row) for row in sheet.iter_rows(values_only=True)]
    workbook.close()

    blocks = _find_blocks(matrix)
    if not blocks:
        raise ValueError("未找到库存区块（方管/矩形管）")

    warnings: list[ParseIssue] = []
    errors: list[ParseIssue] = []
    rows: list[InventoryRow] = []
    footer_row = _find_footer_row(matrix)

    for block in blocks:
        header_row = block["header_row"]
        if header_row >= len(matrix):
            errors.append(ParseIssue(None, None, f"区块 {block['name']} 缺少表头行"))
            continue

        column_map = _header_columns(matrix[header_row], block["start"], block["end"])
        missing = {"spec", "unit_price"} - set(column_map)
        if missing:
            errors.append(
                ParseIssue(None, None, f"区块 {block['name']} 缺少必要列: {sorted(missing)}")
            )
            continue

        for row_index in range(header_row + 1, len(matrix)):
            if footer_row is not None and row_index >= footer_row:
                break
            raw_row = matrix[row_index]
            if _row_is_empty(raw_row, block["start"], block["end"]):
                continue
            spec = _cell_text(raw_row, block["start"] + column_map["spec"])
            if not spec:
                continue
            row_no = row_index + 1
            values: dict[str, Any] = {}
            for field_name in NUMERIC_FIELDS:
                if field_name not in column_map:
                    values[field_name] = None
                    continue
                raw_value = _cell_value(raw_row, block["start"] + column_map[field_name])
                values[field_name] = _to_decimal(
                    raw_value,
                    field_name,
                    row_no,
                    errors,
                )
            pieces = values["pieces"]
            if pieces is not None:
                values["pieces"] = int(pieces)

            packaging = (
                _cell_text(raw_row, block["start"] + column_map["packaging"])
                if "packaging" in column_map
                else None
            )
            manufacturer = (
                _cell_text(raw_row, block["start"] + column_map["manufacturer"])
                if "manufacturer" in column_map
                else None
            )

            _check_price_formula(
                row_no,
                values["unit_price"],
                values["weight_per_piece"],
                values["price_per_piece"],
                warnings,
            )

            rows.append(
                InventoryRow(
                    block=block["name"],
                    spec=spec,
                    unit_price=values["unit_price"],
                    tax_add=values["tax_add"],
                    weight_per_piece=values["weight_per_piece"],
                    pieces=values["pieces"],
                    total_weight=values["total_weight"],
                    price_per_piece=values["price_per_piece"],
                    packaging=packaging,
                    manufacturer=manufacturer,
                    row_no=row_no,
                )
            )

    effective_date = _resolve_effective_date(
        path, explicit_date, today, matrix, footer_row, warnings
    )
    warehouse = _resolve_warehouse(blocks)

    return InventoryParseResult(
        effective_date=effective_date,
        warehouse=warehouse,
        rows=rows,
        warnings=warnings,
        errors=errors,
    )


def _find_blocks(matrix: list[list[Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for row_index, row in enumerate(matrix):
        for column_index, value in enumerate(row):
            if not isinstance(value, str):
                continue
            text = value.strip()
            if "库" not in text:
                continue
            if not any(separator in text for separator in BLOCK_SEPARATORS):
                continue
            name = re.split(r"[：:]", text)[-1].strip()
            if "管" not in name and "型" not in name and "板" not in name:
                continue
            found.append(
                {
                    "name": name,
                    "header_row": row_index + 1,
                    "start": column_index,
                    "end": None,
                }
            )
    found.sort(key=lambda item: item["start"])
    for index, block in enumerate(found):
        block["end"] = found[index + 1]["start"] if index + 1 < len(found) else _max_columns(matrix)
    return found


def _header_columns(row: list[Any], start: int, end: int) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for offset, value in enumerate(row[start:end]):
        if not isinstance(value, str):
            continue
        label = value.strip()
        field_name = HEADER_ALIASES.get(label)
        if field_name is not None and field_name not in mapping:
            mapping[field_name] = offset
    return mapping


def _find_footer_row(matrix: list[list[Any]]) -> int | None:
    for row_index, row in enumerate(matrix):
        if any(isinstance(value, str) and "制表人" in value for value in row):
            return row_index
    return None


def _resolve_effective_date(
    path: Path,
    explicit_date: date | None,
    today: date,
    matrix: list[list[Any]],
    footer_row: int | None,
    warnings: list[ParseIssue],
) -> date | None:
    filename_date = _date_from_filename(path, today)
    footer_date = _date_from_footer(matrix, footer_row)

    chosen: date | None
    if explicit_date is not None:
        chosen = explicit_date
    elif filename_date is not None:
        chosen = filename_date
    else:
        chosen = footer_date

    if filename_date is not None and footer_date is not None and filename_date != footer_date:
        warnings.append(
            ParseIssue(
                None,
                "打印日期",
                f"文件名日期 {filename_date} 与表尾打印日期 {footer_date} 不一致",
            )
        )
    if chosen is None:
        warnings.append(ParseIssue(None, "生效日期", "无法确定生效日期"))
    return chosen


def _date_from_filename(path: Path, today: date) -> date | None:
    match = DATE_IN_FILENAME.search(path.stem)
    if not match:
        return None
    month, day = int(match.group(1)), int(match.group(2))
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return None
    if candidate > today:
        try:
            candidate = date(today.year - 1, month, day)
        except ValueError:
            return None
    return candidate


def _date_from_footer(matrix: list[list[Any]], footer_row: int | None) -> date | None:
    if footer_row is None:
        return None
    for value in matrix[footer_row]:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            match = ISO_DATE.search(value.strip())
            if match:
                try:
                    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                except ValueError:
                    continue
    return None


def _resolve_warehouse(blocks: list[dict[str, Any]]) -> str:
    return "昆明宝象库"


def _max_columns(matrix: list[list[Any]]) -> int:
    return max((len(row) for row in matrix), default=0)


def _row_is_empty(row: list[Any], start: int, end: int) -> bool:
    return all(_cell_value(row, index) in (None, "") for index in range(start, end))


def _cell_value(row: list[Any], index: int) -> Any:
    if index >= len(row):
        return None
    return row[index]


def _cell_text(row: list[Any], index: int) -> str | None:
    value = _cell_value(row, index)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_decimal(
    value: Any, field_name: str, row_no: int, errors: list[ParseIssue]
) -> Decimal | None:
    label = FIELD_LABELS.get(field_name, field_name)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        errors.append(ParseIssue(row_no, label, f"{label} 解析失败: {value!r}"))
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value).strip().replace(",", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        errors.append(ParseIssue(row_no, label, f"{label} 解析失败: {value!r}"))
        return None


def _check_price_formula(
    row_no: int,
    unit_price: Decimal | None,
    weight_per_piece: Decimal | None,
    price_per_piece: Decimal | None,
    warnings: list[ParseIssue],
) -> None:
    if unit_price is None or weight_per_piece is None or price_per_piece is None:
        return
    expected = unit_price * weight_per_piece / Decimal("1000")
    if abs(expected - price_per_piece) > Decimal("0.05"):
        warnings.append(
            ParseIssue(
                row_no,
                "支售价",
                f"支售价与公式不一致: 期望 {expected:.2f}, 实际 {price_per_piece}",
            )
        )
