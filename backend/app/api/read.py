from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin
from app.chat.dependencies import get_llm_router
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.errors import ApiError
from app.core.rate_limit import data_rate_limit
from app.core.redis import get_redis_client
from app.llm.quota import consume_llm_quota
from app.report.service import generate_and_save_report
from steel_core.analysis.service import Anomaly, scan_anomalies
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import AppConfig, DailyReport
from steel_core.query.service import (
    MAX_PAGE_SIZE,
    InventoryPage,
    QueryValidationError,
    QuoteRecord,
    find_inventory_item,
    get_inventory,
    get_price_history,
    get_quotes,
    list_points,
)
from steel_core.quote.service import QuoteValidationError, calculate_quote

router = APIRouter(prefix="/api", tags=["read"], dependencies=[Depends(data_rate_limit)])

DEFAULT_QUOTE_DISCLAIMER = "本报价基于当日库存与行情数据生成，仅供参考，最终成交价以合同为准。"


class QuoteRequest(BaseModel):
    point_id: UUID | None = None
    spec: str | None = None
    pieces: int = Field(gt=0)
    freight: Decimal = Decimal("0")
    processing_fee: Decimal = Decimal("0")
    tax_mode: str = "as_is"


def _quote_dict(quote: QuoteRecord) -> dict[str, Any]:
    return {
        "point_id": str(quote.point_id),
        "code": quote.code,
        "category": quote.category,
        "spec": quote.spec,
        "region": quote.region,
        "quote_date": quote.quote_date.isoformat(),
        "price": float(quote.price),
        "change": float(quote.change) if quote.change is not None else None,
        "source": quote.source,
    }


def _inventory_dict(page: InventoryPage) -> dict[str, Any]:
    return {
        "snapshot_date": page.snapshot_date.isoformat() if page.snapshot_date else None,
        "warehouse": page.warehouse,
        "total": page.total,
        "page": page.page,
        "page_size": page.page_size,
        "items": [
            {
                "block": item.block,
                "spec": item.spec,
                "unit_price": float(item.unit_price) if item.unit_price is not None else None,
                "tax_add": float(item.tax_add) if item.tax_add is not None else None,
                "weight_per_piece": float(item.weight_per_piece)
                if item.weight_per_piece is not None
                else None,
                "pieces": item.pieces,
                "total_weight": float(item.total_weight) if item.total_weight is not None else None,
                "price_per_piece": float(item.price_per_piece)
                if item.price_per_piece is not None
                else None,
                "manufacturer": item.manufacturer,
                "row_no": item.row_no,
            }
            for item in page.items
        ],
    }


def _anomaly_dict(anomaly: Anomaly) -> dict[str, Any]:
    return {
        "kind": anomaly.kind,
        "name": anomaly.name,
        "value": float(anomaly.value),
        "threshold": float(anomaly.threshold),
        "message": anomaly.message,
        "point_id": str(anomaly.point_id) if anomaly.point_id else None,
        "spec": anomaly.spec,
    }


