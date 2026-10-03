"""Retrieval must not depend on the API that happens to be configured today.

These tests pin the failure the app actually hit: a collection built with a
remote embedding model stops answering as soon as the key is replaced, revoked
or simply no longer serves that model, because the query can no longer be
encoded in the same space as the stored chunks.

They drive the coroutines with asyncio.run rather than an async plugin, since
the project has no async test runner configured.
"""

import asyncio
import hashlib
import re
from uuid import uuid4

import pytest

from app.config import settings
from app.services import document_store
from app.services.document_store import (
    LOCAL_EMBEDDING_PROVIDER,
    collection_name_for_conversation,
    retrieve_chunks,
    store_chunks,
)


REMOTE_PROVIDER = "nvidia:test-embed-model"
CHUNKS = [
    "Project Zephyr uses a cobalt rotor and a 17-stage pressure valve.",
    "The maintenance interval is 82 days.",
]


def _deterministic_vector(text: str, dimensions: int, salt: str) -> list[float]:
    vector = [0.0] * dimensions
    for token in re.findall(r"[a-z0-9]+", f"{salt}{text.lower()}"):
        digest = hashlib.sha256(token.encode()).digest()
        vector[int.from_bytes(digest[:4], "big") % dimensions] += 1.0
    norm = sum(value * value for value in vector) ** 0.5 or 1.0
    return [value / norm for value in vector]


@pytest.fixture(autouse=True)
def isolated_chroma(tmp_path, monkeypatch):
    """A private Chroma directory per test, since the client is cached."""
    monkeypatch.setattr(settings, "chroma_persist_directory", str(tmp_path / "chroma"))
    document_store._client.cache_clear()
    yield
    document_store._client.cache_clear()


@pytest.fixture
def remote_model(monkeypatch):
    """Control the remote provider: its dimension and whether it still works."""
    state = {"available": True, "dimension": 64}

    async def choose(user_id: str, api_key: str | None) -> str:
        return REMOTE_PROVIDER

    async def embed(texts: list[str], provider: str, api_key: str | None, input_type: str):
        if provider.startswith("nvidia:"):
            if not state["available"]:
                raise RuntimeError("An NVIDIA key is required for this conversation's embedding model.")
            return [_deterministic_vector(text, state["dimension"], "remote") for text in texts]
        return [_deterministic_vector(text, 16, "local") for text in texts]

    monkeypatch.setattr(document_store, "choose_embedding_provider", choose)
    monkeypatch.setattr(document_store, "embed_texts", embed)
    return state


def _store(conversation_id: str, chunks: list[str] | None = None) -> None:
    async def run() -> None:
        await store_chunks(
            conversation_id=conversation_id,
            document_id=str(uuid4()),
            filename="zephyr.md",
            chunks=chunks if chunks is not None else CHUNKS,
            user_id="rag-test-user",
            api_key="nvapi-test",
        )

    asyncio.run(run())


def _retrieve(conversation_id: str, query: str, api_key: str | None) -> list[dict]:
    async def run() -> list[dict]:
        return await retrieve_chunks(conversation_id=conversation_id, query=query, api_key=api_key)

    return asyncio.run(run())


def _provider_of(conversation_id: str) -> str | None:
    collection = document_store._get_collection(collection_name_for_conversation(conversation_id))
    if collection is None:
        return None
    return (collection.metadata or {}).get("embedding_provider")


def test_retrieval_works_while_the_api_is_available(remote_model):
    conversation_id = str(uuid4())

    _store(conversation_id)
    hits = _retrieve(conversation_id, "pressure valve", "nvapi-test")

    assert len(hits) == len(CHUNKS)
    assert {hit["filename"] for hit in hits} == {"zephyr.md"}
    assert _provider_of(conversation_id) == REMOTE_PROVIDER


