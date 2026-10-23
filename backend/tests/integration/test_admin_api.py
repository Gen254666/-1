import io
from datetime import date

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from steel_core.db.enums import Role
from steel_core.db.models.accounts import User
from steel_core.security import hash_password
from tests.unit.test_core.test_inventory_parser import _build_workbook

pytestmark = pytest.mark.integration

PASSWORD = "secret-123"
TODAY = date(2026, 10, 23)


async def _create_user(session: AsyncSession, username: str, role: Role = Role.USER) -> User:
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


def _xlsx_bytes() -> bytes:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "10.23库存状况表.xlsx"
        _build_workbook(path, invalid_row=False)
        return path.read_bytes()


async def test_admin_import_inventory_and_rollback(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    await _create_user(session, "admin", Role.ADMIN)
    headers = await _login(app_client, "admin")

    response = await app_client.post(
        "/api/admin/import/inventory",
        headers=headers,
        files={
            "file": (
                "10.23库存状况表.xlsx",
                io.BytesIO(_xlsx_bytes()),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"explicit_date": TODAY.isoformat()},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rows_ok"] == 4
    assert payload["no_changes"] is False

    imports = await app_client.get("/api/admin/imports", headers=headers)
    assert imports.status_code == 200
    assert imports.json()[0]["status"] == "success"

    rollback = await app_client.post(
        f"/api/admin/imports/{payload['batch_id']}/rollback", headers=headers
    )
    assert rollback.status_code == 200

    imports_after = await app_client.get("/api/admin/imports", headers=headers)
    assert imports_after.json()[0]["status"] == "rolled_back"


async def test_non_admin_cannot_import(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    await _create_user(session, "alice")
    headers = await _login(app_client, "alice")

    response = await app_client.post(
        "/api/admin/import/inventory",
        headers=headers,
        files={"file": ("10.23.xlsx", b"not-a-zip", "application/octet-stream")},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"


async def test_invalid_upload_is_rejected(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    await _create_user(session, "admin", Role.ADMIN)
    headers = await _login(app_client, "admin")

    response = await app_client.post(
        "/api/admin/import/inventory",
        headers=headers,
        files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_UPLOAD"


async def test_points_permissions(session: AsyncSession, app_client: httpx.AsyncClient) -> None:
    await _create_user(session, "alice")
    await _create_user(session, "admin", Role.ADMIN)
    alice_headers = await _login(app_client, "alice")
    admin_headers = await _login(app_client, "admin")

    private = await app_client.post(
        "/api/points",
        headers=alice_headers,
        json={
            "scope": "private",
            "category": "方管",
            "spec": "200*200*5.0*6m",
            "region": "昆明",
        },
    )
    assert private.status_code == 201, private.text
    private_id = private.json()["id"]

    forbidden_public = await app_client.post(
        "/api/points",
        headers=alice_headers,
        json={
            "scope": "public",
            "category": "方管",
            "spec": "200*200*5.0*6m",
            "region": "昆明",
        },
    )
    assert forbidden_public.status_code == 403

    public = await app_client.post(
        "/api/points",
        headers=admin_headers,
        json={
            "scope": "public",
            "category": "方管",
            "spec": "200*200*5.0*6m",
            "region": "昆明",
        },
    )
    assert public.status_code == 201

    admin_sees = await app_client.get("/api/points", headers=admin_headers)
    assert {item["scope"] for item in admin_sees.json()} == {"public"}

    alice_sees = await app_client.get("/api/points", headers=alice_headers)
    assert {item["scope"] for item in alice_sees.json()} == {"public", "private"}

    forbidden_patch = await app_client.patch(
        f"/api/points/{private_id}",
        headers=admin_headers,
        json={"region": "成都"},
    )
    assert forbidden_patch.status_code == 403


async def test_anomaly_config_admin_only(
    session: AsyncSession, app_client: httpx.AsyncClient
) -> None:
    await _create_user(session, "alice")
    await _create_user(session, "admin", Role.ADMIN)
    alice_headers = await _login(app_client, "alice")
    admin_headers = await _login(app_client, "admin")

    current = await app_client.get("/api/admin/config/anomaly", headers=admin_headers)
    assert current.status_code == 200
    assert current.json()["daily_change_pct"] == 2.0

    updated = await app_client.put(
        "/api/admin/config/anomaly",
        headers=admin_headers,
        json={
            "daily_change_pct": 3,
            "consecutive_days": 4,
            "inventory_deviation_pct": 25,
            "low_stock_pieces": 8,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["daily_change_pct"] == 3.0

    forbidden = await app_client.put(
        "/api/admin/config/anomaly",
        headers=alice_headers,
        json={
            "daily_change_pct": 3,
            "consecutive_days": 4,
            "inventory_deviation_pct": 25,
            "low_stock_pieces": 8,
        },
    )
    assert forbidden.status_code == 403


async def test_admin_user_management(session: AsyncSession, app_client: httpx.AsyncClient) -> None:
    await _create_user(session, "alice")
    await _create_user(session, "admin", Role.ADMIN)
    alice_headers = await _login(app_client, "alice")
    admin_headers = await _login(app_client, "admin")

    created = await app_client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "bob", "password": "bob-secret", "role": "user"},
    )
    assert created.status_code == 201
    assert created.json()["must_change_password"] is True

    listing = await app_client.get("/api/users", headers=admin_headers)
    assert listing.status_code == 200
    assert {item["username"] for item in listing.json()} >= {"alice", "admin", "bob"}

    forbidden = await app_client.get("/api/users", headers=alice_headers)
    assert forbidden.status_code == 403
