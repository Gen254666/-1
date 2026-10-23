import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import Role
from steel_core.db.models.accounts import User
from steel_core.security import hash_password

pytestmark = pytest.mark.integration

PASSWORD = "secret-123"


async def _create_user(session: AsyncSession, username: str, role: Role) -> User:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        role=role,
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


async def test_health_ready_and_metrics(app_client: httpx.AsyncClient) -> None:
    health = await app_client.get("/healthz")
    assert health.status_code == 200

    ready = await app_client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["checks"]["database"] == "ok"

    metrics = await app_client.get("/metrics")
    assert metrics.status_code == 200
    assert "http_requests_total" in metrics.text


async def test_system_status_admin_only(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    await _create_user(session, "alice", Role.USER)
    await _create_user(session, "admin", Role.ADMIN)
    alice_headers = await _login(app_client, "alice")
    admin_headers = await _login(app_client, "admin")

    forbidden = await app_client.get("/api/admin/system/status", headers=alice_headers)
    assert forbidden.status_code == 403

    status = await app_client.get("/api/admin/system/status", headers=admin_headers)
    assert status.status_code == 200
    payload = status.json()
    assert payload["database"] == "ok"
    assert "redis" in payload
    assert "last_successful_import" in payload