def test_retrieval_survives_the_key_being_replaced(remote_model):
    conversation_id = str(uuid4())
    _store(conversation_id)

    # The key is gone, or no longer serves the embedding model.
    remote_model["available"] = False
    hits = _retrieve(conversation_id, "pressure valve", None)

    assert len(hits) == len(CHUNKS)
    # And the collection is now free of the API for good.
    assert _provider_of(conversation_id) == LOCAL_EMBEDDING_PROVIDER


def test_recovery_is_sticky_across_further_key_changes(remote_model):
    conversation_id = str(uuid4())
    _store(conversation_id)

    remote_model["available"] = False
    _retrieve(conversation_id, "valve", None)

    # A brand new key arrives offering a different embedding model entirely.
    remote_model["available"] = True
    remote_model["dimension"] = 32
    hits = _retrieve(conversation_id, "valve", "nvapi-other")

    assert len(hits) == len(CHUNKS)
    assert _provider_of(conversation_id) == LOCAL_EMBEDDING_PROVIDER


def test_uploading_a_second_document_survives_the_api_disappearing(remote_model):
    conversation_id = str(uuid4())
    _store(conversation_id, ["The rotor is cobalt."])

    remote_model["available"] = False
    _store(conversation_id, ["The valve has 17 stages."])

    # Both documents must still be retrievable and share one embedding space.
    collection = document_store._get_collection(collection_name_for_conversation(conversation_id))
    assert collection is not None
    assert collection.count() == 2
    assert _provider_of(conversation_id) == LOCAL_EMBEDDING_PROVIDER

    hits = _retrieve(conversation_id, "valve", None)
    assert {hit["content"] for hit in hits} == {
        "The rotor is cobalt.",
        "The valve has 17 stages.",
    }


def test_an_empty_collection_does_not_keep_a_stale_provider(remote_model):
    conversation_id = str(uuid4())
    name = collection_name_for_conversation(conversation_id)

    # A collection left behind by an aborted upload, still pinned to a remote model.
    document_store._client().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine", "embedding_provider": REMOTE_PROVIDER},
        embedding_function=None,
    )
    assert _provider_of(conversation_id) == REMOTE_PROVIDER

    remote_model["available"] = False
    _store(conversation_id)

    assert _provider_of(conversation_id) == LOCAL_EMBEDDING_PROVIDER
    assert len(_retrieve(conversation_id, "valve", None)) == len(CHUNKS)


def test_a_conversation_pinned_locally_never_needs_the_api(remote_model, monkeypatch):
    conversation_id = str(uuid4())

    async def choose_local(user_id: str, api_key: str | None) -> str:
        return LOCAL_EMBEDDING_PROVIDER

    monkeypatch.setattr(document_store, "choose_embedding_provider", choose_local)
    _store(conversation_id)

    assert _provider_of(conversation_id) == LOCAL_EMBEDDING_PROVIDER

    # Even a working remote key is irrelevant: nothing here depends on the API.
    remote_model["available"] = False
    assert len(_retrieve(conversation_id, "valve", "nvapi-test")) == len(CHUNKS)


def test_migration_preserves_chunk_identity_and_metadata(remote_model):
    conversation_id = str(uuid4())
    _store(conversation_id)

    collection = document_store._get_collection(collection_name_for_conversation(conversation_id))
    before = collection.get(include=["documents", "metadatas"])
    before_by_id = {row: before["ids"].index(row) for row in before["ids"]}
    filenames = {row: before["metadatas"][index]["filename"] for row, index in before_by_id.items()}

    remote_model["available"] = False
    _retrieve(conversation_id, "valve", None)

    migrated = document_store._get_collection(collection_name_for_conversation(conversation_id))
    after = migrated.get(include=["documents", "metadatas"])

    assert sorted(after["ids"]) == sorted(before["ids"])
    assert sorted(after["documents"]) == sorted(before["documents"])
    assert {row: after["metadatas"][index]["filename"] for row, index in
            {row: after["ids"].index(row) for row in after["ids"]}.items()} == filenames