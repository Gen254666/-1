from datetime import date
from pathlib import Path

import pytest

from steel_core.knowledge.service import (
    chunk_text,
    delete_document,
    get_client,
    ingest_document,
    list_documents,
    resolve_collections,
    search_knowledge,
)

DIM = 64


def fake_embedder(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        vector = [0.0] * DIM
        for char in text:
            vector[ord(char) % DIM] += 1.0
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        vectors.append([value / norm for value in vector])
    return vectors


def test_chunk_text_respects_size_and_overlap() -> None:
    text = "钢材行情。" * 300

    chunks = chunk_text(text, chunk_size=200, overlap=50)

    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 200 for chunk in chunks)


def test_resolve_collections_blocks_other_users() -> None:
    user_id = "11111111-1111-1111-1111-111111111111"
    other_id = "22222222-2222-2222-2222-222222222222"

    allowed = resolve_collections(["kb_public", f"kb_private_{user_id}"], user_id=user_id)
    assert f"kb_private_{user_id}" in allowed

    with pytest.raises(PermissionError):
        resolve_collections([f"kb_private_{other_id}"], user_id=user_id)


def test_ingest_search_expiry_and_dedupe(tmp_path: Path) -> None:
    client = get_client(tmp_path)
    collection = client.get_or_create_collection("kb_public")

    added = ingest_document(
        collection,
        doc_id="policy-1",
        title="昆明钢材政策摘要",
        text="昆明钢材出口政策：鼓励边境贸易，规范通关流程。" * 5,
        doc_type="policy",
        source="政策文件",
        effective_date=date(2026, 9, 1),
        expire_date=date(2026, 12, 31),
        embedder=fake_embedder,
    )
    assert added > 0

    duplicates = ingest_document(
        collection,
        doc_id="policy-1",
        title="昆明钢材政策摘要",
        text="昆明钢材出口政策：鼓励边境贸易，规范通关流程。" * 5,
        doc_type="policy",
        source="政策文件",
        effective_date=date(2026, 9, 1),
        expire_date=date(2026, 12, 31),
        embedder=fake_embedder,
    )
    assert duplicates == 0

    citations = search_knowledge(
        client,
        query="钢材出口政策",
        collections=["kb_public"],
        user_id="11111111-1111-1111-1111-111111111111",
        embedder=fake_embedder,
    )
    assert citations
    assert citations[0].title == "昆明钢材政策摘要"
    assert citations[0].doc_type == "policy"
    assert citations[0].effective_date == "2026-09-01"
    assert citations[0].index == 1


def test_expired_documents_are_filtered(tmp_path: Path) -> None:
    client = get_client(tmp_path)
    collection = client.get_or_create_collection("kb_public")
    ingest_document(
        collection,
        doc_id="old-policy",
        title="旧政策",
        text="旧版钢材政策内容。" * 10,
        doc_type="policy",
        source="政策文件",
        effective_date=date(2019, 1, 1),
        expire_date=date(2020, 1, 1),
        embedder=fake_embedder,
    )

    hidden = search_knowledge(
        client,
        query="钢材政策",
        collections=["kb_public"],
        user_id="11111111-1111-1111-1111-111111111111",
        embedder=fake_embedder,
    )
    visible = search_knowledge(
        client,
        query="钢材政策",
        collections=["kb_public"],
        user_id="11111111-1111-1111-1111-111111111111",
        embedder=fake_embedder,
        include_expired=True,
    )

    assert hidden == []
    assert visible
    assert visible[0].expire_date == "2020-01-01"


def test_list_and_delete_documents(tmp_path: Path) -> None:
    client = get_client(tmp_path)
    collection = client.get_or_create_collection("kb_public")
    ingest_document(
        collection,
        doc_id="policy-1",
        title="政策摘要",
        text="钢材出口政策。" * 20,
        doc_type="policy",
        source="政策文件",
        effective_date=date(2026, 1, 1),
        expire_date=None,
        embedder=fake_embedder,
    )
    ingest_document(
        collection,
        doc_id="industry-1",
        title="产业链知识",
        text="钢材产业链包括矿山、焦化、炼钢、轧钢。" * 10,
        doc_type="industry",
        source="行业资料",
        effective_date=date(2026, 1, 1),
        expire_date=None,
        embedder=fake_embedder,
    )

    documents = list_documents(client)
    assert len(documents) == 2
    assert {item["title"] for item in documents} == {"政策摘要", "产业链知识"}
    assert all(item["chunk_count"] > 0 for item in documents)

    deleted = delete_document(client, doc_id="policy-1")
    assert deleted > 0
    remaining = list_documents(client)
    assert {item["doc_id"] for item in remaining} == {"industry-1"}


def test_private_collection_is_isolated(tmp_path: Path) -> None:
    client = get_client(tmp_path)
    user_id = "11111111-1111-1111-1111-111111111111"
    other_id = "22222222-2222-2222-2222-222222222222"
    collection = client.get_or_create_collection(f"kb_private_{user_id}")
    ingest_document(
        collection,
        doc_id="private-1",
        title="私有知识",
        text="内部报价规则：方管加价 220 元/吨。" * 5,
        doc_type="internal_rule",
        source="内部文件",
        effective_date=date(2026, 1, 1),
        expire_date=None,
        embedder=fake_embedder,
    )

    with pytest.raises(PermissionError):
        search_knowledge(
            client,
            query="报价规则",
            collections=[f"kb_private_{other_id}"],
            user_id=user_id,
            embedder=fake_embedder,
        )
