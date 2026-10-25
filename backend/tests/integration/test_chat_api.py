from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.dependencies import get_llm_router, get_mcp_client_factory
from steel_core.db.enums import Role
from steel_core.db.models.accounts import User
from steel_core.db.models.governance import AuditLog
from steel_core.security import hash_password

pytestmark = pytest.mark.integration

PASSWORD = "secret-123"


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    async def complete(self, messages: list[dict[str, str]]) -> str:
        return self.responses.pop(0)


class FakeMCP:
    async def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "get_quotes"}]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "summary": "找到 1 条报价",
            "artifact": {"type": "cards", "payload": {"items": [{"price": 3550}]}},
            "meta": {"as_of": "2026-10-23"},
            "error": None,
        }


async def _create_user(session: AsyncSession) -> User:
    user = User(
        username="alice",
        password_hash=hash_password(PASSWORD),
        role=Role.USER,
    )
    session.add(user)
    await session.commit()
    return user


async def _login(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login", json={"username": "alice", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_chat_stream_and_history(
    session: AsyncSession, app_client: httpx.AsyncClient, app_instance: Any
) -> None:
    await _create_user(session)
    headers = await _login(app_client)

    fake_mcp = FakeMCP()

    @asynccontextmanager
    async def fake_mcp_factory(user: User) -> Any:
        yield fake_mcp

    app_instance.dependency_overrides[get_llm_router] = lambda: FakeLLM(
        [
            '{"tool": "get_quotes", "arguments": {}}',
            '{"final": "今日方管 3550 元/吨"}',
        ]
    )
    app_instance.dependency_overrides[get_mcp_client_factory] = lambda: fake_mcp_factory

    response = await app_client.post(
        "/api/chat/stream",
        headers=headers,
        json={"message": "今天方管多少钱"},
    )
    assert response.status_code == 200, response.text
    body = response.text
    assert "event: session" in body
    assert "event: artifact" in body
    assert "event: token" in body
    assert "event: done" in body
    assert "3550" in body

    sessions = await app_client.get("/api/chat/sessions", headers=headers)
    assert sessions.status_code == 200
    session_id = sessions.json()[0]["id"]

    messages = await app_client.get(f"/api/chat/sessions/{session_id}/messages", headers=headers)
    assert messages.status_code == 200
    payload = messages.json()
    assert [message["role"] for message in payload] == ["user", "assistant"]
    assert payload[1]["content"] == "今日方管 3550 元/吨"
    assert payload[1]["artifacts"]

    audit = await session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "mcp.call")
        .order_by(AuditLog.created_at.desc())
    )
    assert audit is not None
    assert audit.resource_id == "get_quotes"
    assert audit.ip


async def test_chat_requires_auth(app_client: httpx.AsyncClient) -> None:
    response = await app_client.post("/api/chat/stream", json={"message": "你好"})

    assert response.status_code == 401
