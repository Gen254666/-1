from datetime import timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_token
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


@pytest.mark.parametrize(
    ("path", "user_status", "admin_status"),
    [
        ("/api/quotes", 200, 200),
        ("/api/reports", 200, 200),
        ("/api/admin/imports", 403, 200),
        ("/api/admin/config/anomaly", 403, 200),
        ("/api/admin/system/status", 403, 200),
        ("/api/users", 403, 200),
    ],
)
async def test_get_permission_matrix(
    session: AsyncSession,
    app_client: httpx.AsyncClient,
    path: str,
    user_status: int,
    admin_status: int,
) -> None:
    await _create_user(session, "alice", Role.USER)
    await _create_user(session, "admin", Role.ADMIN)
    user_headers = await _login(app_client, "alice")
    admin_headers = await _login(app_client, "admin")

    anonymous = await app_client.get(path)
    assert anonymous.status_code == 401

    user_response = await app_client.get(path, headers=user_headers)
    assert user_response.status_code == user_status

    admin_response = await app_client.get(path, headers=admin_headers)
    assert admin_response.status_code == admin_status


async def test_expired_access_token(session: AsyncSession, app_client: httpx.AsyncClient) -> None:
    user = await _create_user(session, "alice", Role.USER)
    expired, _, _ = create_token(
        user_id=user.id,
        token_type="access",
        role=user.role.value,
        expires_delta=timedelta(seconds=-1),
    )

    response = await app_client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_TOKEN_EXPIRED"
