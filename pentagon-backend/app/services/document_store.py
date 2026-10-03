from __future__ import annotations

import asyncio
import hashlib
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

import chromadb

from app.config import settings
from app.services.embeddings import (
    LOCAL_EMBEDDING_PROVIDER,
    choose_embedding_provider,
    embed_texts,
)

logger = logging.getLogger(__name__)


def collection_name_for_conversation(conversation_id: str) -> str:
    digest = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()
    return f"pentagon_conv_{digest}"


@lru_cache(maxsize=1)
def _client() -> chromadb.PersistentClient:
    Path(settings.chroma_persist_directory).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=settings.chroma_persist_directory)


def _get_collection(name: str):
    client = _client()
    collection_names = {
        item.name if hasattr(item, "name") else str(item)
        for item in client.list_collections()
    }
    if name not in collection_names:
        return None
    return client.get_collection(name=name, embedding_function=None)


def has_documents(conversation_id: str) -> bool:
    collection = _get_collection(collection_name_for_conversation(conversation_id))
    return collection is not None and collection.count() > 0


async def store_chunks(
    *,
    conversation_id: str,
    document_id: str,
    filename: str,
    chunks: list[str],
    user_id: str,
    api_key: str | None,
) -> tuple[str, int]:
    name = collection_name_for_conversation(conversation_id)
    collection = _get_collection(name)
    if collection is not None and collection.count() > 0:
        provider = (collection.metadata or {}).get("embedding_provider", LOCAL_EMBEDDING_PROVIDER)
    else:
        provider = await choose_embedding_provider(user_id, api_key)

    try:
        vectors = await embed_texts(chunks, provider, api_key, "passage")
    except Exception:
        if (collection is not None and collection.count() > 0) or provider == LOCAL_EMBEDDING_PROVIDER:
            raise
        logger.warning("NVIDIA document embeddings failed; using local sentence-transformer embeddings")
        provider = LOCAL_EMBEDDING_PROVIDER
        vectors = await embed_texts(chunks, provider, None, "passage")

    if collection is None:
        collection = _client().get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine", "embedding_provider": provider},
            embedding_function=None,
        )

    chunk_ids = [str(uuid4()) for _ in chunks]
    metadatas = [
        {
            "document_id": document_id,
            "conversation_id": conversation_id,
            "filename": filename,
            "chunk_index": index,
        }
        for index in range(len(chunks))
    ]
    await asyncio.to_thread(
        collection.add,
        ids=chunk_ids,
        embeddings=vectors,
        documents=chunks,
        metadatas=metadatas,
    )
    return name, len(chunk_ids)


async def retrieve_chunks(
    *,
    conversation_id: str,
    query: str,
    api_key: str | None,
    limit: int = 4,
) -> list[dict[str, Any]]:
    collection = _get_collection(collection_name_for_conversation(conversation_id))
    if collection is None:
        return []
    count = collection.count()
    if count == 0:
        return []

    provider = (collection.metadata or {}).get("embedding_provider", LOCAL_EMBEDDING_PROVIDER)
    query_vector = (await embed_texts([query], provider, api_key, "query"))[0]
    results = await asyncio.to_thread(
        collection.query,
        query_embeddings=[query_vector],
        n_results=min(limit, count),
        include=["documents", "metadatas", "distances"],
    )

    documents = results.get("documents", [[]])[0]
    ids = results.get("ids", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    return [
        {
            "chunk_id": ids[index],
            "document_id": (metadatas[index] or {}).get("document_id"),
            "filename": (metadatas[index] or {}).get("filename", "document"),
            "content": documents[index],
            "distance": distances[index] if index < len(distances) else None,
        }
        for index in range(len(documents))
    ]


async def delete_document_chunks(collection_name: str, document_id: str) -> None:
    collection = _get_collection(collection_name)
    if collection is None:
        return
    await asyncio.to_thread(collection.delete, where={"document_id": document_id})
    if collection.count() == 0:
        await asyncio.to_thread(_client().delete_collection, collection_name)
