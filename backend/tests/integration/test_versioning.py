import uuid
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import DatasetType, ImportStatus, Role, VersionStatus
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import DatasetVersion, ImportBatch
from steel_core.versioning.service import (
    NoChangesError,
    cleanup_old_versions,
    compute_checksum,
    create_import_batch,
    create_version,
    get_active_version,
    rollback_version,
)

pytestmark = pytest.mark.integration

EFFECTIVE_DATE = date(2026, 10, 23)


async def _make_user(session: AsyncSession) -> User:
    user = User(
        username=f"user-{uuid.uuid4().hex[:8]}",
        password_hash="not-used",
        role=Role.USER,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_batch(session: AsyncSession, user: User) -> ImportBatch:
    return await create_import_batch(
        session,
        user_id=user.id,
        dataset_type=DatasetType.MARKET_QUOTE,
        effective_date=EFFECTIVE_DATE,
        file_name="quotes.csv",
        file_hash=uuid.uuid4().hex,
        rows_total=16,
        rows_ok=16,
        rows_failed=0,
    )


async def _make_version(
    session: AsyncSession, user: User, checksum: str
) -> tuple[DatasetVersion, ImportBatch]:
    batch = await _make_batch(session, user)
    version = await create_version(
        session,
        dataset_type=DatasetType.MARKET_QUOTE,
        effective_date=EFFECTIVE_DATE,
        checksum=checksum,
        import_batch_id=batch.id,
    )
    return version, batch


def test_checksum_is_stable_for_dict_order() -> None:
    assert compute_checksum({"a": 1, "b": 2}) == compute_checksum({"b": 2, "a": 1})
    assert compute_checksum({"a": 1}) != compute_checksum({"a": 2})


async def test_create_version_activates_and_supersedes(session: AsyncSession) -> None:
    user = await _make_user(session)

    first, _ = await _make_version(session, user, "checksum-1")
    second, _ = await _make_version(session, user, "checksum-2")

    assert first.version_no == 1
    assert second.version_no == 2
    assert first.status == VersionStatus.SUPERSEDED
    assert second.status == VersionStatus.ACTIVE

    active = await get_active_version(session, DatasetType.MARKET_QUOTE, EFFECTIVE_DATE)
    assert active is not None
    assert active.id == second.id


async def test_duplicate_checksum_raises(session: AsyncSession) -> None:
    user = await _make_user(session)
    first, _ = await _make_version(session, user, "same-checksum")
    batch = await _make_batch(session, user)

    with pytest.raises(NoChangesError):
        await create_version(
            session,
            dataset_type=DatasetType.MARKET_QUOTE,
            effective_date=EFFECTIVE_DATE,
            checksum="same-checksum",
            import_batch_id=batch.id,
        )

    active = await get_active_version(session, DatasetType.MARKET_QUOTE, EFFECTIVE_DATE)
    assert active is not None
    assert active.id == first.id


async def test_rollback_restores_previous_active(session: AsyncSession) -> None:
    user = await _make_user(session)
    first, _ = await _make_version(session, user, "checksum-1")
    second, second_batch = await _make_version(session, user, "checksum-2")

    previous = await rollback_version(session, batch_id=second_batch.id)

    await session.refresh(first)
    await session.refresh(second)

    assert previous is not None
    assert previous.id == first.id
    assert first.status == VersionStatus.ACTIVE
    assert second.status == VersionStatus.ROLLED_BACK

    batch = await session.get(ImportBatch, second_batch.id)
    assert batch is not None
    assert batch.status == ImportStatus.ROLLED_BACK
    assert batch.rolled_back_at is not None


async def test_rollback_first_version_leaves_no_active(session: AsyncSession) -> None:
    user = await _make_user(session)
    version, batch = await _make_version(session, user, "checksum-1")

    previous = await rollback_version(session, batch_id=batch.id)

    await session.refresh(version)
    assert previous is None
    assert version.status == VersionStatus.ROLLED_BACK
    assert await get_active_version(session, DatasetType.MARKET_QUOTE, EFFECTIVE_DATE) is None


async def test_version_number_keeps_increasing_after_rollback(session: AsyncSession) -> None:
    user = await _make_user(session)
    _, first_batch = await _make_version(session, user, "checksum-1")
    _, second_batch = await _make_version(session, user, "checksum-2")
    await rollback_version(session, batch_id=second_batch.id)

    third, _ = await _make_version(session, user, "checksum-3")

    assert third.version_no == 3
    assert third.status == VersionStatus.ACTIVE


async def test_cleanup_keeps_latest_versions(session: AsyncSession) -> None:
    user = await _make_user(session)
    for index in range(12):
        await _make_version(session, user, f"checksum-{index}")

    deleted = await cleanup_old_versions(
        session,
        dataset_type=DatasetType.MARKET_QUOTE,
        effective_date=EFFECTIVE_DATE,
        keep=10,
    )

    assert deleted == 2
    count = await session.scalar(
        select(func.count())
        .select_from(DatasetVersion)
        .where(
            DatasetVersion.dataset_type == DatasetType.MARKET_QUOTE,
            DatasetVersion.effective_date == EFFECTIVE_DATE,
        )
    )
    assert count == 10

    active = await get_active_version(session, DatasetType.MARKET_QUOTE, EFFECTIVE_DATE)
    assert active is not None
    assert active.version_no == 12
