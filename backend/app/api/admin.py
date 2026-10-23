from __future__ import annotations

import shutil
import tempfile
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.core.db import get_db_session
from app.core.errors import ApiError
from app.core.redis import get_redis_client
from app.core.uploads import UploadValidationError, validate_upload
from steel_core.analysis.thresholds import (
    AnomalyThresholds,
    ThresholdValidationError,
    load_thresholds,
    parse_thresholds,
)
from steel_core.audit.service import write_audit
from steel_core.cache.service import Cache
from steel_core.db.enums import Role
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import AppConfig, ImportBatch
from steel_core.ingest.service import (
    ImportOutcome,
    ImportValidationError,
    import_inventory,
    import_quotes,
)
from steel_core.query.service import list_points
from steel_core.security import hash_password
from steel_core.versioning.service import VersionNotFoundError, rollback_version

admin_router = APIRouter(prefix="/api/admin", tags=["admin"])
users_router = APIRouter(prefix="/api/users", tags=["users"])


class AnomalyConfigPayload(BaseModel):
    daily_change_pct: float
    consecutive_days: int
    inventory_deviation_pct: float
    low_stock_pieces: int


class UserCreate(BaseModel):
    username: str
    password: str = Field(min_length=8)
    role: Role = Role.USER


class UserUpdate(BaseModel):
    is_active: bool | None = None
    role: Role | None = None


def _outcome_dict(outcome: ImportOutcome) -> dict[str, Any]:
    return {
        "batch_id": str(outcome.batch_id),
        "version_id": str(outcome.version_id) if outcome.version_id else None,
        "effective_date": outcome.effective_date.isoformat(),
        "rows_ok": outcome.rows_ok,
        "rows_failed": outcome.rows_failed,
        "no_changes": outcome.no_changes,
        "warnings": [warning.message for warning in outcome.warnings],
    }


def _thresholds_dict(thresholds: AnomalyThresholds) -> dict[str, Any]:
    return {
        "daily_change_pct": float(thresholds.daily_change_pct),
        "consecutive_days": thresholds.consecutive_days,
        "inventory_deviation_pct": float(thresholds.inventory_deviation_pct),
        "low_stock_pieces": thresholds.low_stock_pieces,
    }


