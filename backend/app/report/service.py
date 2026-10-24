from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.providers import AllProvidersFailed, CompletionClient
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
    model = "llm"
    try:
        narrative = await llm.complete(
            [
                {"role": "system", "content": REPORT_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(facts_payload, ensure_ascii=False),
                },
            ]
        )
        if not narrative.strip():
            narrative = _facts_markdown(facts_payload, facts.disclaimer)
            model = "facts-only"
    except AllProvidersFailed:
        narrative = _facts_markdown(facts_payload, facts.disclaimer)
        model = "facts-only"

    max_version = await session.scalar(
        select(func.max(DailyReport.version_no)).where(DailyReport.report_date == effective_date)
    )
    report = DailyReport(
        report_date=effective_date,
        version_no=(max_version or 0) + 1,
        markdown=narrative.strip() or "日报生成失败",
        sources=facts.sources,
        disclaimer=facts.disclaimer,
        model=model,
        created_by=user_id,
    )
    session.add(report)
    await session.commit()
    return report


def _facts_markdown(facts_payload: dict[str, Any], disclaimer: str) -> str:
    lines = [
        f"# {facts_payload['report_date']} 钢材行情日报（事实稿）",
        "",
        "> LLM 服务暂不可用，以下为系统根据数据库生成的事实数据，未经过模型解读。",
        "",
        "## 报价概览",
    ]
    quotes = facts_payload.get("quotes") or []
    if quotes:
        for quote in quotes:
            change = quote.get("change")
            change_text = f"，涨跌 {change}" if change is not None else ""
            lines.append(
                f"- {quote['code']} {quote['spec']} {quote['region']}："
                f"{quote['price']} 元/吨{change_text}"
            )
    else:
        lines.append("- 暂无报价")

    lines.extend(
        [
            "",
            "## 库存",
            f"- 日期：{facts_payload['inventory'].get('date') or '无'}",
            f"- 规格条数：{facts_payload['inventory'].get('total', 0)}",
        ]
    )

    lines.extend(["", "## 价差"])
    spreads = facts_payload.get("spreads") or []
    if spreads:
        for spread in spreads:
            lines.append(f"- {spread['name']}：{spread['latest']}")
    else:
        lines.append("- 暂无可计算价差")

    lines.extend(["", "## 异动提醒"])
    anomalies = facts_payload.get("anomalies") or []
    if anomalies:
        lines.extend(f"- {message}" for message in anomalies)
    else:
        lines.append("- 暂无异常")

    lines.extend(["", f"> {disclaimer}", ""])
    return "\n".join(lines)
