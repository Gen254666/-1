from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import DatasetType, ImportStatus
from steel_core.db.models.governance import AuditLog, ImportBatch
from steel_core.db.models.inventory import InventoryItem, InventorySnapshot
from steel_core.db.models.market import MarketQuote
from steel_core.ingest.common import ParseIssue
from steel_core.ingest.inventory import parse_inventory_workbook
from steel_core.ingest.quotes import parse_quote_csv
from steel_core.versioning.service import (
    NoChangesError,
    compute_checksum,
    create_import_batch,
    create_version,
    get_active_version,
)


@dataclass
class ImportOutcome:
    batch_id: UUID
    version_id: UUID | None
    effective_date: date
    rows_ok: int
    rows_failed: int
    no_changes: bool = False
    warnings: list[ParseIssue] = field(default_factory=list)
    errors: list[ParseIssue] = field(default_factory=list)


class ImportValidationError(Exception):
    def __init__(self, batch_id: UUID, errors: list[ParseIssue]) -> None:
        super().__init__("import validation failed")
        self.batch_id = batch_id
        self.errors = errors


def _issue_dicts(issues: list[ParseIssue]) -> list[dict[str, Any]]:
    return [
        {"row_no": issue.row_no, "field": issue.field, "message": issue.message} for issue in issues
    ]


def _failed_row_count(issues: list[ParseIssue]) -> int:
    rows = {issue.row_no for issue in issues if issue.row_no is not None}
    return len(rows) if rows else (1 if issues else 0)


def _file_hash(path: Path) -> str:
    return compute_checksum(path.read_bytes())


def _stable_rows(rows: list[Any]) -> list[dict[str, Any]]:
    normalized = [
        {key: value for key, value in asdict(row).items() if key != "row_no"} for row in rows
    ]
    return sorted(
        normalized,
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str),
    )


async def _record_failed_batch(
    session: AsyncSession,
    *,
    user_id: UUID,
    dataset_type: DatasetType,
    effective_date: date,
    path: Path,
    rows_total: int,
    rows_ok: int,
    errors: list[ParseIssue],
) -> ImportBatch:
    rows_failed = _failed_row_count(errors)
    batch = await create_import_batch(
        session,
        user_id=user_id,
        dataset_type=dataset_type,
        effective_date=effective_date,
        file_name=path.name,
        file_hash=_file_hash(path),
        rows_total=rows_total,
        rows_ok=max(rows_ok, 0),
        rows_failed=rows_failed,
        errors=_issue_dicts(errors),
        status=ImportStatus.FAILED,
    )
    await session.commit()
    return batch


async def import_quotes(
    session: AsyncSession,
    *,
    user_id: UUID,
    path: Path,
    allowed_points: dict[str, UUID],
    expected_point_codes: set[str] | None = None,
    default_source: str = "mysteel",
) -> ImportOutcome:
    try:
        parsed = parse_quote_csv(
            path,
            allowed_point_codes=set(allowed_points),
            expected_point_codes=expected_point_codes,
            default_source=default_source,
        )
    except Exception as exc:  # noqa: BLE001
        errors = [ParseIssue(None, None, f"文件解析失败: {exc}")]
        batch = await _record_failed_batch(
            session,
            user_id=user_id,
            dataset_type=DatasetType.MARKET_QUOTE,
            effective_date=date.today(),
            path=path,
            rows_total=0,
            rows_ok=0,
            errors=errors,
        )
        raise ImportValidationError(batch.id, errors) from exc

    if not parsed.rows and not parsed.errors:
        parsed.errors.append(ParseIssue(None, None, "CSV 无有效数据"))

    dates = {row.quote_date for row in parsed.rows}
    if len(dates) > 1:
        parsed.errors.append(ParseIssue(None, "date", "CSV 包含多个日期，需按日期拆分导入"))
    effective_date = next(iter(dates)) if len(dates) == 1 else date.today()

    if parsed.errors:
        batch = await _record_failed_batch(
            session,
            user_id=user_id,
            dataset_type=DatasetType.MARKET_QUOTE,
            effective_date=effective_date,
            path=path,
            rows_total=parsed.total_rows or len(parsed.rows),
            rows_ok=len(parsed.rows),
            errors=parsed.errors,
        )
        raise ImportValidationError(batch.id, parsed.errors)

    checksum = compute_checksum({"rows": _stable_rows(parsed.rows)})
    batch = await create_import_batch(
        session,
        user_id=user_id,
        dataset_type=DatasetType.MARKET_QUOTE,
        effective_date=effective_date,
        file_name=path.name,
        file_hash=_file_hash(path),
        rows_total=parsed.total_rows,
        rows_ok=len(parsed.rows),
        rows_failed=0,
    )

    try:
        version = await create_version(
            session,
            dataset_type=DatasetType.MARKET_QUOTE,
            effective_date=effective_date,
            checksum=checksum,
            import_batch_id=batch.id,
        )
    except NoChangesError:
        active = await get_active_version(session, DatasetType.MARKET_QUOTE, effective_date)
        await session.commit()
        return ImportOutcome(
            batch_id=batch.id,
            version_id=active.id if active is not None else None,
            effective_date=effective_date,
            rows_ok=len(parsed.rows),
            rows_failed=0,
            no_changes=True,
            warnings=parsed.warnings,
        )

    for row in parsed.rows:
        point_id = allowed_points.get(row.point_code)
        if point_id is None:
            msg = f"point code not allowed: {row.point_code}"
            raise ValueError(msg)
        session.add(
            MarketQuote(
                version_id=version.id,
                point_id=point_id,
                quote_date=row.quote_date,
                price=row.price,
                change=row.change,
                source=row.source,
                note=row.note,
            )
        )

    session.add(
        AuditLog(
            user_id=user_id,
            action="import.market_quote",
            resource_type="dataset_version",
            resource_id=str(version.id),
            detail={
                "rows": len(parsed.rows),
                "effective_date": effective_date.isoformat(),
            },
        )
    )
    await session.commit()

    return ImportOutcome(
        batch_id=batch.id,
        version_id=version.id,
        effective_date=effective_date,
        rows_ok=len(parsed.rows),
        rows_failed=0,
        warnings=parsed.warnings,
    )


