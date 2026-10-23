from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from steel_core.db.base import Base
from steel_core.db.enums import (
    DatasetType,
    ImportStatus,
    VersionStatus,
    str_enum,
)


class ImportBatch(Base):
    __tablename__ = "import_batch"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False
    )
    dataset_type: Mapped[DatasetType] = mapped_column(
        str_enum(DatasetType, "dataset_type"), nullable=False
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ImportStatus] = mapped_column(
        str_enum(ImportStatus, "import_status"), nullable=False
    )
    rows_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_ok: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DatasetVersion(Base):
    __tablename__ = "dataset_version"
    __table_args__ = (
        UniqueConstraint(
            "dataset_type",
            "effective_date",
            "version_no",
            name="uq_dataset_version_type_date_no",
        ),
        Index(
            "uq_dataset_version_active",
            "dataset_type",
            "effective_date",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_type: Mapped[DatasetType] = mapped_column(
        str_enum(DatasetType, "dataset_type"), nullable=False
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[VersionStatus] = mapped_column(
        str_enum(VersionStatus, "version_status"), nullable=False
    )
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("import_batch.id"), index=True, nullable=False
    )
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DailyReport(Base):
    __tablename__ = "daily_report"
    __table_args__ = (
        UniqueConstraint("report_date", "version_no", name="uq_daily_report_date_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), nullable=False
    )
    disclaimer: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AppConfig(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
