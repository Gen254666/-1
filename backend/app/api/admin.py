from __future__ import annotations

import io
import shutil
import tempfile
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.errors import ApiError
from app.core.http import client_ip
from app.core.rate_limit import import_rate_limit
from app.core.redis import get_redis_client
from app.core.uploads import UploadValidationError, validate_upload
from app.knowledge.gateway import get_knowledge_gateway
from steel_core.analysis.thresholds import (
    AnomalyThresholds,
    ThresholdValidationError,
    load_thresholds,
    parse_thresholds,
)
from steel_core.audit.service import write_audit
from steel_core.cache.service import Cache
from steel_core.db.enums import DatasetType, ImportStatus, Role
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import AppConfig, ImportBatch
from steel_core.ingest.derivation import derive_from_active_snapshot
from steel_core.ingest.service import (
    ImportOutcome,
    ImportValidationError,
    import_inventory,
)
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
        "derived_points_created": outcome.derived_points_created,
        "derived_points_updated": outcome.derived_points_updated,
        "derived_points_deactivated": outcome.derived_points_deactivated,
        "derived_quotes": outcome.derived_quotes,
        "derived_quote_version_id": (
            str(outcome.derived_quote_version_id) if outcome.derived_quote_version_id else None
        ),
        "derived_quote_no_changes": outcome.derived_quote_no_changes,
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

    settings = get_settings()
    if settings.upload_tmp_dir:
        upload_root = Path(settings.upload_tmp_dir)
        upload_root.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix="steel-import-", dir=upload_root))
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix="steel-import-"))
    try:
        temp_dir.chmod(0o700)
    except OSError:
        pass
    basename = Path(filename).name
    path = temp_dir / basename
    path.write_bytes(content)
    try:
        path.chmod(0o600)
    except OSError:
        pass
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
    request: Request,
    file: UploadFile = File(...),
    explicit_date: date | None = Form(None),
    confirm: bool = Form(False),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
    redis: Any | None = Depends(get_redis_client),
    _rate_limit: None = Depends(import_rate_limit),
) -> dict[str, Any]:
    if Path(file.filename or "").suffix.lower() != ".xlsx":
        raise ApiError(400, "INVALID_UPLOAD", "库存导入只支持 .xlsx 文件")
    if not confirm:
        raise ApiError(400, "CONFIRMATION_REQUIRED", "请确认库存导入操作")
    temp_dir, path = await _save_upload(file)
    try:
        outcome = await import_inventory(
            session,
            user_id=user.id,
            path=path,
            explicit_date=explicit_date,
            ip=client_ip(request),
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
    request: Request,
    confirm: bool = Query(False),
    user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
    redis: Any | None = Depends(get_redis_client),
    _rate_limit: None = Depends(import_rate_limit),
) -> dict[str, Any]:
    if not confirm:
        raise ApiError(400, "CONFIRMATION_REQUIRED", "请确认回滚操作")
    batch = await session.get(ImportBatch, batch_id)
    if batch is None:
        raise ApiError(404, "NOT_FOUND", "导入批次不存在")
    if batch.dataset_type == DatasetType.MARKET_QUOTE and batch.file_name.startswith(
        "自动生成-"
    ):
        raise ApiError(
            400,
            "AUTO_BATCH_READONLY",
            "自动生成的行情批次不能单独回滚，请回滚对应库存批次",
        )
    try:
        previous = await rollback_version(session, batch_id=batch_id)
    except VersionNotFoundError as exc:
        raise ApiError(400, "INVALID_ROLLBACK", str(exc)) from exc

    derived_payload: dict[str, Any] | None = None
    invalidate_dates = {batch.effective_date}
    if batch.dataset_type == DatasetType.INVENTORY:
        derive_date = previous.effective_date if previous is not None else batch.effective_date
        invalidate_dates.add(derive_date)
        derived = await derive_from_active_snapshot(
            session,
            user_id=user.id,
            effective_date=derive_date,
            allow_empty=True,
        )
        if derived is not None:
            derived_payload = {
                "effective_date": derive_date.isoformat(),
                "points_created": derived.points_created,
                "points_updated": derived.points_updated,
                "points_deactivated": derived.points_deactivated,
                "quotes_written": derived.quotes_written,
                "quote_version_id": (
                    str(derived.quote_version_id) if derived.quote_version_id else None
                ),
                "warnings": [warning.message for warning in derived.warnings],
            }

    await write_audit(
        session,
        user_id=user.id,
        action="import.rollback",
        resource_type="import_batch",
        resource_id=str(batch.id),
        detail={"effective_date": batch.effective_date.isoformat()},
        ip=client_ip(request),
    )
    await session.commit()
    cache = Cache(redis)
    for invalidate_date in invalidate_dates:
        await cache.invalidate_date(invalidate_date)
    return {
        "batch_id": str(batch.id),
        "previous_version_id": str(previous.id) if previous else None,
        "derived": derived_payload,
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


@admin_router.get("/system/status")
async def system_status_endpoint(
    _user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
    redis: Any | None = Depends(get_redis_client),
) -> dict[str, Any]:
    database = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        database = "error"

    redis_status = "unavailable"
    if redis is not None:
        try:
            await redis.ping()
            redis_status = "ok"
        except Exception:  # noqa: BLE001
            redis_status = "error"

    last_import = await session.scalar(
        select(ImportBatch)
        .where(ImportBatch.status == ImportStatus.SUCCESS)
        .order_by(ImportBatch.created_at.desc())
        .limit(1)
    )

    return {
        "database": database,
        "redis": redis_status,
        "last_successful_import": {
            "id": str(last_import.id),
            "dataset_type": last_import.dataset_type.value,
            "effective_date": last_import.effective_date.isoformat(),
            "created_at": last_import.created_at.isoformat(),
        }
        if last_import is not None
        else None,
        "circuit_breakers": [],
    }


KNOWLEDGE_SUFFIXES = {".md", ".txt", ".pdf", ".docx"}


def _extract_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".txt"}:
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return content.decode("gb18030")
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if suffix == ".docx":
        from docx import Document

        document = Document(io.BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    raise ValueError("不支持的知识库文件类型")


@admin_router.post("/knowledge/documents")
async def upload_knowledge_document_endpoint(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    doc_type: str = Form("policy"),
    effective_date: date | None = Form(None),
    expire_date: date | None = Form(None),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
    gateway: Any = Depends(get_knowledge_gateway),
) -> dict[str, Any]:
    filename = file.filename or "document"
    suffix = Path(filename).suffix.lower()
    if suffix not in KNOWLEDGE_SUFFIXES:
        raise ApiError(400, "INVALID_UPLOAD", "知识库仅支持 md/txt/pdf/docx")
    content = await file.read()
    await file.close()
    try:
        validate_upload(filename, content)
    except UploadValidationError as exc:
        raise ApiError(400, "INVALID_UPLOAD", exc.message) from exc
    try:
        text = _extract_text(filename, content)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(400, "INVALID_UPLOAD", f"文档解析失败: {exc}") from exc
    if not text.strip():
        raise ApiError(400, "INVALID_UPLOAD", "文档没有可提取文本")

    doc_id = uuid.uuid4().hex
    payload = {
        "doc_id": doc_id,
        "title": (title or Path(filename).stem).strip(),
        "text": text,
        "doc_type": doc_type,
        "source": filename,
        "effective_date": effective_date.isoformat() if effective_date else None,
        "expire_date": expire_date.isoformat() if expire_date else None,
    }
    result = await gateway.ingest(admin, payload)
    await write_audit(
        session,
        user_id=admin.id,
        action="knowledge.upload",
        resource_type="knowledge_document",
        resource_id=doc_id,
        detail={"title": payload["title"], "doc_type": doc_type},
    )
    await session.commit()
    return result


@admin_router.get("/knowledge/documents")
async def list_knowledge_documents_endpoint(
    admin: User = Depends(require_admin),
    gateway: Any = Depends(get_knowledge_gateway),
) -> dict[str, Any]:
    return await gateway.list_documents(admin)


@admin_router.delete("/knowledge/documents/{doc_id}")
async def delete_knowledge_document_endpoint(
    doc_id: str,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
    gateway: Any = Depends(get_knowledge_gateway),
) -> dict[str, Any]:
    result = await gateway.delete(admin, doc_id)
    await write_audit(
        session,
        user_id=admin.id,
        action="knowledge.delete",
        resource_type="knowledge_document",
        resource_id=doc_id,
    )
    await session.commit()
    return result


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
    request: Request,
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
        ip=client_ip(request),
    )
    await session.commit()
    return _user_dict(user)


@users_router.patch("/{user_id}")
async def update_user_endpoint(
    user_id: uuid.UUID,
    payload: UserUpdate,
    request: Request,
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
        ip=client_ip(request),
    )
    await session.commit()
    return _user_dict(user)