async def import_inventory(
    session: AsyncSession,
    *,
    user_id: UUID,
    path: Path,
    explicit_date: date | None = None,
    warehouse: str | None = None,
) -> ImportOutcome:
    try:
        parsed = parse_inventory_workbook(path, explicit_date=explicit_date)
    except Exception as exc:  # noqa: BLE001
        errors = [ParseIssue(None, None, f"文件解析失败: {exc}")]
        batch = await _record_failed_batch(
            session,
            user_id=user_id,
            dataset_type=DatasetType.INVENTORY,
            effective_date=explicit_date or date.today(),
            path=path,
            rows_total=0,
            rows_ok=0,
            errors=errors,
        )
        raise ImportValidationError(batch.id, errors) from exc

    if parsed.effective_date is None:
        parsed.errors.append(ParseIssue(None, "生效日期", "无法确定生效日期"))
    if not parsed.rows and not parsed.errors:
        parsed.errors.append(ParseIssue(None, None, "库存表无有效数据"))

    effective_date = parsed.effective_date or date.today()
    if parsed.errors:
        failed_rows = _failed_row_count(parsed.errors)
        batch = await _record_failed_batch(
            session,
            user_id=user_id,
            dataset_type=DatasetType.INVENTORY,
            effective_date=effective_date,
            path=path,
            rows_total=len(parsed.rows),
            rows_ok=max(len(parsed.rows) - failed_rows, 0),
            errors=parsed.errors,
        )
        raise ImportValidationError(batch.id, parsed.errors)

    assert parsed.effective_date is not None
    warehouse_name = warehouse or parsed.warehouse
    checksum = compute_checksum(
        {
            "warehouse": warehouse_name,
            "effective_date": parsed.effective_date.isoformat(),
            "rows": _stable_rows(parsed.rows),
        }
    )
    batch = await create_import_batch(
        session,
        user_id=user_id,
        dataset_type=DatasetType.INVENTORY,
        effective_date=parsed.effective_date,
        file_name=path.name,
        file_hash=_file_hash(path),
        rows_total=len(parsed.rows),
        rows_ok=len(parsed.rows),
        rows_failed=0,
    )

    try:
        version = await create_version(
            session,
            dataset_type=DatasetType.INVENTORY,
            effective_date=parsed.effective_date,
            checksum=checksum,
            import_batch_id=batch.id,
        )
    except NoChangesError:
        active = await get_active_version(session, DatasetType.INVENTORY, parsed.effective_date)
        await session.commit()
        return ImportOutcome(
            batch_id=batch.id,
            version_id=active.id if active is not None else None,
            effective_date=parsed.effective_date,
            rows_ok=len(parsed.rows),
            rows_failed=0,
            no_changes=True,
            warnings=parsed.warnings,
        )

    snapshot = InventorySnapshot(
        version_id=version.id,
        snapshot_date=parsed.effective_date,
        warehouse=warehouse_name,
        source_file=path.name,
    )
    session.add(snapshot)
    await session.flush()

    session.add_all(
        [
            InventoryItem(
                snapshot_id=snapshot.id,
                block=row.block,
                spec=row.spec,
                unit_price=row.unit_price,
                tax_add=row.tax_add,
                weight_per_piece=row.weight_per_piece,
                pieces=row.pieces,
                total_weight=row.total_weight,
                price_per_piece=row.price_per_piece,
                packaging=row.packaging,
                manufacturer=row.manufacturer,
                row_no=row.row_no,
            )
            for row in parsed.rows
        ]
    )
    session.add(
        AuditLog(
            user_id=user_id,
            action="import.inventory",
            resource_type="dataset_version",
            resource_id=str(version.id),
            detail={
                "rows": len(parsed.rows),
                "effective_date": parsed.effective_date.isoformat(),
                "warehouse": warehouse_name,
            },
        )
    )
    await session.commit()

    return ImportOutcome(
        batch_id=batch.id,
        version_id=version.id,
        effective_date=parsed.effective_date,
        rows_ok=len(parsed.rows),
        rows_failed=0,
        warnings=parsed.warnings,
    )