def _user_dict(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


async def _save_upload(file: UploadFile) -> tuple[Path, Path]:
    filename = file.filename or "upload"
    content = await file.read()
    try:
        validate_upload(filename, content)
    except UploadValidationError as exc:
        await file.close()
        raise ApiError(400, "INVALID_UPLOAD", exc.message) from exc

    temp_dir = Path(tempfile.mkdtemp(prefix="steel-import-"))
    basename = Path(filename).name
    path = temp_dir / f"{uuid.uuid4().hex[:8]}_{basename}"
    path.write_bytes(content)
    await file.close()
    return temp_dir, path


@admin_router.get("/imports")
async def list_imports_endpoint(
    _user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    batches = list(
        (
            await session.scalars(
                select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(50)
            )
        ).all()
    )
    return [
        {
            "id": str(batch.id),
            "dataset_type": batch.dataset_type.value,
            "effective_date": batch.effective_date.isoformat(),
            "file_name": batch.file_name,
            "status": batch.status.value,
            "rows_total": batch.rows_total,
            "rows_ok": batch.rows_ok,
            "rows_failed": batch.rows_failed,
            "errors": batch.errors or [],
            "created_at": batch.created_at.isoformat(),
            "rolled_back_at": batch.rolled_back_at.isoformat() if batch.rolled_back_at else None,
        }
        for batch in batches
    ]


@admin_router.post("/import/inventory")
async def import_inventory_endpoint(
    file: UploadFile = File(...),
    explicit_date: date | None = Form(None),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
    redis: Any | None = Depends(get_redis_client),
) -> dict[str, Any]:
    temp_dir, path = await _save_upload(file)
    try:
        outcome = await import_inventory(
            session, user_id=user.id, path=path, explicit_date=explicit_date
        )
    except ImportValidationError as exc:
        raise ApiError(
            400,
            "IMPORT_VALIDATION_FAILED",
            "导入校验失败",
            {
                "batch_id": str(exc.batch_id),
                "errors": [
                    {"row_no": error.row_no, "field": error.field, "message": error.message}
                    for error in exc.errors
                ],
            },
        ) from exc
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    await Cache(redis).invalidate_date(outcome.effective_date)
    return _outcome_dict(outcome)


@admin_router.post("/import/quotes")
async def import_quotes_endpoint(
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
    redis: Any | None = Depends(get_redis_client),
) -> dict[str, Any]:
    points = await list_points(session, user_id=user.id)
    allowed_points = {point.code: point.id for point in points}
    temp_dir, path = await _save_upload(file)
    try:
        outcome = await import_quotes(
            session,
            user_id=user.id,
            path=path,
            allowed_points=allowed_points,
            expected_point_codes=set(allowed_points),
        )
    except ImportValidationError as exc:
        raise ApiError(
            400,
            "IMPORT_VALIDATION_FAILED",
            "导入校验失败",
            {
                "batch_id": str(exc.batch_id),
                "errors": [
                    {"row_no": error.row_no, "field": error.field, "message": error.message}
                    for error in exc.errors
                ],
            },
        ) from exc
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    await Cache(redis).invalidate_date(outcome.effective_date)
    return _outcome_dict(outcome)


@admin_router.post("/imports/{batch_id}/rollback")
async def rollback_import_endpoint(
    batch_id: uuid.UUID,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
    redis: Any | None = Depends(get_redis_client),
) -> dict[str, Any]:
    batch = await session.get(ImportBatch, batch_id)
    if batch is None:
        raise ApiError(404, "NOT_FOUND", "导入批次不存在")
    try:
        previous = await rollback_version(session, batch_id=batch_id)
    except VersionNotFoundError as exc:
        raise ApiError(400, "INVALID_ROLLBACK", str(exc)) from exc

    await write_audit(
        session,
        user_id=user.id,
        action="import.rollback",
        resource_type="import_batch",
        resource_id=str(batch.id),
        detail={"effective_date": batch.effective_date.isoformat()},
    )
    await session.commit()
    await Cache(redis).invalidate_date(batch.effective_date)
    return {
        "batch_id": str(batch.id),
        "previous_version_id": str(previous.id) if previous else None,
    }


@admin_router.get("/config/anomaly")
async def get_anomaly_config_endpoint(
    _user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return _thresholds_dict(await load_thresholds(session))


@admin_router.put("/config/anomaly")
async def update_anomaly_config_endpoint(
    payload: AnomalyConfigPayload,
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        thresholds = parse_thresholds(payload.model_dump())
    except ThresholdValidationError as exc:
        raise ApiError(400, "INVALID_ARGUMENT", str(exc)) from exc

    value = _thresholds_dict(thresholds)
    config = await session.scalar(select(AppConfig).where(AppConfig.key == "anomaly"))
    if config is None:
        session.add(AppConfig(key="anomaly", value=value, updated_by=user.id))
    else:
        config.value = value
        config.updated_by = user.id
    await write_audit(
        session,
        user_id=user.id,
        action="config.anomaly.update",
        resource_type="app_config",
        resource_id="anomaly",
        detail=value,
    )
    await session.commit()
    return value


@users_router.get("")
async def list_users_endpoint(
    _user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    users = list((await session.scalars(select(User).order_by(User.username))).all())
    return [_user_dict(user) for user in users]


@users_router.post("", status_code=201)
async def create_user_endpoint(
    payload: UserCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    existing = await session.scalar(select(User).where(User.username == payload.username))
    if existing is not None:
        raise ApiError(409, "DUPLICATE_USERNAME", "用户名已存在")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        must_change_password=True,
    )
    session.add(user)
    await session.flush()
    await write_audit(
        session,
        user_id=admin.id,
        action="user.create",
        resource_type="user",
        resource_id=str(user.id),
        detail={"username": user.username, "role": user.role.value},
    )
    await session.commit()
    return _user_dict(user)


@users_router.patch("/{user_id}")
async def update_user_endpoint(
    user_id: uuid.UUID,
    payload: UserUpdate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(404, "NOT_FOUND", "用户不存在")

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    await write_audit(
        session,
        user_id=admin.id,
        action="user.update",
        resource_type="user",
        resource_id=str(user.id),
        detail=changes,
    )
    await session.commit()
    return _user_dict(user)
