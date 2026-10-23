import uuid
from pathlib import Path

import httpx
import pytest

from mcp_server.auth import create_service_token
from mcp_server.server import app
from steel_core.db.enums import Role
from steel_core.knowledge.service import get_client

pytestmark = pytest.mark.integration


def fake_embedder(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        vector = [0.0] * 32
        for char in text:
            vector[ord(char) % 32] += 1.0
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        vectors.append([value / norm for value in vector])
    return vectors


async def test_knowledge_internal_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = get_client(tmp_path)
    monkeypatch.setattr("mcp_server.server._knowledge_client", lambda: client)
    monkeypatch.setattr("steel_core.knowledge.service.default_embedder", fake_embedder)

    admin_id = uuid.uuid4()
    user_id = uuid.uuid4()
    admin_token = create_service_token(user_id=admin_id, role=Role.ADMIN)
    user_token = create_service_token(user_id=user_id, role=Role.USER)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://mcp") as http:
        unauthorized = await http.post(
            "/internal/knowledge/documents",
            json={"title": "x", "text": "y"},
        )
        assert unauthorized.status_code == 401

        forbidden = await http.post(
            "/internal/knowledge/documents",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"title": "x", "text": "y"},
        )
        assert forbidden.status_code == 403

        created = await http.post(
            "/internal/knowledge/documents",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "title": "昆明钢材政策摘要",
                "text": "钢材出口政策：鼓励边境贸易。" * 20,
                "doc_type": "policy",
                "source": "政策文件",
                "effective_date": "2026-01-01",
                "expire_date": "2026-12-31",
            },
        )
        assert created.status_code == 200, created.text
        payload = created.json()
        assert payload["chunks"] > 0
        doc_id = payload["doc_id"]

        listed = await http.get(
            "/internal/knowledge/documents",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert listed.status_code == 200
        assert listed.json()["documents"][0]["doc_id"] == doc_id

        deleted = await http.delete(
            "/internal/knowledge/documents",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"doc_id": doc_id},
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted_chunks"] > 0

        listed_after = await http.get(
            "/internal/knowledge/documents",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert listed_after.json()["documents"] == []
