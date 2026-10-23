from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.analysis.service import Anomaly, SpreadSeries, calculate_spread, scan_anomalies
from steel_core.db.enums import PointScope
from steel_core.db.models.governance import AppConfig
from steel_core.db.models.market import PricePoint
from steel_core.query.service import (
    InventoryPage,
    QuoteRecord,
    get_inventory,
    get_quotes,
    list_points,
)

SPREAD_PAIRS = [
    ("REJUAN_4.75X1500_KUNMING", "REJUAN_4.75X1500_CHENGDU", "热卷 昆明-成都"),
    (
        "LUOWENG_HBR400E_PHI20_KUNMING",
        "LUOWENG_HBR400E_PHI20_GUIYANG",
        "螺纹 昆明-贵阳",
    ),
    ("FANG_100X100X2.5_KUNMING", "REJUAN_4.75X1500_KUNMING", "方管-热卷价差"),
]

DEFAULT_REPORT_DISCLAIMER = "本报告基于公开与内部数据整理，仅供参考，不构成投资或交易建议。"


@dataclass
class ReportFacts:
    as_of: date | None
    quotes: list[QuoteRecord]
    inventory: InventoryPage
    spreads: list[SpreadSeries]
    anomalies: list[Anomaly]
    sources: list[dict[str, Any]] = field(default_factory=list)
    disclaimer: str = DEFAULT_REPORT_DISCLAIMER
    warnings: list[str] = field(default_factory=list)


async def build_daily_report_facts(
    session: AsyncSession,
    *,
    user_id: UUID,
    report_date: date | None = None,
) -> ReportFacts:
    quotes = await _load_quotes(session, user_id=user_id, report_date=report_date)
    inventory = await get_inventory(session, page_size=100)
    anomalies = await scan_anomalies(session, user_id=user_id, quote_date=report_date)

    public_ids = set(
        (
            await session.scalars(
                select(PricePoint.id).where(
                    PricePoint.scope == PointScope.PUBLIC,
                    PricePoint.is_active.is_(True),
                )
            )
        ).all()
    )
    quotes = [quote for quote in quotes if quote.point_id in public_ids]
    anomalies = [
        anomaly
        for anomaly in anomalies
        if anomaly.point_id is None or anomaly.point_id in public_ids
    ]

    as_of = report_date
    if as_of is None and quotes:
        as_of = quotes[0].quote_date
    if as_of is None:
        as_of = inventory.snapshot_date

    points = await list_points(session, user_id=user_id)
    point_by_code = {point.code: point for point in points}
    spreads: list[SpreadSeries] = []
    if as_of is not None:
        for left_code, right_code, _ in SPREAD_PAIRS:
            left = point_by_code.get(left_code)
            right = point_by_code.get(right_code)
            if left is None or right is None:
                continue
            series = await calculate_spread(
                session,
                user_id=user_id,
                left_point_id=left.id,
                right_point_id=right.id,
                start_date=as_of - timedelta(days=30),
                end_date=as_of,
            )
            if series is not None:
                spreads.append(series)

    sources: list[dict[str, Any]] = [
        {
            "type": "quote",
            "code": quote.code,
            "date": quote.quote_date.isoformat(),
            "source": quote.source,
        }
        for quote in quotes
    ]
    if inventory.snapshot_date is not None:
        sources.append(
            {
                "type": "inventory",
                "date": inventory.snapshot_date.isoformat(),
                "warehouse": inventory.warehouse,
            }
        )

    warnings: list[str] = []
    if not quotes:
        warnings.append("当日无报价数据")
    if inventory.snapshot_date is None:
        warnings.append("当日无库存数据")

    return ReportFacts(
        as_of=as_of,
        quotes=quotes,
        inventory=inventory,
        spreads=spreads,
        anomalies=anomalies,
        sources=sources,
        disclaimer=await _load_report_disclaimer(session),
        warnings=warnings,
    )


async def _load_quotes(
    session: AsyncSession, *, user_id: UUID, report_date: date | None
) -> list[QuoteRecord]:
    items: list[QuoteRecord] = []
    page = 1
    while True:
        result = await get_quotes(
            session,
            user_id=user_id,
            quote_date=report_date,
            page=page,
            page_size=100,
        )
        items.extend(result.items)
        if len(items) >= result.total or not result.items:
            break
        page += 1
    return items


async def _load_report_disclaimer(session: AsyncSession) -> str:
    config = await session.scalar(select(AppConfig).where(AppConfig.key == "disclaimer"))
    if config is None or not isinstance(config.value, dict):
        return DEFAULT_REPORT_DISCLAIMER
    disclaimer = config.value.get("report")
    return str(disclaimer) if disclaimer else DEFAULT_REPORT_DISCLAIMER
