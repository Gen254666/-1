import uuid
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import DatasetType, PointScope, Role
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import AppConfig, AuditLog, DailyReport, DatasetVersion
from steel_core.db.models.inventory import InventoryItem, InventorySnapshot
from steel_core.db.models.market import MarketQuote, PricePoint
from steel_core.security import hash_password
from steel_core.versioning.service import create_import_batch, create_version

pytestmark = pytest.mark.integration

PASSWORD = "secret-123"
TODAY = date(2026, 10, 23)


async def _create_user(session: AsyncSession) -> User:
    user = User(
        username="alice",
        password_hash=hash_password(PASSWORD),
        role=Role.USER,
    )
    session.add(user)
    await session.commit()
    return user


async def _auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _make_point(
    session: AsyncSession,
    code: str,
    *,
    category: str = "方管",
    spec: str = "100*100*2.5*6m",
    region: str = "昆明",
) -> PricePoint:
    point = PricePoint(
        scope=PointScope.PUBLIC,
        code=code,
        category=category,
        spec=spec,
        region=region,
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


async def _seed_market(session: AsyncSession, user: User) -> tuple[PricePoint, PricePoint]:
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
    await session.commit()
    return first, second


async def _seed_inventory(session: AsyncSession, user: User) -> InventorySnapshot:
    version = await _make_version(session, user, TODAY, dataset_type=DatasetType.INVENTORY)
    snapshot = InventorySnapshot(
        version_id=version.id,
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
    await session.commit()
    return snapshot


async def test_quotes_require_auth(app_client: httpx.AsyncClient) -> None:
    response = await app_client.get("/api/quotes")

    assert response.status_code == 401


async def test_get_quotes_and_history(session: AsyncSession, app_client: httpx.AsyncClient) -> None:
    user = await _create_user(session)
    await _seed_market(session, user)
    headers = await _auth_headers(app_client)

    quotes = await app_client.get("/api/quotes", headers=headers)
    assert quotes.status_code == 200
    assert quotes.json()["total"] == 2
    assert quotes.json()["items"][0]["price"] == 3550.0

    history = await app_client.get(
        "/api/history",
        headers=headers,
        params={
            "point_ids": [str(quotes.json()["items"][0]["point_id"])],
            "start_date": (TODAY - timedelta(days=7)).isoformat(),
            "end_date": TODAY.isoformat(),
        },
    )
    assert history.status_code == 200
    assert history.json()[0]["latest"] == 3550.0
    assert history.json()[0]["change"] == 50.0


async def test_inventory_dashboard_and_quote_generate(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    user = await _create_user(session)
    await _seed_market(session, user)
    await _seed_inventory(session, user)
    headers = await _auth_headers(app_client)

    inventory = await app_client.get("/api/inventory", headers=headers)
    assert inventory.status_code == 200
    assert inventory.json()["total"] == 1
    assert inventory.json()["items"][0]["spec"] == "100*100*2.5*6m"

    dashboard = await app_client.get("/api/dashboard", headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["quotes"]["total"] == 2
    assert dashboard.json()["inventory"]["total"] == 1
    assert "anomalies" in dashboard.json()

    quote = await app_client.post(
        "/api/quote/generate",
        headers=headers,
        json={
            "spec": "100×100×2.5×6m",
            "pieces": 10,
            "freight": 100,
            "processing_fee": 50,
        },
    )
    assert quote.status_code == 200, quote.text
    payload = quote.json()
    assert payload["total"] == 1035.0
    assert payload["lines"][0]["price_per_piece"] == 88.5
    assert payload["disclaimer"] == "报价免责"
    assert payload["sources"][0]["type"] == "inventory"

    missing = await app_client.post(
        "/api/quote/generate",
        headers=headers,
        json={"spec": "not-exist", "pieces": 1},
    )
    assert missing.status_code == 404


async def test_quote_export_audits_and_watermarks(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    user = await _create_user(session)
    await _seed_inventory(session, user)
    headers = await _auth_headers(app_client)

    response = await app_client.post(
        "/api/exports/quote",
        headers=headers,
        json={
            "spec": "100×100×2.5×6m",
            "pieces": 10,
            "freight": 100,
            "processing_fee": 50,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["export_id"]
    assert payload["filename"].endswith(".md")
    assert "alice" in payload["watermark"]
    assert payload["export_id"] in payload["watermark"]
    audit = await session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "export.quote")
        .order_by(AuditLog.created_at.desc())
    )
    assert audit is not None
    assert audit.ip


async def test_report_export_audits_and_watermarks(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    user = await _create_user(session)
    session.add(
        DailyReport(
            report_date=TODAY,
            version_no=1,
            markdown="# 日报\n\n今日行情",
            sources=[],
            disclaimer="报告免责",
            model="test",
            created_by=user.id,
        )
    )
    await session.commit()
    headers = await _auth_headers(app_client)

    response = await app_client.post(
        f"/api/reports/{TODAY.isoformat()}/export", headers=headers
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "alice" in payload["content"]
    assert "今日行情" in payload["content"]
    assert payload["export_id"] in payload["content"]
    audit = await session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "export.report")
        .order_by(AuditLog.created_at.desc())
    )
    assert audit is not None
    assert audit.ip

    missing = await app_client.post("/api/reports/2026-10-01/export", headers=headers)
    assert missing.status_code == 404


async def test_reports_read(session: AsyncSession, app_client: httpx.AsyncClient) -> None:
    user = await _create_user(session)
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
    headers = await _auth_headers(app_client)

    listing = await app_client.get("/api/reports", headers=headers)
    assert listing.status_code == 200
    assert listing.json()[0]["report_date"] == TODAY.isoformat()

    detail = await app_client.get(f"/api/reports/{TODAY.isoformat()}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["markdown"] == "# 日报"


async def test_quote_generate_for_private_point_isolated(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    await _create_user(session)
    other = User(
        username="bob",
        password_hash=hash_password(PASSWORD),
        role=Role.USER,
    )
    session.add(other)
    await session.flush()
    private = PricePoint(
        scope=PointScope.PRIVATE,
        owner_user_id=other.id,
        code="PRIVATE",
        category="方管",
        spec="100*100*2.5*6m",
        region="昆明",
        source="mysteel",
        unit="元/吨",
    )
    session.add(private)
    await session.flush()
    version = await _make_version(session, other, TODAY)
    session.add(
        MarketQuote(
            version_id=version.id,
            point_id=private.id,
            quote_date=TODAY,
            price=Decimal("3600"),
            source="mysteel",
        )
    )
    await session.commit()
    headers = await _auth_headers(app_client)

    response = await app_client.get(
        "/api/quotes", headers=headers, params={"point_ids": [str(private.id)]}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0
