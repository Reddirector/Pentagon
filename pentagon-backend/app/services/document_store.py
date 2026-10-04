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
    is_remote_provider,
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


def purge_conversation_collection(conversation_id: str) -> bool:
    """Drop every chunk indexed for a conversation.

    The database cascades the ``documents`` rows when a thread is deleted, but
    the vectors live in Chroma, keyed by a hash of the conversation id. Without
    this the full text of every uploaded document outlived the thread that was
    supposed to have removed it.

    Returns True when a collection was actually deleted.
    """
    name = collection_name_for_conversation(conversation_id)
    if _get_collection(name) is None:
        return False
    _client().delete_collection(name)
    logger.info("Purged vector collection %s for a deleted conversation", name)
    return True


async def _rebuild_with_local_embeddings(name: str, collection) -> Any:
    """Re-encode an existing collection with the local model.

    Embedding spaces are not interchangeable: a remote model and the local
    model disagree on both meaning and dimension, and a Chroma collection can
    only ever hold one space. So when the pinned provider stops working -- the
    key was replaced, revoked, or the model is no longer served -- the stored
    chunks are re-embedded locally instead of being abandoned. Pinning the
    result to the local provider also means later key changes cannot break
    this collection again.

    The new vectors are computed before the store is touched, so a failure
    here leaves the original collection exactly as it was.
    """
    existing = await asyncio.to_thread(collection.get, include=["documents", "metadatas"])
    ids = list(existing.get("ids") or [])
    documents = list(existing.get("documents") or [])
    metadatas = list(existing.get("metadatas") or [])
    metadatas.extend({} for _ in range(len(ids) - len(metadatas)))

    vectors = await embed_texts(documents, LOCAL_EMBEDDING_PROVIDER, None, "passage") if documents else []

    client = _client()
    await asyncio.to_thread(client.delete_collection, name)
    rebuilt = client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine", "embedding_provider": LOCAL_EMBEDDING_PROVIDER},
        embedding_function=None,
    )
    if ids:
        await asyncio.to_thread(
            rebuilt.add,
            ids=ids,
            embeddings=vectors,
            documents=documents,
            metadatas=metadatas,
        )
    logger.info("Re-embedded collection %s locally after its provider became unusable", name)
    return rebuilt


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
        # Existing vectors define the space this collection lives in.
        provider = (collection.metadata or {}).get("embedding_provider", LOCAL_EMBEDDING_PROVIDER)
    else:
        # Empty or absent, so the space can still be chosen freely. Drop an
        # empty collection first, otherwise its recorded provider would be kept
        # while the vectors below came from a different one.
        if collection is not None:
            await asyncio.to_thread(_client().delete_collection, name)
            collection = None
        provider = await choose_embedding_provider(user_id, api_key)

    try:
        vectors = await embed_texts(chunks, provider, api_key, "passage")
    except Exception as exc:
        if provider == LOCAL_EMBEDDING_PROVIDER:
            raise
        logger.warning(
            "Embedding provider %s failed during upload (%s); falling back to local embeddings",
            provider,
            exc,
        )
        if collection is not None and collection.count() > 0:
            # Never mix spaces: bring the stored vectors into the local space too.
            collection = await _rebuild_with_local_embeddings(name, collection)
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
    name = collection_name_for_conversation(conversation_id)
    collection = _get_collection(name)
    if collection is None:
        return []
    count = collection.count()
    if count == 0:
        return []

    provider = (collection.metadata or {}).get("embedding_provider", LOCAL_EMBEDDING_PROVIDER)
    try:
        query_vector = (await embed_texts([query], provider, api_key, "query"))[0]
        results = await asyncio.to_thread(
            collection.query,
            query_embeddings=[query_vector],
            n_results=min(limit, count),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        if not is_remote_provider(provider):
            raise
        # The pinned provider is an API model and it is no longer usable --
        # a replaced or revoked key, or a model that is no longer served.
        # Retrieval must survive that: re-encode the collection locally once
        # and answer from it, rather than failing the whole turn.
        logger.warning(
            "Pinned embedding provider %s is unusable for retrieval (%s); re-embedding locally",
            provider,
            exc,
        )
        collection = await _rebuild_with_local_embeddings(name, collection)
        provider = LOCAL_EMBEDDING_PROVIDER
        query_vector = (await embed_texts([query], provider, None, "query"))[0]
        results = await asyncio.to_thread(
            collection.query,
            query_embeddings=[query_vector],
            n_results=min(limit, collection.count()),
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
