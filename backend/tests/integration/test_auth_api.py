from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import Role
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import AuditLog
from steel_core.security import hash_password

pytestmark = pytest.mark.integration

PASSWORD = "secret-123"


async def _create_user(
    session: AsyncSession,
    username: str = "alice",
    *,
    role: Role = Role.USER,
    must_change_password: bool = False,
) -> User:
    user = User(
        username=username,
        password_hash=hash_password(PASSWORD),
        role=role,
        must_change_password=must_change_password,
    )
    session.add(user)
    await session.commit()
    return user


async def _login(client: httpx.AsyncClient, username: str = "alice") -> dict[str, Any]:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_login_and_me(session: AsyncSession, app_client: httpx.AsyncClient) -> None:
    user = await _create_user(session)

    payload = await _login(app_client)

    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert payload["user"]["username"] == "alice"
    assert app_client.cookies.get("refresh_token")

    me = await app_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["id"] == str(user.id)


async def test_wrong_password_returns_401(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    await _create_user(session)

    response = await app_client.post(
        "/api/auth/login", json={"username": "alice", "password": "wrong"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_INVALID_CREDENTIALS"


async def test_login_success_and_failure_are_audited(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    await _create_user(session)

    await app_client.post(
        "/api/auth/login", json={"username": "alice", "password": "wrong"}
    )
    await _login(app_client)

    entries = list(
        (
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.action.in_(("auth.login", "auth.login_failed")))
                .order_by(AuditLog.created_at)
            )
        ).all()
    )
    actions = {entry.action for entry in entries}
    assert {"auth.login", "auth.login_failed"} <= actions
    assert all(entry.ip for entry in entries)


async def test_login_locks_after_failures(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    await _create_user(session)

    response = None
    for _ in range(5):
        response = await app_client.post(
            "/api/auth/login", json={"username": "alice", "password": "wrong"}
        )

    assert response is not None
    assert response.status_code == 423
    assert response.json()["code"] == "AUTH_ACCOUNT_LOCKED"


async def test_refresh_rotation_and_reuse_detection(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    await _create_user(session)
    await _login(app_client)
    original_refresh = app_client.cookies.get("refresh_token")
    assert original_refresh

    refreshed = await app_client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]
    rotated_refresh = app_client.cookies.get("refresh_token")
    assert rotated_refresh
    assert rotated_refresh != original_refresh

    app_client.cookies.clear()
    app_client.cookies.set("refresh_token", original_refresh)
    reused = await app_client.post("/api/auth/refresh")

    assert reused.status_code == 401
    assert reused.json()["code"] == "AUTH_REFRESH_REUSED"


async def test_logout_revokes_refresh(session: AsyncSession, app_client: httpx.AsyncClient) -> None:
    await _create_user(session)
    payload = await _login(app_client)
    refresh_token = app_client.cookies.get("refresh_token")
    assert refresh_token

    logout = await app_client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert logout.status_code == 204

    app_client.cookies.clear()
    app_client.cookies.set("refresh_token", refresh_token)
    response = await app_client.post("/api/auth/refresh")

    assert response.status_code == 401


async def test_must_change_password_blocks_other_endpoints(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    await _create_user(session, "newbie", must_change_password=True)
    login = await app_client.post(
        "/api/auth/login", json={"username": "newbie", "password": PASSWORD}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    blocked = await app_client.get("/api/quotes", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"

    me = await app_client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True

    changed = await app_client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"old_password": PASSWORD, "new_password": "new-secret-123"},
    )
    assert changed.status_code == 204

    allowed = await app_client.get("/api/quotes", headers=headers)
    assert allowed.status_code == 200

    me_after = await app_client.get("/api/auth/me", headers=headers)
    assert me_after.json()["must_change_password"] is False


async def test_change_password(session: AsyncSession, app_client: httpx.AsyncClient) -> None:
    await _create_user(session)
    payload = await _login(app_client)

    changed = await app_client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
        json={"old_password": PASSWORD, "new_password": "new-secret-123"},
    )
    assert changed.status_code == 204

    new_login = await app_client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "new-secret-123"},
    )
    assert new_login.status_code == 200

    old_login = await app_client.post(
        "/api/auth/login",
        json={"username": "alice", "password": PASSWORD},
    )
    assert old_login.status_code == 401


async def test_invalid_access_token_returns_401(
    app_client: httpx.AsyncClient,
) -> None:
    response = await app_client.get(
        "/api/auth/me", headers={"Authorization": "Bearer invalid-token"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_TOKEN_INVALID"


async def test_login_rate_limit(app_client: httpx.AsyncClient) -> None:
    response = None
    for index in range(5):
        response = await app_client.post(
            "/api/auth/login",
            json={"username": f"missing-{index}", "password": "wrong"},
        )
        assert response.status_code == 401

    blocked = await app_client.post(
        "/api/auth/login", json={"username": "missing-6", "password": "wrong"}
    )

    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMITED"
