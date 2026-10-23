from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import DatasetType, PointScope
from steel_core.db.models.market import MarketQuote, PricePoint
from steel_core.versioning.service import (
    NoChangesError,
    compute_checksum,
    create_import_batch,
    create_version,
    get_active_version,
)


class PrivateQuoteError(Exception):
    pass


def _row_key(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)


async def upsert_private_quote(
    session: AsyncSession,
    *,
    user_id: UUID,
    point_id: UUID,
    quote_date: date,
    price: Decimal,
    change: Decimal | None = None,
    note: str | None = None,
) -> Any:
    point = await session.get(PricePoint, point_id)
    if point is None:
        raise PrivateQuoteError("点位不存在")
    if point.scope != PointScope.PRIVATE or point.owner_user_id != user_id:
        raise PrivateQuoteError("只能为自己的私有点位录入报价")

    active = await get_active_version(
        session,
        DatasetType.MARKET_QUOTE,
        quote_date,
        scope=PointScope.PRIVATE,
        owner_user_id=user_id,
    )
    existing = (
        list(
            (
                await session.scalars(
                    select(MarketQuote).where(MarketQuote.version_id == active.id)
                )
            ).all()
        )
        if active is not None
        else []
    )

    rows: list[dict[str, Any]] = [
        {
            "point_id": str(row.point_id),
            "quote_date": row.quote_date,
            "price": row.price,
            "change": row.change,
            "source": row.source,
            "note": row.note,
        }
        for row in existing
        if row.point_id != point_id
    ]
    rows.append(
        {
            "point_id": str(point_id),
            "quote_date": quote_date,
            "price": price,
            "change": change,
            "source": "manual",
            "note": note,
        }
    )
    checksum = compute_checksum({"private_rows": sorted(rows, key=_row_key)})

    batch = await create_import_batch(
        session,
        user_id=user_id,
        dataset_type=DatasetType.MARKET_QUOTE,
        effective_date=quote_date,
        file_name="private_quote",
        file_hash=uuid.uuid4().hex,
        rows_total=len(rows),
        rows_ok=len(rows),
        rows_failed=0,
    )

    try:
        version = await create_version(
            session,
            dataset_type=DatasetType.MARKET_QUOTE,
            effective_date=quote_date,
            checksum=checksum,
            import_batch_id=batch.id,
            scope=PointScope.PRIVATE,
            owner_user_id=user_id,
        )
    except NoChangesError:
        current = await get_active_version(
            session,
            DatasetType.MARKET_QUOTE,
            quote_date,
            scope=PointScope.PRIVATE,
            owner_user_id=user_id,
        )
        await session.commit()
        if current is None:
            raise PrivateQuoteError("私有报价版本不存在") from None
        return current

    for row in existing:
        if row.point_id == point_id:
            continue
        session.add(
            MarketQuote(
                version_id=version.id,
                point_id=row.point_id,
                quote_date=row.quote_date,
                price=row.price,
                change=row.change,
                source=row.source,
                note=row.note,
            )
        )
    session.add(
        MarketQuote(
            version_id=version.id,
            point_id=point_id,
            quote_date=quote_date,
            price=price,
            change=change,
            source="manual",
            note=note,
        )
    )
    await session.commit()
    return version
