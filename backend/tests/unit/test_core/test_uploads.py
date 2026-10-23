import io
import zipfile

import openpyxl
import pytest

from app.core.uploads import (
    UploadValidationError,
    escape_csv_cell,
    sanitize_filename,
    validate_upload,
)


def _xlsx_bytes() -> bytes:
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "规格"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_valid_xlsx_is_accepted() -> None:
    safe_name = validate_upload("10.23库存状况表.xlsx", _xlsx_bytes())

    assert safe_name.endswith(".xlsx")
    assert "库存" not in safe_name


def test_valid_csv_is_accepted() -> None:
    safe_name = validate_upload("quotes.csv", b"point_id,date,price\nP1,2026-10-23,3550\n")

    assert safe_name.endswith(".csv")


def test_disallowed_extension_is_rejected() -> None:
    with pytest.raises(UploadValidationError):
        validate_upload("payload.exe", b"MZ")


def test_macro_extension_is_rejected() -> None:
    with pytest.raises(UploadValidationError):
        validate_upload("quotes.xlsm", b"PK\x03\x04")


def test_fake_xlsx_is_rejected() -> None:
    with pytest.raises(UploadValidationError):
        validate_upload("quotes.xlsx", b"not a zip")


def test_oversize_file_is_rejected() -> None:
    with pytest.raises(UploadValidationError):
        validate_upload("quotes.csv", b"a" * 20, max_bytes=10)


def test_too_many_csv_rows_is_rejected() -> None:
    with pytest.raises(UploadValidationError):
        validate_upload("quotes.csv", b"a\nb\n", max_rows=1)


def test_zip_bomb_is_rejected() -> None:
    payload = _zip_bytes(
        {
            "[Content_Types].xml": b"<Types/>",
            "word/document.xml": b"0" * 5_000_000,
        }
    )

    with pytest.raises(UploadValidationError):
        validate_upload("document.docx", payload)


def test_docx_requires_document_xml() -> None:
    payload = _zip_bytes({"[Content_Types].xml": b"<Types/>"})

    with pytest.raises(UploadValidationError):
        validate_upload("document.docx", payload)


def test_pdf_magic_is_checked() -> None:
    assert validate_upload("report.pdf", b"%PDF-1.7").endswith(".pdf")

    with pytest.raises(UploadValidationError):
        validate_upload("report.pdf", b"not a pdf")


def test_sanitize_filename_removes_paths() -> None:
    safe_name = sanitize_filename("../../evil.csv")

    assert "/" not in safe_name
    assert ".." not in safe_name
    assert safe_name.endswith(".csv")


def test_escape_csv_cell_blocks_formula_injection() -> None:
    assert escape_csv_cell("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
    assert escape_csv_cell("+1") == "'+1"
    assert escape_csv_cell("-1") == "'-1"
    assert escape_csv_cell("@SUM(A1)") == "'@SUM(A1)"
    assert escape_csv_cell("normal") == "normal"
