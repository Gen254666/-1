import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from steel_core.db.enums import Role
from tests.integration.test_admin_api import _create_user, _login

pytestmark = pytest.mark.integration


async def test_import_rate_limit_returns_429(
    session: AsyncSession,
    app_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _create_user(session, "admin", role=Role.ADMIN)
    headers = await _login(app_client, "admin")
    settings = get_settings()
    monkeypatch.setattr(settings, "import_rate_limit", 1)

    first = await app_client.post(
        "/api/admin/import/inventory",
        headers=headers,
        files={"file": ("10.25.xlsx", b"not-a-zip", "application/octet-stream")},
    )
    second = await app_client.post(
        "/api/admin/import/inventory",
        headers=headers,
        files={"file": ("10.25.xlsx", b"not-a-zip", "application/octet-stream")},
    )

    assert first.status_code == 400
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"