def _report_dict(report: DailyReport) -> dict[str, Any]:
    return {
        "id": str(report.id),
        "report_date": report.report_date.isoformat(),
        "version_no": report.version_no,
        "markdown": report.markdown,
        "sources": report.sources,
        "disclaimer": report.disclaimer,
        "model": report.model,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.get("/quotes")
async def get_quotes_endpoint(
    quote_date: date | None = Query(None, alias="date"),
    category: str | None = None,
    region: str | None = None,
    point_ids: list[UUID] | None = Query(None),
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        result = await get_quotes(
            session,
            user_id=user.id,
            quote_date=quote_date,
            category=category,
            region=region,
            point_ids=point_ids,
            page=page,
            page_size=page_size,
        )
    except QueryValidationError as exc:
        raise ApiError(400, "INVALID_ARGUMENT", str(exc)) from exc
    return {
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
        "items": [_quote_dict(item) for item in result.items],
    }


@router.get("/history")
async def get_history_endpoint(
    point_ids: list[UUID] = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    try:
        series = await get_price_history(
            session,
            user_id=user.id,
            point_ids=point_ids,
            start_date=start_date,
            end_date=end_date,
        )
    except QueryValidationError as exc:
        raise ApiError(400, "INVALID_ARGUMENT", str(exc)) from exc
    return [
        {
            "point_id": str(item.point_id),
            "code": item.code,
            "name": item.name,
            "points": [
                {"date": point.quote_date.isoformat(), "price": float(point.price)}
                for point in item.points
            ],
            "latest": float(item.latest) if item.latest is not None else None,
            "minimum": float(item.minimum) if item.minimum is not None else None,
            "maximum": float(item.maximum) if item.maximum is not None else None,
            "average": float(item.average) if item.average is not None else None,
            "change": float(item.change) if item.change is not None else None,
            "change_pct": float(item.change_pct) if item.change_pct is not None else None,
        }
        for item in series
    ]


@router.get("/inventory")
async def get_inventory_endpoint(
    snapshot_date: date | None = Query(None, alias="date"),
    category: str | None = None,
    page: int = 1,
    page_size: int = 20,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        result = await get_inventory(
            session,
            snapshot_date=snapshot_date,
            category=category,
            page=page,
            page_size=page_size,
        )
    except QueryValidationError as exc:
        raise ApiError(400, "INVALID_ARGUMENT", str(exc)) from exc
    return _inventory_dict(result)


@router.get("/dashboard")
async def dashboard_endpoint(
    quote_date: date | None = Query(None, alias="date"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    quotes = await get_quotes(
        session,
        user_id=user.id,
        quote_date=quote_date,
        page=1,
        page_size=MAX_PAGE_SIZE,
    )
    inventory = await get_inventory(
        session, snapshot_date=quote_date, page_size=MAX_PAGE_SIZE
    )
    anomalies = await scan_anomalies(session, user_id=user.id, quote_date=quote_date)
    as_of = quotes.items[0].quote_date if quotes.items else inventory.snapshot_date
    return {
        "date": as_of.isoformat() if as_of else None,
        "quotes": {
            "total": quotes.total,
            "items": [_quote_dict(item) for item in quotes.items],
        },
        "inventory": _inventory_dict(inventory),
        "anomalies": [_anomaly_dict(item) for item in anomalies],
    }


@router.post("/quote/generate")
async def generate_quote_endpoint(
    payload: QuoteRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    visible_points = await list_points(session, user_id=user.id)
    point = None
    if payload.point_id is not None:
        point = next((item for item in visible_points if item.id == payload.point_id), None)
        if point is None:
            raise ApiError(404, "NOT_FOUND", "点位不存在或无权访问")

    spec = point.spec if point is not None else payload.spec
    if not spec:
        raise ApiError(400, "INVALID_ARGUMENT", "必须提供 point_id 或 spec")

    inventory = await get_inventory(session, page_size=1)
    item = await find_inventory_item(session, spec=spec)
    if item is None or item.unit_price is None or item.weight_per_piece is None:
        raise ApiError(404, "DATA_UNAVAILABLE", f"库存中找不到可用规格: {spec}")

    try:
        calculation = calculate_quote(
            spec=spec,
            unit_price=item.unit_price,
            tax_add=item.tax_add,
            weight_per_piece=item.weight_per_piece,
            pieces=payload.pieces,
            freight=payload.freight,
            processing_fee=payload.processing_fee,
            tax_mode=payload.tax_mode,
        )
    except QuoteValidationError as exc:
        raise ApiError(400, "INVALID_ARGUMENT", str(exc)) from exc

    sources: list[dict[str, Any]] = [
        {
            "type": "inventory",
            "date": inventory.snapshot_date.isoformat() if inventory.snapshot_date else None,
            "warehouse": inventory.warehouse,
            "spec": spec,
        }
    ]
    if point is not None:
        sources.append(
            {
                "type": "point",
                "point_id": str(point.id),
                "code": point.code,
                "region": point.region,
            }
        )

    return {
        "lines": [
            {
                "spec": line.spec,
                "unit_price": float(line.unit_price),
                "tax_add": float(line.tax_add) if line.tax_add is not None else None,
                "weight_per_piece": float(line.weight_per_piece),
                "pieces": line.pieces,
                "price_per_piece": float(line.price_per_piece),
                "subtotal": float(line.subtotal),
                "ton_price": float(line.ton_price),
            }
            for line in calculation.lines
        ],
        "freight": float(calculation.freight),
        "processing_fee": float(calculation.processing_fee),
        "total": float(calculation.total),
        "total_weight": float(calculation.total_weight),
        "average_ton_price": float(calculation.average_ton_price),
        "tax_mode": calculation.tax_mode,
        "warnings": calculation.warnings,
        "sources": sources,
        "disclaimer": await _quote_disclaimer(session),
        "valid_until": date.today().isoformat(),
    }


@router.get("/reports")
async def list_reports_endpoint(
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    reports = list(
        (
            await session.scalars(
                select(DailyReport)
                .order_by(DailyReport.report_date.desc(), DailyReport.version_no.desc())
                .limit(20)
            )
        ).all()
    )
    return [_report_dict(report) for report in reports]


@router.post("/reports/generate")
async def generate_report_endpoint(
    report_date: date | None = Query(None, alias="date"),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
    llm: Any = Depends(get_llm_router),
    redis: Any | None = Depends(get_redis_client),
) -> dict[str, Any]:
    settings = get_settings()
    if not await consume_llm_quota(
        redis, user_id=admin.id, limit=settings.llm_daily_request_limit
    ):
        raise ApiError(429, "LLM_QUOTA_EXCEEDED", "今日日报额度已用完，请明天再试")
    report = await generate_and_save_report(
        session, llm=llm, user_id=admin.id, report_date=report_date
    )
    return _report_dict(report)


@router.get("/reports/{report_date}")
async def get_report_endpoint(
    report_date: date,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    report = await session.scalar(
        select(DailyReport)
        .where(DailyReport.report_date == report_date)
        .order_by(DailyReport.version_no.desc())
        .limit(1)
    )
    if report is None:
        raise ApiError(404, "NOT_FOUND", "日报不存在")
    return _report_dict(report)


async def _quote_disclaimer(session: AsyncSession) -> str:
    config = await session.scalar(select(AppConfig).where(AppConfig.key == "disclaimer"))
    if config is None or not isinstance(config.value, dict):
        return DEFAULT_QUOTE_DISCLAIMER
    disclaimer = config.value.get("quote")
    return str(disclaimer) if disclaimer else DEFAULT_QUOTE_DISCLAIMER
