from datetime import date
from decimal import Decimal
from pathlib import Path

from steel_core.ingest.quotes import parse_quote_csv


def _write_csv(path: Path, content: str, *, bom: bool = False) -> None:
    path.write_text(content, encoding="utf-8-sig" if bom else "utf-8")


def test_parse_valid_csv_and_report_missing_points(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv"
    _write_csv(
        path,
        "point_id,date,price,change,source,note\n"
        "P1,2026-10-23,3550,10,mysteel,ok\n"
        "P2,2026-10-23,3480,-10,mysteel,\n",
    )

    result = parse_quote_csv(
        path,
        allowed_point_codes={"P1", "P2"},
        expected_point_codes={"P1", "P2", "P3"},
    )

    assert result.total_rows == 2
    assert len(result.rows) == 2
    assert not result.errors

    first = result.rows[0]
    assert first.point_code == "P1"
    assert first.quote_date == date(2026, 10, 23)
    assert first.price == Decimal("3550")
    assert first.change == Decimal("10")
    assert first.source == "mysteel"

    assert any("P3" in warning.message for warning in result.warnings)


def test_unknown_point_is_error(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv"
    _write_csv(
        path,
        "point_id,date,price,change,source,note\nP9,2026-10-23,3550,,mysteel,\n",
    )

    result = parse_quote_csv(path, allowed_point_codes={"P1"})

    assert not result.rows
    assert any(error.field == "point_id" for error in result.errors)


def test_invalid_date_and_price_are_errors(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv"
    _write_csv(
        path,
        "point_id,date,price,change,source,note\n"
        "P1,2026-13-40,3550,,mysteel,\n"
        "P1,2026-10-23,0,,mysteel,\n"
        "P1,2026-10-23,abc,,mysteel,\n",
    )

    result = parse_quote_csv(path, allowed_point_codes={"P1"})

    assert not result.rows
    assert len(result.errors) == 3


def test_duplicate_point_date_is_error(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv"
    _write_csv(
        path,
        "point_id,date,price,change,source,note\n"
        "P1,2026-10-23,3550,,mysteel,\n"
        "P1,2026-10-23,3560,,mysteel,\n",
    )

    result = parse_quote_csv(path, allowed_point_codes={"P1"})

    assert len(result.rows) == 1
    assert any("重复" in error.message for error in result.errors)


def test_gbk_encoded_csv_is_supported(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv"
    content = "point_id,date,price,change,source,note\nP1,2026-10-23,3550,,mysteel,备注\n"
    path.write_bytes(content.encode("gb18030"))

    result = parse_quote_csv(path, allowed_point_codes={"P1"})

    assert len(result.rows) == 1
    assert result.rows[0].note == "备注"


def test_bom_prefixed_header_is_supported(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv"
    _write_csv(
        path,
        "point_id,date,price,change,source,note\nP1,2026-10-23,3550,,mysteel,\n",
        bom=True,
    )

    result = parse_quote_csv(path, allowed_point_codes={"P1"})

    assert len(result.rows) == 1
    assert not result.errors


def test_missing_required_header_is_error(tmp_path: Path) -> None:
    path = tmp_path / "quotes.csv"
    _write_csv(path, "point_id,date\nP1,2026-10-23\n")

    result = parse_quote_csv(path, allowed_point_codes={"P1"})

    assert not result.rows
    assert any("缺少必要列" in error.message for error in result.errors)
