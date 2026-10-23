from datetime import date

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import PointScope, Role, VersionStatus
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import DatasetVersion
from steel_core.security import hash_password

pytestmark = pytest.mark.integration

PASSWORD = "secret-123"
QUOTE_DATE = date(2026, 10, 24)


async def _create_user(session: AsyncSession, username: str) -> User:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        role=Role.USER,
    )
    session.add(user)
    await session.commit()
    return user


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_private_point(
    client: httpx.AsyncClient, headers: dict[str, str], spec: str
) -> str:
    response = await client.post(
        "/api/points",
        headers=headers,
        json={
            "scope": "private",
            "category": "方管",
            "spec": spec,
            "region": "昆明",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_private_quote_visibility_and_versioning(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    await _create_user(session, "alice")
    await _create_user(session, "bob")
    alice_headers = await _login(app_client, "alice")
    bob_headers = await _login(app_client, "bob")

    first_point = await _create_private_point(app_client, alice_headers, "200*200*5.0*6m")
    second_point = await _create_private_point(app_client, alice_headers, "200*200*6.0*6m")

    created = await app_client.post(
        f"/api/points/{first_point}/quotes",
        headers=alice_headers,
        json={"quote_date": QUOTE_DATE.isoformat(), "price": 3800, "change": 20},
    )
    assert created.status_code == 201, created.text

    alice_quotes = await app_client.get(
        "/api/quotes",
        headers=alice_headers,
        params={"point_ids": [first_point]},
    )
    assert alice_quotes.status_code == 200
    assert alice_quotes.json()["total"] == 1
    assert alice_quotes.json()["items"][0]["price"] == 3800.0

    bob_quotes = await app_client.get(
        "/api/quotes",
        headers=bob_headers,
        params={"point_ids": [first_point]},
    )
    assert bob_quotes.status_code == 200
    assert bob_quotes.json()["total"] == 0

    forbidden = await app_client.post(
        f"/api/points/{first_point}/quotes",
        headers=bob_headers,
        json={"quote_date": QUOTE_DATE.isoformat(), "price": 3900},
    )
    assert forbidden.status_code == 403

    updated = await app_client.post(
        f"/api/points/{first_point}/quotes",
        headers=alice_headers,
        json={"quote_date": QUOTE_DATE.isoformat(), "price": 3850},
    )
    assert updated.status_code == 201
    alice_after = await app_client.get(
        "/api/quotes",
        headers=alice_headers,
        params={"point_ids": [first_point]},
    )
    assert alice_after.json()["items"][0]["price"] == 3850.0

    second = await app_client.post(
        f"/api/points/{second_point}/quotes",
        headers=alice_headers,
        json={"quote_date": QUOTE_DATE.isoformat(), "price": 3900},
    )
    assert second.status_code == 201
    both = await app_client.get(
        "/api/quotes",
        headers=alice_headers,
        params={"point_ids": [first_point, second_point]},
    )
    assert both.json()["total"] == 2

    versions = list(
        (
            await session.scalars(
                select(DatasetVersion)
                .where(
                    DatasetVersion.scope == PointScope.PRIVATE,
                    DatasetVersion.effective_date == QUOTE_DATE,
                )
                .order_by(DatasetVersion.version_no)
            )
        ).all()
    )
    assert len(versions) == 3
    assert versions[-1].status == VersionStatus.ACTIVE
    assert versions[0].status == VersionStatus.SUPERSEDED
    assert versions[-1].owner_user_id is not None

    active_count = await session.scalar(
        select(func.count())
        .select_from(DatasetVersion)
        .where(
            DatasetVersion.scope == PointScope.PRIVATE,
            DatasetVersion.effective_date == QUOTE_DATE,
            DatasetVersion.status == VersionStatus.ACTIVE,
        )
    )
    assert active_count == 1
