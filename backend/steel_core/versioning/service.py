from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import DatasetType, ImportStatus, PointScope, VersionStatus
from steel_core.db.models.governance import DatasetVersion, ImportBatch


class NoChangesError(Exception):
    """Raised when the imported checksum matches the active version."""


class VersionNotFoundError(Exception):
    """Raised when a version or rollback target cannot be found."""


def compute_checksum(payload: bytes | str | Mapping[str, Any]) -> str:
    if isinstance(payload, bytes):
        data = payload
    elif isinstance(payload, str):
        data = payload.encode("utf-8")
    else:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


async def _lock_dataset(
    session: AsyncSession,
    dataset_type: DatasetType,
    effective_date: date,
    *,
    scope: PointScope = PointScope.PUBLIC,
    owner_user_id: UUID | None = None,
) -> None:
    key = (
        f"{dataset_type.value}:{effective_date.isoformat()}:{scope.value}:"
        f"{owner_user_id or 'public'}"
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": key},
    )


async def get_active_version(
    session: AsyncSession,
    dataset_type: DatasetType,
    effective_date: date,
    *,
    scope: PointScope = PointScope.PUBLIC,
    owner_user_id: UUID | None = None,
) -> DatasetVersion | None:
    return await session.scalar(
        select(DatasetVersion).where(
            DatasetVersion.dataset_type == dataset_type,
            DatasetVersion.effective_date == effective_date,
            DatasetVersion.status == VersionStatus.ACTIVE,
            DatasetVersion.scope == scope,
            DatasetVersion.owner_user_id.is_(None)
            if owner_user_id is None
            else DatasetVersion.owner_user_id == owner_user_id,
        )
    )


async def create_import_batch(
    session: AsyncSession,
    *,
    user_id: UUID,
    dataset_type: DatasetType,
    effective_date: date,
    file_name: str,
    file_hash: str,
    rows_total: int,
    rows_ok: int,
    rows_failed: int,
    errors: list[dict[str, Any]] | None = None,
    status: ImportStatus | None = None,
) -> ImportBatch:
    if status is None:
        status = ImportStatus.SUCCESS if rows_failed == 0 else ImportStatus.FAILED

    batch = ImportBatch(
        user_id=user_id,
        dataset_type=dataset_type,
        effective_date=effective_date,
        file_name=file_name,
        file_hash=file_hash,
        status=status,
        rows_total=rows_total,
        rows_ok=rows_ok,
        rows_failed=rows_failed,
        errors=errors,
    )
    session.add(batch)
    await session.flush()
    return batch


async def create_version(
    session: AsyncSession,
    *,
    dataset_type: DatasetType,
    effective_date: date,
    checksum: str,
    import_batch_id: UUID,
    scope: PointScope = PointScope.PUBLIC,
    owner_user_id: UUID | None = None,
) -> DatasetVersion:
    await _lock_dataset(
        session,
        dataset_type,
        effective_date,
        scope=scope,
        owner_user_id=owner_user_id,
    )

    active = await get_active_version(
        session,
        dataset_type,
        effective_date,
        scope=scope,
        owner_user_id=owner_user_id,
    )
    if active is not None and active.checksum == checksum:
        raise NoChangesError("checksum matches the active version")

    if active is not None:
        active.status = VersionStatus.SUPERSEDED
        await session.flush()

    max_version = await session.scalar(
        select(func.max(DatasetVersion.version_no)).where(
            DatasetVersion.dataset_type == dataset_type,
            DatasetVersion.effective_date == effective_date,
            DatasetVersion.scope == scope,
            DatasetVersion.owner_user_id.is_(None)
            if owner_user_id is None
            else DatasetVersion.owner_user_id == owner_user_id,
        )
    )
    version = DatasetVersion(
        dataset_type=dataset_type,
        effective_date=effective_date,
        scope=scope,
        owner_user_id=owner_user_id,
        version_no=(max_version or 0) + 1,
        status=VersionStatus.ACTIVE,
        import_batch_id=import_batch_id,
        checksum=checksum,
    )
    session.add(version)
    await session.flush()
    return version


async def rollback_version(session: AsyncSession, *, batch_id: UUID) -> DatasetVersion | None:
    batch = await session.get(ImportBatch, batch_id)
    if batch is None:
        raise VersionNotFoundError("import batch not found")

    version = await session.scalar(
        select(DatasetVersion).where(DatasetVersion.import_batch_id == batch_id)
    )
    if version is None or version.status != VersionStatus.ACTIVE:
        raise VersionNotFoundError("active version not found for this import batch")

    await _lock_dataset(
        session,
        version.dataset_type,
        version.effective_date,
        scope=version.scope,
        owner_user_id=version.owner_user_id,
    )

    version.status = VersionStatus.ROLLED_BACK
    await session.flush()

    previous = await session.scalar(
        select(DatasetVersion)
        .where(
            DatasetVersion.dataset_type == version.dataset_type,
            DatasetVersion.effective_date == version.effective_date,
            DatasetVersion.scope == version.scope,
            DatasetVersion.owner_user_id.is_(None)
            if version.owner_user_id is None
            else DatasetVersion.owner_user_id == version.owner_user_id,
            DatasetVersion.version_no < version.version_no,
            DatasetVersion.status != VersionStatus.ROLLED_BACK,
        )
        .order_by(DatasetVersion.version_no.desc())
        .limit(1)
    )
    if previous is not None:
        previous.status = VersionStatus.ACTIVE
        await session.flush()

    batch.status = ImportStatus.ROLLED_BACK
    batch.rolled_back_at = datetime.now(UTC)
    await session.flush()
    return previous


async def cleanup_old_versions(
    session: AsyncSession,
    *,
    dataset_type: DatasetType,
    effective_date: date,
    keep: int = 10,
    scope: PointScope = PointScope.PUBLIC,
    owner_user_id: UUID | None = None,
) -> int:
    versions = (
        await session.scalars(
            select(DatasetVersion)
            .where(
                DatasetVersion.dataset_type == dataset_type,
                DatasetVersion.effective_date == effective_date,
                DatasetVersion.scope == scope,
                DatasetVersion.owner_user_id.is_(None)
                if owner_user_id is None
                else DatasetVersion.owner_user_id == owner_user_id,
            )
            .order_by(DatasetVersion.version_no.desc())
        )
    ).all()

    stale = [version for version in versions[keep:] if version.status != VersionStatus.ACTIVE]
    for version in stale:
        await session.delete(version)
    await session.flush()
    return len(stale)
