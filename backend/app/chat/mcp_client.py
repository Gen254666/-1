from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.core.config import get_settings
from mcp_server.auth import create_service_token
from steel_core.db.models.accounts import User


class HttpMCPClient:
    def __init__(self, url: str, user: User) -> None:
        self._url = url
        self._user = user
        self._transport: Any = None
        self._session_cm: Any = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> HttpMCPClient:
        token = create_service_token(user_id=self._user.id, role=self._user.role, ttl_seconds=300)
        self._transport = streamablehttp_client(
            self._url,
            headers={"Authorization": f"Bearer {token}"},
        )
        read, write, _ = await self._transport.__aenter__()
        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._session_cm is not None:
            await self._session_cm.__aexit__(exc_type, exc, tb)
        if self._transport is not None:
            await self._transport.__aexit__(exc_type, exc, tb)

    async def list_tools(self) -> list[dict[str, Any]]:
        assert self._session is not None
        result = await self._session.list_tools()
        return [
            {
                "name": tool.name,
                "description": getattr(tool, "description", ""),
                "input_schema": getattr(tool, "inputSchema", {}),
            }
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert self._session is not None
        result = await self._session.call_tool(name, arguments)
        structured = getattr(result, "structuredContent", None) or getattr(
            result, "structured_content", None
        )
        if isinstance(structured, dict):
            return structured

        text_parts: list[str] = []
        for content in result.content:
            text = getattr(content, "text", None)
            if text:
                text_parts.append(text)
        text = "\n".join(text_parts)
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
        return {
            "summary": text,
            "artifact": None,
            "meta": {},
            "error": {
                "code": "UPSTREAM_ERROR",
                "message": "MCP 返回了无法解析的结果",
                "details": {},
                "retryable": False,
            },
        }


@asynccontextmanager
async def default_mcp_factory(user: User) -> AsyncIterator[HttpMCPClient]:
    settings = get_settings()
    url = settings.mcp_base_url.rstrip("/") + "/mcp"
    async with HttpMCPClient(url, user) as client:
        yield client
