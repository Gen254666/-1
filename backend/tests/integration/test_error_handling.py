from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.integration


async def test_unhandled_error_hides_details(app_instance: Any) -> None:
    @app_instance.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret SQL details")

    transport = httpx.ASGITransport(app=app_instance, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    assert "secret SQL details" not in response.text
    assert "Traceback" not in response.text
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert response.json()["details"]["request_id"]
