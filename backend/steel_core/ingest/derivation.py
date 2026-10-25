from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.audit.service import write_audit
from steel_core.db.enums import DatasetType, PointScope, VersionStatus
from steel_core.db.models.governance import DatasetVersion
from steel_core.db.models.inventory import InventoryItem, InventorySnapshot
from steel_core.db.models.market import MarketQuote, PricePoint
from steel_core.ingest.common import ParseIssue
from steel_core.ingest.derived import (
    canonical_rows,
    category_for_block,
    point_code,
    region_for_warehouse,
)
from steel_core.ingest.inventory import InventoryRow
from steel_core.query.service import normalize_spec
from steel_core.versioning.service import (
    NoChangesError,
    compute_checksum,
    create_import_batch,
    create_version,
    get_active_version,
)

DRIVEN_SOURCES = {"inventory", "mysteel"}
SHRINK_GUARD_RATIO = 0.5
SHRINK_GUARD_MIN = 10


@dataclass
class DerivationOutcome:
    points_created: int = 0
    points_updated: int = 0
    points_deactivated: int = 0
    quotes_written: int = 0
    quote_version_id: UUID | None = None
    quote_no_changes: bool = False
    warnings: list[ParseIssue] = field(default_factory=list)


async def sync_inventory_derivation(
    session: AsyncSession,
    *,
    user_id: UUID,
    effective_date: date,
    warehouse: str,
    rows: list[InventoryRow],
    source_file: str,
    force: bool = False,
    deactivate_missing: bool = True,
) -> DerivationOutcome:
    outcome = DerivationOutcome()
    canonical = canonical_rows(rows)
    region = region_for_warehouse(warehouse)
    derived: list[tuple[str, str, InventoryRow]] = []
    for row in canonical:
        category = category_for_block(row.block)
        code = point_code(category, row.spec, region)
        derived.append((code, category, row))

    existing_points = list(
        (
            await session.scalars(
                select(PricePoint).where(PricePoint.scope == PointScope.PUBLIC)
            )
        ).all()
    )
    by_code = {point.code: point for point in existing_points}
    derived_codes = {code for code, _, _ in derived}
    points_by_code: dict[str, PricePoint] = {}

    for code, category, row in derived:
        point = by_code.get(code)
        if point is None:
            point = PricePoint(
                scope=PointScope.PUBLIC,
                owner_user_id=None,
                code=code,
                category=category,
                spec=row.spec,
                region=region,
                source="inventory",
                unit="元/吨",
                is_active=True,
            )
            session.add(point)
            by_code[code] = point
            outcome.points_created += 1
        else:
            changes = {
                "category": category,
                "spec": row.spec,
                "region": region,
                "source": "inventory",
                "unit": "元/吨",
                "is_active": True,
            }
            if any(getattr(point, key) != value for key, value in changes.items()):
                for key, value in changes.items():
                    setattr(point, key, value)
                outcome.points_updated += 1
        points_by_code[code] = point

    await session.flush()

    _append_conflict_warnings(rows, outcome)
    priced = [
        (code, row)
        for code, _, row in derived
        if row.unit_price is not None
    ]
    for _, _, row in derived:
        if row.unit_price is None:
            outcome.warnings.append(
                ParseIssue(None, "单价", f"规格 {row.spec} 缺少单价，未生成行情")
            )

    driven = (
        [
            point
            for point in existing_points
            if point.is_active and point.source in DRIVEN_SOURCES
        ]
        if deactivate_missing
        else []
    )
    to_deactivate = [point for point in driven if point.code not in derived_codes]
    existing_quote_count = await _active_quote_count(session, effective_date)
    point_shrink = (
        deactivate_missing
        and len(driven) >= SHRINK_GUARD_MIN
        and len(derived_codes) < len(driven) * SHRINK_GUARD_RATIO
    )
    quote_shrink = (
        deactivate_missing
        and existing_quote_count >= SHRINK_GUARD_MIN
        and len(priced) < existing_quote_count * SHRINK_GUARD_RATIO
    )
    if not force and (point_shrink or quote_shrink):
        outcome.warnings.append(
            ParseIssue(
                None,
                "点位",
                f"库存规模大幅缩减（点位 {len(driven)}→{len(derived_codes)}，"
                f"行情 {existing_quote_count}→{len(priced)}），已跳过停用与行情覆盖；"
                "确认无误后可强制同步",
            )
        )
        active = await get_active_version(session, DatasetType.MARKET_QUOTE, effective_date)
        outcome.quote_no_changes = True
        outcome.quote_version_id = active.id if active is not None else None
        await _write_audit(
            session,
            user_id=user_id,
            outcome=outcome,
            effective_date=effective_date,
            warehouse=warehouse,
            resource_id=str(outcome.quote_version_id) if outcome.quote_version_id else None,
            guard_tripped=True,
        )
        return outcome

    if to_deactivate:
        for point in to_deactivate:
            point.is_active = False
        outcome.points_deactivated = len(to_deactivate)

    quote_payload = [
        {
            "code": code,
            "date": effective_date.isoformat(),
            "price": str(row.unit_price),
            "source": "inventory",
        }
        for code, row in priced
    ]
    checksum = compute_checksum({"rows": sorted(quote_payload, key=lambda item: item["code"])})
    batch = await create_import_batch(
        session,
        user_id=user_id,
        dataset_type=DatasetType.MARKET_QUOTE,
        effective_date=effective_date,
        file_name=f"自动生成-{source_file}",
        file_hash=checksum,
        rows_total=len(priced),
        rows_ok=len(priced),
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
        outcome.quote_no_changes = True
        active = await get_active_version(
            session, DatasetType.MARKET_QUOTE, effective_date
        )
        outcome.quote_version_id = active.id if active is not None else None
    else:
        for code, row in priced:
            session.add(
                MarketQuote(
                    version_id=version.id,
                    point_id=points_by_code[code].id,
                    quote_date=effective_date,
                    price=row.unit_price,
                    change=None,
                    source="inventory",
                    note="库存表单价",
                )
            )
        outcome.quotes_written = len(priced)
        outcome.quote_version_id = version.id

    await _write_audit(
        session,
        user_id=user_id,
        outcome=outcome,
        effective_date=effective_date,
        warehouse=warehouse,
        resource_id=str(outcome.quote_version_id) if outcome.quote_version_id else str(batch.id),
    )
    return outcome


async def _active_quote_count(session: AsyncSession, effective_date: date) -> int:
    version = await get_active_version(session, DatasetType.MARKET_QUOTE, effective_date)
    if version is None:
        return 0
    return int(
        await session.scalar(
            select(func.count())
            .select_from(MarketQuote)
            .where(MarketQuote.version_id == version.id)
        )
        or 0
    )


async def _write_audit(
    session: AsyncSession,
    *,
    user_id: UUID,
    outcome: DerivationOutcome,
    effective_date: date,
    warehouse: str,
    resource_id: str | None,
    guard_tripped: bool = False,
) -> None:
    await write_audit(
        session,
        user_id=user_id,
        action="derive.inventory",
        resource_type="dataset_version",
        resource_id=resource_id,
        detail={
            "effective_date": effective_date.isoformat(),
            "warehouse": warehouse,
            "points_created": outcome.points_created,
            "points_updated": outcome.points_updated,
            "points_deactivated": outcome.points_deactivated,
            "quotes_written": outcome.quotes_written,
            "quote_no_changes": outcome.quote_no_changes,
            "guard_tripped": guard_tripped,
        },
    )


async def derive_from_active_snapshot(
    session: AsyncSession,
    *,
    user_id: UUID,
    effective_date: date,
    force: bool = False,
    allow_empty: bool = False,
) -> DerivationOutcome | None:
    snapshot = await session.scalar(
        select(InventorySnapshot)
        .join(DatasetVersion, InventorySnapshot.version_id == DatasetVersion.id)
        .where(
            DatasetVersion.status == VersionStatus.ACTIVE,
            InventorySnapshot.snapshot_date == effective_date,
        )
    )
    if snapshot is None:
        if not allow_empty:
            return None
        outcome = await sync_inventory_derivation(
            session,
            user_id=user_id,
            effective_date=effective_date,
            warehouse="",
            rows=[],
            source_file=f"回滚重推导-{effective_date.isoformat()}",
            force=force,
            deactivate_missing=False,
        )
        outcome.warnings.append(
            ParseIssue(None, "库存", "回滚后无可用库存快照，已清空当日行情")
        )
        return outcome

    items = list(
        (
            await session.scalars(
                select(InventoryItem)
                .where(InventoryItem.snapshot_id == snapshot.id)
                .order_by(InventoryItem.row_no)
            )
        ).all()
    )
    rows = [
        InventoryRow(
            block=item.block,
            spec=item.spec,
            unit_price=item.unit_price,
            tax_add=item.tax_add,
            weight_per_piece=item.weight_per_piece,
            pieces=item.pieces,
            total_weight=item.total_weight,
            price_per_piece=item.price_per_piece,
            packaging=item.packaging,
            manufacturer=item.manufacturer,
            row_no=item.row_no,
        )
        for item in items
    ]
    latest_inventory_date = await session.scalar(
        select(func.max(InventorySnapshot.snapshot_date))
        .join(DatasetVersion, InventorySnapshot.version_id == DatasetVersion.id)
        .where(
            DatasetVersion.status == VersionStatus.ACTIVE,
            DatasetVersion.dataset_type == DatasetType.INVENTORY,
        )
    )
    historical = latest_inventory_date is not None and effective_date < latest_inventory_date
    outcome = await sync_inventory_derivation(
        session,
        user_id=user_id,
        effective_date=effective_date,
        warehouse=snapshot.warehouse,
        rows=rows,
        source_file=snapshot.source_file,
        force=force,
        deactivate_missing=not historical,
    )
    if historical:
        outcome.warnings.append(
            ParseIssue(None, "点位", "历史日期重推导不调整当前点位目录")
        )
    return outcome


def _append_conflict_warnings(
    rows: list[InventoryRow], outcome: DerivationOutcome
) -> None:
    grouped: dict[tuple[str, str], list[InventoryRow]] = {}
    for row in rows:
        key = (row.block, normalize_spec(row.spec))
        grouped.setdefault(key, []).append(row)
    for grouped_rows in grouped.values():
        prices = {row.unit_price for row in grouped_rows if row.unit_price is not None}
        if len(prices) > 1:
            spec = grouped_rows[0].spec
            outcome.warnings.append(
                ParseIssue(
                    None,
                    "单价",
                    f"规格 {spec} 多行单价不一致，取支数最多行",
                )
            )
