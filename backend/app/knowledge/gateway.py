from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import ApiError
from mcp_server.auth import create_service_token
from steel_core.db.models.accounts import User


class KnowledgeGateway:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def _request(
        self,
        user: User,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        token = create_service_token(user_id=user.id, role=user.role, ttl_seconds=60)
        async with httpx.AsyncClient(base_url=self._base_url, timeout=60) as client:
            response = await client.request(
                method,
                path,
                headers={"Authorization": f"Bearer {token}"},
                json=json,
                params=params,
            )
        if response.status_code >= 400:
            try:
                payload = response.json()
            except Exception:  # noqa: BLE001
                payload = {}
            raise ApiError(
                response.status_code,
                str(payload.get("code", "KNOWLEDGE_ERROR")),
                str(payload.get("message", "知识库服务请求失败")),
            )
        return response.json()

    async def ingest(self, user: User, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(user, "POST", "/internal/knowledge/documents", json=payload)

    async def list_documents(self, user: User) -> dict[str, Any]:
        return await self._request(user, "GET", "/internal/knowledge/documents")

    async def delete(self, user: User, doc_id: str) -> dict[str, Any]:
        return await self._request(
            user,
            "DELETE",
            "/internal/knowledge/documents",
            params={"doc_id": doc_id},
        )


def get_knowledge_gateway() -> KnowledgeGateway:
    return KnowledgeGateway(get_settings().mcp_base_url)
