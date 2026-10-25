import uuid
from datetime import date
from decimal import Decimal

from app.report.service import _facts_markdown
from steel_core.query.service import QuoteRecord
from steel_core.report.facts import report_quote_highlights


def _q(code: str, change: str | None) -> QuoteRecord:
    return QuoteRecord(
        point_id=uuid.uuid4(),
        code=code,
        category="方管",
        spec=f"{code}*6m",
        region="昆明",
        quote_date=date(2026, 10, 25),
        price=Decimal("3550"),
        change=None if change is None else Decimal(change),
        source="inventory",
    )


def test_highlights_prefer_largest_change() -> None:
    quotes = [
        _q("A", change=None),
        _q("B", change="10"),
        _q("C", change="-30"),
        _q("D", change="5"),
    ]

    result = report_quote_highlights(quotes, limit=2)

    assert [quote.code for quote in result] == ["C", "B"]


def test_highlights_fallback_when_all_changes_null() -> None:
    quotes = [_q("B", change=None), _q("A", change=None)]

    result = report_quote_highlights(quotes, limit=2)

    assert [quote.code for quote in result] == ["A", "B"]


def test_facts_markdown_marks_first_day() -> None:
    markdown = _facts_markdown(
        {
            "report_date": "2026-10-25",
            "quotes_total": 2,
            "changes_unavailable": True,
            "quotes": [
                {
                    "code": "A",
                    "spec": "100*100*2.5*6m",
                    "region": "昆明",
                    "price": 3550.0,
                    "change": None,
                }
            ],
            "inventory": {"date": "2026-10-25", "total": 2},
            "spreads": [],
            "anomalies": [],
        },
        "免责",
    )

    assert "首日无涨跌" in markdown
