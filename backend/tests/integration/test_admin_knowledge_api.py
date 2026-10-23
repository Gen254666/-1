import io
from typing import Any

import httpx
import pytest
from docx import Document
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.gateway import get_knowledge_gateway
from steel_core.db.enums import Role
from steel_core.db.models.accounts import User
from steel_core.security import hash_password

pytestmark = pytest.mark.integration

PASSWORD = "secret-123"


class FakeGateway:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []

    async def ingest(self, user: User, payload: dict[str, Any]) -> dict[str, Any]:
        self.documents.append({**payload, "chunk_count": 2})
        return {"doc_id": payload["doc_id"], "chunks": 2}

    async def list_documents(self, user: User) -> dict[str, Any]:
        return {"documents": self.documents}

    async def delete(self, user: User, doc_id: str) -> dict[str, Any]:
        self.documents = [document for document in self.documents if document["doc_id"] != doc_id]
        return {"doc_id": doc_id, "deleted_chunks": 2}


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


async def test_knowledge_upload_list_delete(
    session: AsyncSession, app_client: httpx.AsyncClient, app_instance: Any
) -> None:
    await _create_user(session, "alice", Role.USER)
    await _create_user(session, "admin", Role.ADMIN)
    admin_headers = await _login(app_client, "admin")
    user_headers = await _login(app_client, "alice")
    gateway = FakeGateway()
    app_instance.dependency_overrides[get_knowledge_gateway] = lambda: gateway

    uploaded = await app_client.post(
        "/api/admin/knowledge/documents",
        headers=admin_headers,
        files={
            "file": (
                "policy.md",
                "# 政策摘要\n钢材出口政策：鼓励边境贸易。",
                "text/markdown",
            )
        },
        data={"title": "政策摘要", "doc_type": "policy"},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["chunks"] == 2
    assert "鼓励边境贸易" in gateway.documents[0]["text"]

    listed = await app_client.get("/api/admin/knowledge/documents", headers=admin_headers)
    assert listed.status_code == 200
    doc_id = listed.json()["documents"][0]["doc_id"]

    forbidden = await app_client.post(
        "/api/admin/knowledge/documents",
        headers=user_headers,
        files={"file": ("policy.md", b"text", "text/markdown")},
    )
    assert forbidden.status_code == 403

    invalid = await app_client.post(
        "/api/admin/knowledge/documents",
        headers=admin_headers,
        files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "INVALID_UPLOAD"

    deleted = await app_client.delete(
        f"/api/admin/knowledge/documents/{doc_id}", headers=admin_headers
    )
    assert deleted.status_code == 200
    assert gateway.documents == []


async def test_docx_upload_is_extracted(
    session: AsyncSession, app_client: httpx.AsyncClient, app_instance: Any
) -> None:
    await _create_user(session, "admin", Role.ADMIN)
    headers = await _login(app_client, "admin")
    gateway = FakeGateway()
    app_instance.dependency_overrides[get_knowledge_gateway] = lambda: gateway

    document = Document()
    document.add_paragraph("钢材产业链知识：矿山、焦化、炼钢、轧钢。")
    buffer = io.BytesIO()
    document.save(buffer)

    response = await app_client.post(
        "/api/admin/knowledge/documents",
        headers=headers,
        files={
            "file": (
                "industry.docx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"title": "产业链知识", "doc_type": "industry"},
    )

    assert response.status_code == 200, response.text
    assert "炼钢" in gateway.documents[0]["text"]
