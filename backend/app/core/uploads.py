from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path

import openpyxl

ALLOWED_EXTENSIONS = {".xlsx", ".csv", ".pdf", ".docx", ".md", ".txt"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_ROWS = 10_000


class UploadValidationError(Exception):
    def __init__(self, message: str, code: str = "INVALID_UPLOAD") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sanitize_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return f"{uuid.uuid4().hex}{suffix}"


def escape_csv_cell(value: str) -> str:
    if value and value[0] in "=+-@":
        return f"'{value}"
    return value


def validate_upload(
    filename: str,
    content: bytes,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
    max_rows: int = MAX_ROWS,
) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(f"不支持的文件类型: {suffix or '(无扩展名)'}")
    if len(content) > max_bytes:
        raise UploadValidationError(f"文件超过大小限制: {max_bytes} 字节")
    if not content:
        raise UploadValidationError("文件为空")

    if suffix in {".xlsx", ".docx"}:
        required = ("xl/workbook.xml",) if suffix == ".xlsx" else ("word/document.xml",)
        _validate_zip(content, required)
        if suffix == ".xlsx":
            _validate_xlsx_rows(content, max_rows)
    elif suffix == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise UploadValidationError("PDF 文件头不合法")
    else:
        if b"\x00" in content:
            raise UploadValidationError("文本文件包含二进制内容")
        if suffix == ".csv":
            rows = content.count(b"\n") + (0 if content.endswith(b"\n") else 1)
            if rows > max_rows:
                raise UploadValidationError(f"CSV 行数超过限制: {max_rows}")

    return sanitize_filename(filename)


def _validate_zip(content: bytes, required: tuple[str, ...]) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise UploadValidationError("文件不是合法的 Office 文档") from exc

    with archive:
        names = set(archive.namelist())
        for name in names:
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts:
                raise UploadValidationError("压缩包包含非法路径")

        missing = set(required) - names
        if missing:
            raise UploadValidationError(f"Office 文档缺少必要文件: {sorted(missing)}")

        total_uncompressed = sum(info.file_size for info in archive.infolist())
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise UploadValidationError("压缩包解压后体积过大")
        if (
            total_uncompressed > 1_000_000
            and total_uncompressed / max(len(content), 1) > MAX_COMPRESSION_RATIO
        ):
            raise UploadValidationError("压缩包压缩比异常，疑似 zip bomb")


def _validate_xlsx_rows(content: bytes, max_rows: int) -> None:
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise UploadValidationError("Excel 文件无法解析") from exc

    try:
        for sheet in workbook.worksheets:
            if sheet.max_row > max_rows:
                raise UploadValidationError(f"Excel 行数超过限制: {max_rows}")
    finally:
        workbook.close()
