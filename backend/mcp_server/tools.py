from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from mcp_server.context import UserContext
from steel_core.analysis.service import (
    Anomaly,
    SpreadSeries,
    calculate_spread,
)
from steel_core.analysis.service import (
    scan_anomalies as scan_anomalies_service,
)
from steel_core.db.enums import Role
from steel_core.db.models.governance import AppConfig, DailyReport
from steel_core.knowledge.service import get_client as get_knowledge_client
from steel_core.knowledge.service import search_knowledge
from steel_core.query.service import (
    InventoryPage,
    QueryValidationError,
    QuoteRecord,
    list_points,
)
from steel_core.query.service import (
    get_inventory as query_inventory,
)
from steel_core.query.service import (
    get_price_history as query_price_history,
)
from steel_core.query.service import (
    get_quotes as query_quotes,
)
from steel_core.quote.service import QuoteValidationError, calculate_quote
from steel_core.report.facts import ReportFacts, build_daily_report_facts

DEFAULT_QUOTE_DISCLAIMER = "本报价基于当日库存与行情数据生成，仅供参考，最终成交价以合同为准。"


def _meta(
    *,
    as_of: date | None = None,
    source: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "source": source,
        "cached": False,
        "warnings": warnings or [],
    }


def _ok(
    summary: str,
    artifact_type: str,
    payload: Any,
    *,
    as_of: date | None = None,
    source: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "summary": summary,
        "artifact": {"type": artifact_type, "payload": payload},
        "meta": _meta(as_of=as_of, source=source, warnings=warnings),
        "error": None,
    }


def _error(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "summary": "",
        "artifact": None,
        "meta": _meta(),
        "error": {"code": code, "message": message, "details": details or {}, "retryable": False},
    }


def _quote_payload(quote: QuoteRecord) -> dict[str, Any]:
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


def _inventory_payload(page: InventoryPage) -> dict[str, Any]:
    return {
        "snapshot_date": page.snapshot_date.isoformat() if page.snapshot_date else None,
        "warehouse": page.warehouse,
        "total": page.total,
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
                "price_per_piece": float(item.price_per_piece)
                if item.price_per_piece is not None
                else None,
                "manufacturer": item.manufacturer,
                "row_no": item.row_no,
            }
            for item in page.items
        ],
    }


def _anomaly_payload(anomaly: Anomaly) -> dict[str, Any]:
    return {
        "kind": anomaly.kind,
        "name": anomaly.name,
        "value": float(anomaly.value),
        "threshold": float(anomaly.threshold),
        "message": anomaly.message,
        "point_id": str(anomaly.point_id) if anomaly.point_id else None,
        "spec": anomaly.spec,
    }


def _spread_payload(series: SpreadSeries) -> dict[str, Any]:
    return {
        "left_code": series.left_code,
        "right_code": series.right_code,
        "points": [
            {"date": point.quote_date.isoformat(), "value": float(point.value)}
            for point in series.points
        ],
        "latest": float(series.latest),
        "minimum": float(series.minimum),
        "maximum": float(series.maximum),
        "average": float(series.average),
    }


def _chart_payload(
    title: str,
    series: list[dict[str, Any]],
    as_of: date | None,
) -> dict[str, Any]:
    return {
        "series": series,
        "chart": {
            "kind": "line",
            "title": title,
            "x_label": "日期",
            "y_label": "元/吨",
        },
        "meta": {"as_of": as_of.isoformat() if as_of else None},
    }


