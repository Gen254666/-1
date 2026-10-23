from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from steel_core.db.base import Base
from steel_core.db.enums import PointScope, str_enum


class PricePoint(Base):
    __tablename__ = "price_point"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'public' AND owner_user_id IS NULL) "
            "OR (scope = 'private' AND owner_user_id IS NOT NULL)",
            name="owner_scope",
        ),
        Index(
            "uq_price_point_public_code",
            "code",
            unique=True,
            postgresql_where=text("scope = 'public'"),
        ),
        Index(
            "uq_price_point_private_owner_code",
            "owner_user_id",
            "code",
            unique=True,
            postgresql_where=text("scope = 'private'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[PointScope] = mapped_column(str_enum(PointScope, "point_scope"), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    spec: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="mysteel", nullable=False)
    unit: Mapped[str] = mapped_column(String(16), default="元/吨", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MarketQuote(Base):
    __tablename__ = "market_quote"
    __table_args__ = (
        UniqueConstraint(
            "version_id",
            "point_id",
            "quote_date",
            name="uq_market_quote_version_point_date",
        ),
        Index("ix_market_quote_point_date", "point_id", "quote_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dataset_version.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    point_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("price_point.id"), index=True, nullable=False
    )
    quote_date: Mapped[date] = mapped_column(Date, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    change: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    source: Mapped[str] = mapped_column(String(32), default="mysteel", nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
