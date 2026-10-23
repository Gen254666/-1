from __future__ import annotations

import json
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.providers import CompletionClient
from steel_core.db.models.governance import DailyReport
from steel_core.report.facts import build_daily_report_facts

REPORT_PROMPT = (
    "你是钢材行情分析师。根据给定的事实数据写一份中文日报，"
    "包含行情概览、库存变化、价差、异动提醒。只能使用给定数字，禁止编造。"
    "使用 Markdown，控制在 500 字以内。"
)


async def generate_and_save_report(
    session: AsyncSession,
    *,
    llm: CompletionClient,
    user_id: UUID,
    report_date: date | None = None,
) -> DailyReport:
    facts = await build_daily_report_facts(session, user_id=user_id, report_date=report_date)
    effective_date = facts.as_of or date.today()
    facts_payload = {
        "report_date": effective_date.isoformat(),
        "quotes": [
            {
                "code": quote.code,
                "spec": quote.spec,
                "region": quote.region,
                "price": float(quote.price),
                "change": float(quote.change) if quote.change is not None else None,
            }
            for quote in facts.quotes
        ],
        "inventory": {
            "date": facts.inventory.snapshot_date.isoformat()
            if facts.inventory.snapshot_date
            else None,
            "total": facts.inventory.total,
        },
        "spreads": [
            {
                "name": f"{series.left_code}-{series.right_code}",
                "latest": float(series.latest),
            }
            for series in facts.spreads
        ],
        "anomalies": [anomaly.message for anomaly in facts.anomalies],
        "warnings": facts.warnings,
    }
    narrative = await llm.complete(
        [
            {"role": "system", "content": REPORT_PROMPT},
            {
                "role": "user",
                "content": json.dumps(facts_payload, ensure_ascii=False),
            },
        ]
    )

    max_version = await session.scalar(
        select(func.max(DailyReport.version_no)).where(DailyReport.report_date == effective_date)
    )
    report = DailyReport(
        report_date=effective_date,
        version_no=(max_version or 0) + 1,
        markdown=narrative.strip() or "日报生成失败",
        sources=facts.sources,
        disclaimer=facts.disclaimer,
        model="llm",
        created_by=user_id,
    )
    session.add(report)
    await session.commit()
    return report