async def get_meta(
    session: AsyncSession, ctx: UserContext, *, category: str | None = None
) -> dict[str, Any]:
    points = await list_points(session, user_id=ctx.user_id, category=category)
    latest_quotes = await query_quotes(
        session, user_id=ctx.user_id, category=category, page=1, page_size=1
    )
    inventory = await query_inventory(session, category=category, page_size=1)
    latest_quote_date = latest_quotes.items[0].quote_date if latest_quotes.items else None
    payload = {
        "columns": ["code", "category", "spec", "region", "source", "unit", "point_id"],
        "rows": [
            {
                "point_id": str(point.id),
                "code": point.code,
                "category": point.category,
                "spec": point.spec,
                "region": point.region,
                "source": point.source,
                "unit": point.unit,
            }
            for point in points
        ],
    }
    return _ok(
        f"可用点位 {len(points)} 个；最新报价日期 {latest_quote_date or '无'}；"
        f"最新库存日期 {inventory.snapshot_date or '无'}",
        "table",
        payload,
        as_of=latest_quote_date,
        source="mysteel",
    )


async def get_quotes(
    session: AsyncSession,
    ctx: UserContext,
    *,
    point_ids: list[UUID] | None = None,
    category: str | None = None,
    region: str | None = None,
    quote_date: date | None = None,
    page: int = 1,
    page_size: int = 20,
    use_cache: bool = True,
) -> dict[str, Any]:
    try:
        result = await query_quotes(
            session,
            user_id=ctx.user_id,
            quote_date=quote_date,
            category=category,
            region=region,
            point_ids=point_ids,
            page=page,
            page_size=page_size,
        )
    except QueryValidationError as exc:
        return _error("INVALID_ARGUMENT", str(exc))
    as_of = result.items[0].quote_date if result.items else quote_date
    summary = f"共 {result.total} 条报价"
    if result.items:
        summary += f"，示例：{result.items[0].code} {result.items[0].price} 元/吨"
    return _ok(
        summary,
        "cards",
        {"items": [_quote_payload(item) for item in result.items]},
        as_of=as_of,
        source=result.items[0].source if result.items else None,
    )


