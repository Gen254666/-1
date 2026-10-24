from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.db import get_db_session
from app.core.errors import ApiError
from app.core.rate_limit import data_rate_limit
from steel_core.audit.service import write_audit
from steel_core.db.enums import PointScope, Role
from steel_core.db.models.accounts import User
from steel_core.db.models.market import PricePoint
from steel_core.query.service import list_points
from steel_core.quote.private import PrivateQuoteError, upsert_private_quote

router = APIRouter(prefix="/api/points", tags=["points"], dependencies=[Depends(data_rate_limit)])


class PointCreate(BaseModel):
    scope: PointScope = PointScope.PRIVATE
    code: str | None = None
    category: str
    spec: str
    region: str
    source: str = "manual"
    unit: str = "元/吨"


class PointUpdate(BaseModel):
    category: str | None = None
    spec: str | None = None
    region: str | None = None
    source: str | None = None
    unit: str | None = None
    is_active: bool | None = None


class PrivateQuoteCreate(BaseModel):
    quote_date: date
    price: Decimal = Field(gt=0)
    change: Decimal | None = None
    note: str | None = None


def _point_dict(point: PricePoint) -> dict[str, Any]:
    return {
        "id": str(point.id),
        "scope": point.scope.value,
        "owner_user_id": str(point.owner_user_id) if point.owner_user_id else None,
        "code": point.code,
        "category": point.category,
        "spec": point.spec,
        "region": point.region,
        "source": point.source,
        "unit": point.unit,
        "is_active": point.is_active,
    }


@router.get("")
async def list_points_endpoint(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    points = await list_points(session, user_id=user.id)
    return [_point_dict(point) for point in points]


@router.post("", status_code=201)
async def create_point_endpoint(
    payload: PointCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if payload.scope == PointScope.PUBLIC and user.role != Role.ADMIN:
        raise ApiError(403, "AUTH_FORBIDDEN", "只有管理员可以创建公共点位")

    code = payload.code.strip() if payload.code else uuid.uuid4().hex[:12].upper()
    point = PricePoint(
        scope=payload.scope,
        owner_user_id=user.id if payload.scope == PointScope.PRIVATE else None,
        code=code,
        category=payload.category,
        spec=payload.spec,
        region=payload.region,
        source=payload.source,
        unit=payload.unit,
        is_active=True,
    )
    session.add(point)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(409, "DUPLICATE_CODE", "点位编码已存在") from exc

    await write_audit(
        session,
        user_id=user.id,
        action="point.create",
        resource_type="price_point",
        resource_id=str(point.id),
        detail={"code": point.code, "scope": point.scope.value},
    )
    await session.commit()
    return _point_dict(point)


@router.post("/{point_id}/quotes", status_code=201)
async def create_private_quote_endpoint(
    point_id: uuid.UUID,
    payload: PrivateQuoteCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    point = await session.get(PricePoint, point_id)
    if point is None:
        raise ApiError(404, "NOT_FOUND", "点位不存在")
    if point.scope != PointScope.PRIVATE or point.owner_user_id != user.id:
        raise ApiError(403, "AUTH_FORBIDDEN", "只能为自己的私有点位录入报价")

    try:
        version = await upsert_private_quote(
            session,
            user_id=user.id,
            point_id=point_id,
            quote_date=payload.quote_date,
            price=payload.price,
            change=payload.change,
            note=payload.note,
        )
    except PrivateQuoteError as exc:
        raise ApiError(400, "INVALID_ARGUMENT", str(exc)) from exc

    await write_audit(
        session,
        user_id=user.id,
        action="private_quote.upsert",
        resource_type="market_quote",
        resource_id=str(point_id),
        detail={
            "quote_date": payload.quote_date.isoformat(),
            "price": str(payload.price),
        },
    )
    await session.commit()
    return {
        "version_id": str(version.id),
        "point_id": str(point_id),
        "quote_date": payload.quote_date.isoformat(),
        "price": float(payload.price),
        "change": float(payload.change) if payload.change is not None else None,
    }


@router.patch("/{point_id}")
async def update_point_endpoint(
    point_id: uuid.UUID,
    payload: PointUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    point = await session.get(PricePoint, point_id)
    if point is None:
        raise ApiError(404, "NOT_FOUND", "点位不存在")

    if point.scope == PointScope.PUBLIC:
        if user.role != Role.ADMIN:
            raise ApiError(403, "AUTH_FORBIDDEN", "只有管理员可以修改公共点位")
    elif point.owner_user_id != user.id:
        raise ApiError(403, "AUTH_FORBIDDEN", "只能修改自己的私有点位")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(point, field, value)

    await write_audit(
        session,
        user_id=user.id,
        action="point.update",
        resource_type="price_point",
        resource_id=str(point.id),
        detail=payload.model_dump(exclude_unset=True),
    )
    await session.commit()
    return _point_dict(point)


@router.delete("/{point_id}", status_code=204)
async def delete_point_endpoint(
    point_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    point = await session.get(PricePoint, point_id)
    if point is None:
        raise ApiError(404, "NOT_FOUND", "点位不存在")

    if point.scope == PointScope.PUBLIC:
        if user.role != Role.ADMIN:
            raise ApiError(403, "AUTH_FORBIDDEN", "只有管理员可以停用公共点位")
    elif point.owner_user_id != user.id:
        raise ApiError(403, "AUTH_FORBIDDEN", "只能停用自己的私有点位")

    point.is_active = False
    await write_audit(
        session,
        user_id=user.id,
        action="point.deactivate",
        resource_type="price_point",
        resource_id=str(point.id),
    )
    await session.commit()
    return Response(status_code=204)
