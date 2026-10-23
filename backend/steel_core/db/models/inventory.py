from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from steel_core.db.base import Base


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshot"
    __table_args__ = (UniqueConstraint("version_id", name="uq_inventory_snapshot_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_version.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    warehouse: Mapped[str] = mapped_column(String(64), default="昆明宝象库", nullable=False)
    source_file: Mapped[str] = mapped_column(String(255), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InventoryItem(Base):
    __tablename__ = "inventory_item"
    __table_args__ = (
        Index("ix_inventory_item_spec", "spec"),
        Index("ix_inventory_item_block", "block"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("inventory_snapshot.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    block: Mapped[str] = mapped_column(String(16), nullable=False)
    spec: Mapped[str] = mapped_column(String(64), nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    tax_add: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    weight_per_piece: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    pieces: Mapped[int | None] = mapped_column(Integer)
    total_weight: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    price_per_piece: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    packaging: Mapped[str | None] = mapped_column(String(64))
    manufacturer: Mapped[str | None] = mapped_column(String(64))
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
