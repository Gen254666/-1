from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Any

import chromadb

Embedder = Callable[[list[str]], list[list[float]]]
NEVER_EXPIRES_TS = 4102444800  # 2100-01-01
DEFAULT_CHUNK_SIZE = 700
DEFAULT_OVERLAP = 100


@dataclass(frozen=True)
class Citation:
    index: int
    doc_id: str
    title: str
    doc_type: str
    effective_date: str
    expire_date: str | None
    snippet: str
    score: float


def get_client(path: str | Path) -> Any:
    return chromadb.PersistentClient(
        path=str(path),
        settings=chromadb.config.Settings(anonymized_telemetry=False),
    )


def chunk_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("。"), window.rfind("\n"), window.rfind("；"))
            if cut > chunk_size * 0.6:
                end = start + cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def resolve_collections(
    requested: list[str] | None,
    *,
    user_id: str,
    include_private: bool = True,
) -> list[str]:
    allowed = {"kb_public"}
    if include_private:
        allowed.add(f"kb_private_{user_id}")
    if not requested:
        return sorted(allowed)
    for name in requested:
        if name not in allowed:
            msg = f"无权访问知识库集合: {name}"
            raise PermissionError(msg)
    return requested


def ingest_document(
    collection: Any,
    *,
    doc_id: str,
    title: str,
    text: str,
    doc_type: str,
    source: str,
    effective_date: date | None,
    expire_date: date | None,
    embedder: Embedder | None = None,
) -> int:
    embed = embedder or default_embedder
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    existing = collection.get(where={"doc_id": doc_id}, include=["metadatas"])
    existing_ids = existing.get("ids") or []
    if existing_ids:
        metadatas = existing.get("metadatas") or []
        if any(
            metadata.get("content_hash") == content_hash
            for metadata in metadatas
            if isinstance(metadata, dict)
        ):
            return 0
        collection.delete(ids=existing_ids)

    chunks = chunk_text(text)
    if not chunks:
        return 0

    expire_ts = (
        int(datetime.combine(expire_date, time.min, tzinfo=UTC).timestamp())
        if expire_date
        else NEVER_EXPIRES_TS
    )
    effective_date_value = effective_date.isoformat() if effective_date else ""
    expire_date_value = expire_date.isoformat() if expire_date else ""
    metadatas = [
        {
            "doc_id": doc_id,
            "title": title,
            "doc_type": doc_type,
            "source": source,
            "effective_date": effective_date_value,
            "expire_date": expire_date_value,
            "expire_ts": expire_ts,
            "content_hash": content_hash,
            "chunk_index": index,
        }
        for index, _ in enumerate(chunks)
    ]
    ids = [f"{doc_id}:{index}" for index, _ in enumerate(chunks)]
    collection.add(
        ids=ids,
        documents=chunks,
        metadatas=metadatas,
        embeddings=embed(chunks),
    )
    return len(chunks)


def list_documents(client: Any, collection_name: str = "kb_public") -> list[dict[str, Any]]:
    try:
        collection = client.get_collection(collection_name)
    except Exception:  # noqa: BLE001
        return []
    result = collection.get(include=["metadatas"])
    documents: dict[str, dict[str, Any]] = {}
    for metadata in result.get("metadatas") or []:
        if not isinstance(metadata, dict):
            continue
        doc_id = metadata.get("doc_id")
        if not doc_id:
            continue
        entry = documents.setdefault(
            str(doc_id),
            {
                "doc_id": str(doc_id),
                "title": str(metadata.get("title", "")),
                "doc_type": str(metadata.get("doc_type", "")),
                "source": str(metadata.get("source", "")),
                "effective_date": str(metadata.get("effective_date", "")),
                "expire_date": str(metadata.get("expire_date", "")),
                "chunk_count": 0,
            },
        )
        entry["chunk_count"] += 1
    return sorted(documents.values(), key=lambda item: item["title"])


def delete_document(client: Any, *, doc_id: str, collection_name: str = "kb_public") -> int:
    try:
        collection = client.get_collection(collection_name)
    except Exception:  # noqa: BLE001
        return 0
    existing = collection.get(where={"doc_id": doc_id}, include=["metadatas"])
    ids = existing.get("ids") or []
    if ids:
        collection.delete(ids=ids)
    return len(ids)


def search_knowledge(
    client: Any,
    *,
    query: str,
    collections: list[str] | None,
    user_id: str,
    embedder: Embedder | None = None,
    top_k: int = 5,
    include_expired: bool = False,
) -> list[Citation]:
    embed = embedder or default_embedder
    allowed = resolve_collections(collections, user_id=user_id)
    where = None
    if not include_expired:
        where = {"expire_ts": {"$gte": int(datetime.now(UTC).timestamp())}}

    candidates: list[Citation] = []
    query_vector = embed([query])
    for name in allowed:
        try:
            collection = client.get_collection(name)
        except Exception:  # noqa: BLE001
            continue
        result = collection.query(
            query_embeddings=query_vector,
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        for document, metadata, distance in zip(documents, metadatas, distances, strict=False):
            if not isinstance(metadata, dict):
                continue
            score = max(0.0, 1.0 - float(distance))
            candidates.append(
                Citation(
                    index=0,
                    doc_id=str(metadata.get("doc_id", "")),
                    title=str(metadata.get("title", "")),
                    doc_type=str(metadata.get("doc_type", "")),
                    effective_date=str(metadata.get("effective_date", "")),
                    expire_date=str(metadata["expire_date"])
                    if metadata.get("expire_date")
                    else None,
                    snippet=document,
                    score=score,
                )
            )

    candidates.sort(key=lambda citation: citation.score, reverse=True)
    top = candidates[:top_k]
    return [
        Citation(
            index=index + 1,
            doc_id=citation.doc_id,
            title=citation.title,
            doc_type=citation.doc_type,
            effective_date=citation.effective_date,
            expire_date=citation.expire_date,
            snippet=citation.snippet,
            score=citation.score,
        )
        for index, citation in enumerate(top)
    ]


@lru_cache
def _embedding_model() -> Any:
    import os

    from app.core.config import get_settings

    # huggingface_hub 在导入时读取这些变量，必须早于 fastembed 导入。
    os.environ.setdefault("HF_ENDPOINT", get_settings().hf_endpoint)
    # hf-mirror 的 Xet CDN 可能返回 401，禁用后走普通下载。
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    from fastembed import TextEmbedding

    return TextEmbedding(model_name="BAAI/bge-small-zh-v1.5")


def default_embedder(texts: list[str]) -> list[list[float]]:
    model = _embedding_model()
    return [[float(value) for value in vector] for vector in model.embed(texts)]
