import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_server.context import UserContext, require_context
from mcp_server.tools import (
    compare_spread,
    generate_daily_report,
    generate_quote_tool,
    get_daily_report,
    get_inventory,
    get_meta,
    get_price_history,
    get_quotes,
    scan_anomalies_tool,
    search_knowledge_tool,
)
from steel_core.db.enums import DatasetType, PointScope, Role
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import AppConfig, DailyReport, DatasetVersion
from steel_core.db.models.inventory import InventoryItem, InventorySnapshot
from steel_core.db.models.market import MarketQuote, PricePoint
from steel_core.knowledge.service import get_client as get_knowledge_client
from steel_core.knowledge.service import ingest_document as ingest_knowledge
from steel_core.versioning.service import create_import_batch, create_version

pytestmark = pytest.mark.integration

TODAY = date(2026, 10, 23)


async def _make_user(session: AsyncSession) -> User:
    from steel_core.security import hash_password

    user = User(
        username=f"user-{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("secret-123"),
        role=Role.USER,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_point(session: AsyncSession, code: str, spec: str = "100*100*2.5*6m") -> PricePoint:
    point = PricePoint(
        scope=PointScope.PUBLIC,
        code=code,
        category="方管",
        spec=spec,
        region="昆明",
        source="mysteel",
        unit="元/吨",
    )
    session.add(point)
    await session.flush()
    return point


async def _make_version(
    session: AsyncSession,
    user: User,
    effective_date: date,
    *,
    dataset_type: DatasetType = DatasetType.MARKET_QUOTE,
) -> DatasetVersion:
    batch = await create_import_batch(
        session,
        user_id=user.id,
        dataset_type=dataset_type,
        effective_date=effective_date,
        file_name="data.csv",
        file_hash=uuid.uuid4().hex,
        rows_total=1,
        rows_ok=1,
        rows_failed=0,
    )
    return await create_version(
        session,
        dataset_type=dataset_type,
        effective_date=effective_date,
        checksum=uuid.uuid4().hex,
        import_batch_id=batch.id,
    )


async def _seed(session: AsyncSession) -> tuple[User, PricePoint, PricePoint]:
    user = await _make_user(session)
    first = await _make_point(session, "P1")
    second = await _make_point(session, "P2", spec="100*150*2.5*6m")
    for offset, first_price, second_price in [
        (1, "3500", "3400"),
        (0, "3550", "3480"),
    ]:
        quote_date = TODAY - timedelta(days=offset)
        version = await _make_version(session, user, quote_date)
        session.add_all(
            [
                MarketQuote(
                    version_id=version.id,
                    point_id=first.id,
                    quote_date=quote_date,
                    price=Decimal(first_price),
                    source="mysteel",
                ),
                MarketQuote(
                    version_id=version.id,
                    point_id=second.id,
                    quote_date=quote_date,
                    price=Decimal(second_price),
                    source="mysteel",
                ),
            ]
        )

    inventory_version = await _make_version(
        session, user, TODAY, dataset_type=DatasetType.INVENTORY
    )
    snapshot = InventorySnapshot(
        version_id=inventory_version.id,
        snapshot_date=TODAY,
        warehouse="昆明宝象库",
        source_file="10.23.xlsx",
    )
    session.add(snapshot)
    await session.flush()
    session.add(
        InventoryItem(
            snapshot_id=snapshot.id,
            block="方管",
            spec="100*100*2.5*6m",
            unit_price=Decimal("3550"),
            tax_add=Decimal("220"),
            weight_per_piece=Decimal("24.93"),
            pieces=230,
            total_weight=Decimal("5.662"),
            price_per_piece=Decimal("88.5"),
            manufacturer="正大",
            row_no=4,
        )
    )
    session.add(
        AppConfig(
            key="disclaimer",
            value={"quote": "报价免责", "report": "报告免责"},
        )
    )
    session.add(
        DailyReport(
            report_date=TODAY,
            version_no=1,
            markdown="# 日报",
            sources=[],
            disclaimer="报告免责",
            model="test",
            created_by=user.id,
        )
    )
    await session.commit()
    return user, first, second


def _assert_envelope(result: dict[str, Any], artifact_type: str) -> None:
    assert result["error"] is None
    assert result["summary"]
    artifact = result["artifact"]
    assert isinstance(artifact, dict)
    assert artifact["type"] == artifact_type
    assert "as_of" in result["meta"]


async def test_mcp_tools_contracts(session: AsyncSession) -> None:
    user, first, second = await _seed(session)
    ctx = UserContext(user_id=user.id, role=Role.USER)

    meta = await get_meta(session, ctx)
    _assert_envelope(meta, "table")
    assert any(row["code"] == "P1" for row in meta["artifact"]["payload"]["rows"])

    limited_meta = await get_meta(session, ctx, limit=1)
    assert limited_meta["artifact"]["payload"]["total"] >= 2
    assert len(limited_meta["artifact"]["payload"]["rows"]) == 1

    quotes = await get_quotes(session, ctx)
    _assert_envelope(quotes, "cards")
    assert quotes["artifact"]["payload"]["items"][0]["price"] == 3550.0

    history = await get_price_history(
        session,
        ctx,
        point_ids=[first.id],
        start_date=TODAY - timedelta(days=7),
        end_date=TODAY,
    )
    _assert_envelope(history, "chart")
    assert history["artifact"]["payload"]["series"][0]["y"] == [3500.0, 3550.0]

    spread = await compare_spread(
        session,
        ctx,
        left_point_id=first.id,
        right_point_id=second.id,
        start_date=TODAY - timedelta(days=7),
        end_date=TODAY,
    )
    _assert_envelope(spread, "chart")

    anomalies = await scan_anomalies_tool(session, ctx, quote_date=TODAY)
    _assert_envelope(anomalies, "table")

    inventory = await get_inventory(session, ctx)
    _assert_envelope(inventory, "cards")
    assert inventory["artifact"]["payload"]["items"][0]["spec"] == "100*100*2.5*6m"

    quote = await generate_quote_tool(
        session,
        ctx,
        pieces=10,
        spec="100*100*2.5*6m",
        freight=Decimal("100"),
        processing_fee=Decimal("50"),
    )
    _assert_envelope(quote, "quote")
    assert quote["artifact"]["payload"]["total"] == 1035.0
    assert quote["artifact"]["payload"]["disclaimer"] == "报价免责"

    report = await get_daily_report(session, ctx, report_date=TODAY)
    _assert_envelope(report, "report")
    assert report["artifact"]["payload"]["markdown"] == "# 日报"


async def test_generate_daily_report_requires_admin(session: AsyncSession) -> None:
    user, _, _ = await _seed(session)
    user_ctx = UserContext(user_id=user.id, role=Role.USER)
    admin_ctx = UserContext(user_id=user.id, role=Role.ADMIN)

    forbidden = await generate_daily_report(session, user_ctx, report_date=TODAY)
    assert forbidden["error"]["code"] == "PERMISSION_DENIED"

    allowed = await generate_daily_report(session, admin_ctx, report_date=TODAY)
    _assert_envelope(allowed, "report")
    assert allowed["artifact"]["payload"]["report_date"] == TODAY.isoformat()
    assert allowed["artifact"]["payload"]["disclaimer"] == "报告免责"
    assert allowed["artifact"]["payload"]["quotes_total"] == 2


def test_require_context_without_context() -> None:
    from mcp_server.context import ToolError

    with pytest.raises(ToolError):
        require_context()


def _fake_embedder(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        vector = [0.0] * 32
        for char in text:
            vector[ord(char) % 32] += 1.0
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        vectors.append([value / norm for value in vector])
    return vectors


def test_search_knowledge_tool(tmp_path: Path) -> None:
    client = get_knowledge_client(tmp_path)
    collection = client.get_or_create_collection("kb_public")
    ingest_knowledge(
        collection,
        doc_id="policy-1",
        title="政策摘要",
        text="钢材出口政策摘要：规范边境贸易流程。" * 5,
        doc_type="policy",
        source="政策文件",
        effective_date=date(2026, 1, 1),
        expire_date=None,
        embedder=_fake_embedder,
    )
    user_id = uuid.uuid4()
    ctx = UserContext(user_id=user_id, role=Role.USER)

    result = search_knowledge_tool(
        ctx,
        query="出口政策",
        collections=["kb_public"],
        client=client,
        embedder=_fake_embedder,
    )

    assert result["error"] is None
    assert result["artifact"]["type"] == "text"
    assert result["artifact"]["payload"]["citations"][0]["title"] == "政策摘要"
    assert "[1]" in result["summary"]

    forbidden = search_knowledge_tool(
        ctx,
        query="出口政策",
        collections=[f"kb_private_{uuid.uuid4()}"],
        client=client,
        embedder=_fake_embedder,
    )
    assert forbidden["error"]["code"] == "PERMISSION_DENIED"