async def get_price_history(
    session: AsyncSession,
    ctx: UserContext,
    *,
    point_ids: list[UUID],
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    end_date = end_date or date.today()
    start_date = start_date or end_date - timedelta(days=30)
    try:
        series = await query_price_history(
            session,
            user_id=ctx.user_id,
            point_ids=point_ids,
            start_date=start_date,
            end_date=end_date,
        )
    except QueryValidationError as exc:
        return _error("INVALID_ARGUMENT", str(exc))
    if not series:
        return _error("DATA_UNAVAILABLE", "区间内没有可用历史数据")
    chart_series = [
        {
            "name": item.name,
            "x": [point.quote_date.isoformat() for point in item.points],
            "y": [float(point.price) for point in item.points],
            "unit": "元/吨",
        }
        for item in series
    ]
    latest_dates = [item.points[-1].quote_date for item in series if item.points]
    as_of = max(latest_dates) if latest_dates else None
    summary = "；".join(
        f"{item.name} 最新 {item.latest}，区间涨跌 {item.change}" for item in series
    )
    return _ok(
        summary,
        "chart",
        _chart_payload("价格走势", chart_series, as_of),
        as_of=as_of,
        source="mysteel",
    )


async def compare_spread(
    session: AsyncSession,
    ctx: UserContext,
    *,
    left_point_id: UUID,
    right_point_id: UUID,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    end_date = end_date or date.today()
    start_date = start_date or end_date - timedelta(days=30)
    try:
        series = await calculate_spread(
            session,
            user_id=ctx.user_id,
            left_point_id=left_point_id,
            right_point_id=right_point_id,
            start_date=start_date,
            end_date=end_date,
        )
    except QueryValidationError as exc:
        return _error("INVALID_ARGUMENT", str(exc))
    if series is None:
        return _error("DATA_UNAVAILABLE", "价差计算缺少点位数据或无权访问")
    payload = _spread_payload(series)
    chart_series = [
        {
            "name": f"{series.left_code} - {series.right_code}",
            "x": [point["date"] for point in payload["points"]],
            "y": [point["value"] for point in payload["points"]],
            "unit": "元/吨",
        }
    ]
    as_of = series.points[-1].quote_date if series.points else None
    return _ok(
        f"{series.left_code} - {series.right_code} 最新价差 {series.latest} 元/吨",
        "chart",
        _chart_payload("价差走势", chart_series, as_of),
        as_of=as_of,
        source="mysteel",
    )


async def scan_anomalies_tool(
    session: AsyncSession,
    ctx: UserContext,
    *,
    quote_date: date | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    try:
        anomalies = await scan_anomalies_service(
            session, user_id=ctx.user_id, quote_date=quote_date, category=category
        )
    except QueryValidationError as exc:
        return _error("INVALID_ARGUMENT", str(exc))
    as_of = quote_date
    if anomalies and anomalies[0].point_id is None:
        as_of = quote_date
    return _ok(
        f"检测到 {len(anomalies)} 条异动",
        "table",
        {
            "columns": ["kind", "name", "value", "threshold", "message"],
            "rows": [_anomaly_payload(anomaly) for anomaly in anomalies],
        },
        as_of=as_of,
        source="internal",
    )


async def get_inventory(
    session: AsyncSession,
    ctx: UserContext,
    *,
    snapshot_date: date | None = None,
    category: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    try:
        result = await query_inventory(
            session,
            snapshot_date=snapshot_date,
            category=category,
            page=page,
            page_size=page_size,
        )
    except QueryValidationError as exc:
        return _error("INVALID_ARGUMENT", str(exc))
    return _ok(
        f"库存 {result.total} 条，仓库 {result.warehouse or '无'}",
        "cards",
        _inventory_payload(result),
        as_of=result.snapshot_date,
        source="inventory",
    )


async def generate_quote_tool(
    session: AsyncSession,
    ctx: UserContext,
    *,
    pieces: int,
    point_id: UUID | None = None,
    spec: str | None = None,
    freight: Decimal = Decimal("0"),
    processing_fee: Decimal = Decimal("0"),
    tax_mode: str = "as_is",
) -> dict[str, Any]:
    points = await list_points(session, user_id=ctx.user_id)
    point = None
    if point_id is not None:
        point = next((item for item in points if item.id == point_id), None)
        if point is None:
            return _error("NOT_FOUND", "点位不存在或无权访问")
    chosen_spec = point.spec if point is not None else spec
    if not chosen_spec:
        return _error("INVALID_ARGUMENT", "必须提供 point_id 或 spec")

    inventory = await query_inventory(session, page_size=100)
    item = next(
        (
            entry
            for entry in inventory.items
            if entry.spec == chosen_spec
            and entry.unit_price is not None
            and entry.weight_per_piece is not None
        ),
        None,
    )
    if item is None or item.unit_price is None or item.weight_per_piece is None:
        return _error("DATA_UNAVAILABLE", f"库存中找不到可用规格: {chosen_spec}")

    try:
        calculation = calculate_quote(
            spec=chosen_spec,
            unit_price=item.unit_price,
            tax_add=item.tax_add,
            weight_per_piece=item.weight_per_piece,
            pieces=pieces,
            freight=freight,
            processing_fee=processing_fee,
            tax_mode=tax_mode,
        )
    except QuoteValidationError as exc:
        return _error("INVALID_ARGUMENT", str(exc))

    sources: list[dict[str, Any]] = [
        {
            "type": "inventory",
            "date": inventory.snapshot_date.isoformat() if inventory.snapshot_date else None,
            "warehouse": inventory.warehouse,
            "spec": chosen_spec,
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

    payload = {
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
    return _ok(
        f"{chosen_spec} {pieces} 支，合计 {calculation.total} 元",
        "quote",
        payload,
        as_of=inventory.snapshot_date,
        source="inventory",
        warnings=calculation.warnings,
    )


async def get_daily_report(
    session: AsyncSession, ctx: UserContext, *, report_date: date
) -> dict[str, Any]:
    report = await session.scalar(
        select(DailyReport)
        .where(DailyReport.report_date == report_date)
        .order_by(DailyReport.version_no.desc())
        .limit(1)
    )
    if report is None:
        return _error("NOT_FOUND", "日报不存在")
    return _ok(
        f"{report_date} 日报，版本 {report.version_no}",
        "report",
        {
            "report_date": report.report_date.isoformat(),
            "version_no": report.version_no,
            "markdown": report.markdown,
            "sources": report.sources,
            "disclaimer": report.disclaimer,
            "model": report.model,
            "as_of": report.report_date.isoformat(),
        },
        as_of=report.report_date,
        source="report",
    )


async def generate_daily_report(
    session: AsyncSession, ctx: UserContext, *, report_date: date | None = None
) -> dict[str, Any]:
    if ctx.role != Role.ADMIN:
        return _error("PERMISSION_DENIED", "普通用户不能生成日报")
    facts: ReportFacts = await build_daily_report_facts(
        session, user_id=ctx.user_id, report_date=report_date
    )
    payload = {
        "report_date": facts.as_of.isoformat() if facts.as_of else None,
        "quotes": [_quote_payload(quote) for quote in facts.quotes],
        "inventory": _inventory_payload(facts.inventory),
        "spreads": [_spread_payload(series) for series in facts.spreads],
        "anomalies": [_anomaly_payload(anomaly) for anomaly in facts.anomalies],
        "sources": facts.sources,
        "disclaimer": facts.disclaimer,
        "as_of": facts.as_of.isoformat() if facts.as_of else None,
        "warnings": facts.warnings,
    }
    return _ok(
        f"日报事实稿：报价 {len(facts.quotes)} 条，库存 "
        f"{facts.inventory.total} 条，异动 {len(facts.anomalies)} 条",
        "report",
        payload,
        as_of=facts.as_of,
        source="internal",
        warnings=facts.warnings,
    )


@lru_cache
def _knowledge_client() -> Any:
    return get_knowledge_client(get_settings().chroma_path)


def search_knowledge_tool(
    ctx: UserContext,
    *,
    query: str,
    collections: list[str] | None = None,
    top_k: int = 5,
    include_expired: bool = False,
    client: Any | None = None,
    embedder: Any | None = None,
) -> dict[str, Any]:
    if include_expired and ctx.role != Role.ADMIN:
        return _error("PERMISSION_DENIED", "只有管理员可以检索过期文档")
    if top_k < 1 or top_k > 10:
        return _error("INVALID_ARGUMENT", "top_k 必须在 1 到 10 之间")

    knowledge_client = client or _knowledge_client()
    try:
        citations = search_knowledge(
            knowledge_client,
            query=query,
            collections=collections,
            user_id=str(ctx.user_id),
            embedder=embedder,
            top_k=top_k,
            include_expired=include_expired,
        )
    except PermissionError as exc:
        return _error("PERMISSION_DENIED", str(exc))

    payload = {
        "citations": [
            {
                "index": citation.index,
                "doc_id": citation.doc_id,
                "title": citation.title,
                "doc_type": citation.doc_type,
                "effective_date": citation.effective_date,
                "expire_date": citation.expire_date,
                "snippet": citation.snippet,
                "score": citation.score,
            }
            for citation in citations
        ]
    }
    if citations:
        summary = "；".join(f"[{citation.index}] {citation.title}" for citation in citations)
    else:
        summary = "未检索到相关内容"
    return _ok(summary, "text", payload, source="knowledge")


async def _quote_disclaimer(session: AsyncSession) -> str:
    config = await session.scalar(select(AppConfig).where(AppConfig.key == "disclaimer"))
    if config is None or not isinstance(config.value, dict):
        return DEFAULT_QUOTE_DISCLAIMER
    disclaimer = config.value.get("quote")
    return str(disclaimer) if disclaimer else DEFAULT_QUOTE_DISCLAIMER
