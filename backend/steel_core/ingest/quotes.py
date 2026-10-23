from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from steel_core.ingest.common import ParseIssue

REQUIRED_COLUMNS = {"point_id", "date", "price"}


@dataclass(frozen=True)
class QuoteRow:
    point_code: str
    quote_date: date
    price: Decimal
    change: Decimal | None
    source: str
    note: str | None
    row_no: int


@dataclass
class QuoteParseResult:
    rows: list[QuoteRow] = field(default_factory=list)
    warnings: list[ParseIssue] = field(default_factory=list)
    errors: list[ParseIssue] = field(default_factory=list)
    total_rows: int = 0


def parse_quote_csv(
    path: Path,
    *,
    allowed_point_codes: set[str],
    expected_point_codes: set[str] | None = None,
    default_source: str = "mysteel",
) -> QuoteParseResult:
    result = QuoteParseResult()

    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="gb18030")
        except UnicodeDecodeError:
            result.errors.append(ParseIssue(None, None, "CSV 编码无法识别"))
            return result

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = set(reader.fieldnames or [])
    missing = REQUIRED_COLUMNS - fieldnames
    if missing:
        result.errors.append(ParseIssue(None, None, f"缺少必要列: {sorted(missing)}"))
        return result

    seen: set[tuple[str, date]] = set()
    for row_no, raw in enumerate(reader, start=2):
        if not any((value or "").strip() for value in raw.values()):
            continue
        result.total_rows += 1

        valid = True
        code = (raw.get("point_id") or "").strip()
        if code not in allowed_point_codes:
            result.errors.append(ParseIssue(row_no, "point_id", f"未知或不可见点位: {code!r}"))
            valid = False

        quote_date = _parse_date(raw.get("date"), row_no, result.errors)
        if quote_date is None:
            valid = False

        price = _parse_decimal(raw.get("price"), "price", row_no, result.errors, positive=True)
        if price is None:
            valid = False

        change: Decimal | None = None
        change_raw = (raw.get("change") or "").strip()
        if change_raw:
            change = _parse_decimal(change_raw, "change", row_no, result.errors, positive=False)
            if change is None:
                valid = False

        if not valid:
            continue

        assert quote_date is not None
        assert price is not None
        key = (code, quote_date)
        if key in seen:
            result.errors.append(
                ParseIssue(
                    row_no,
                    "point_id",
                    f"重复的 point_id/date: {code} {quote_date}",
                )
            )
            continue
        seen.add(key)

        source = (raw.get("source") or "").strip() or default_source
        note = (raw.get("note") or "").strip() or None
        result.rows.append(
            QuoteRow(
                point_code=code,
                quote_date=quote_date,
                price=price,
                change=change,
                source=source,
                note=note,
                row_no=row_no,
            )
        )

    if expected_point_codes:
        present = {row.point_code for row in result.rows}
        for code in sorted(expected_point_codes - present):
            result.warnings.append(ParseIssue(None, "point_id", f"CSV 未包含跟踪点位: {code}"))

    return result


def _parse_date(value: str | None, row_no: int, errors: list[ParseIssue]) -> date | None:
    text = (value or "").strip()
    if not text:
        errors.append(ParseIssue(row_no, "date", "日期为空"))
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        errors.append(ParseIssue(row_no, "date", f"日期格式错误: {text!r}"))
        return None


def _parse_decimal(
    value: str | None,
    field_name: str,
    row_no: int,
    errors: list[ParseIssue],
    *,
    positive: bool,
) -> Decimal | None:
    text = (value or "").strip().replace(",", "")
    if not text:
        errors.append(ParseIssue(row_no, field_name, f"{field_name} 为空"))
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        errors.append(ParseIssue(row_no, field_name, f"{field_name} 解析失败: {value!r}"))
        return None
    if positive and number <= 0:
        errors.append(ParseIssue(row_no, field_name, f"{field_name} 必须大于 0: {number}"))
        return None
    return number
