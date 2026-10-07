"""Legacy -> RAG 2 migration: dry-run, verify, then (only then) delete.

The one dangerous moment in this whole upgrade is the deletion of a store
nobody has verified a replacement for, so that is what the tests circle: a
dry run that changes nothing, an apply that verifies counts before the purge,
and a failure at any step that leaves the original exactly as it was.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config import settings
from app.db.models import Collection, Conversation, ConversationCollection, Document, User
from app.db.session import SessionLocal
from app.rag2 import migrate as migrate_module
from app.rag2.migrate import migrate
from app.rag2.store import chroma_collection_name, purge_collection_vectors
from app.services.document_store import (
    _client,
    _get_collection,
    collection_name_for_conversation,
    purge_conversation_collection,
)

LOCAL_PROVIDER = f"local:{settings.local_embedding_model}"


class Created:
    """What a test made in Chroma, so teardown can leave no residue."""

    def __init__(self) -> None:
        self.conversations: list[str] = []
        self.collections: list[str] = []


@pytest.fixture
def created() -> Iterator[Created]:
    made = Created()
    yield made
    for conversation_id in made.conversations:
        purge_conversation_collection(conversation_id)
    for collection_id in made.collections:
        purge_collection_vectors(collection_id)


def _seed(
    created: Created,
    files: dict[str, list[str]],
    *,
    provider: str = LOCAL_PROVIDER,
    title: str = "Migrated thread",
) -> tuple[str, str, list[str]]:
    """One conversation with documents, chunked the old way (inside Chroma)."""
    user_id = f"mig-{uuid4()}"
    conversation_id = str(uuid4())
    created.conversations.append(conversation_id)
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.add(Conversation(id=conversation_id, user_id=user_id, title=title))
        db.flush()
        document_ids: list[str] = []
        ids: list[str] = []
        texts: list[str] = []
        metadatas: list[dict] = []
        for filename, chunks in files.items():
            document = Document(
                user_id=user_id,
                conversation_id=conversation_id,
                collection_name=collection_name_for_conversation(conversation_id),
                filename=filename,
                chunk_count=len(chunks),
            )
            db.add(document)
            db.flush()
            document_ids.append(document.id)
            for index, text in enumerate(chunks):
                ids.append(f"{document.id}:{index}")
                texts.append(text)
                metadatas.append(
                    {
                        "document_id": document.id,
                        "conversation_id": conversation_id,
                        "filename": filename,
                        "chunk_index": index,
                    }
                )
        db.commit()

    client = _client()
    store = client.get_or_create_collection(
        name=collection_name_for_conversation(conversation_id),
        metadata={"hnsw:space": "cosine", "embedding_provider": provider},
        embedding_function=None,
    )
    store.add(
        ids=ids,
        embeddings=[[0.1, 0.2, 0.3] for _ in ids],
        documents=texts,
        metadatas=metadatas,
    )
    return user_id, conversation_id, document_ids


def _collection_for(conversation_id: str, user_id: str) -> Collection | None:
    with SessionLocal() as db:
        link = db.scalar(
            select(ConversationCollection).where(
                ConversationCollection.conversation_id == conversation_id
            )
        )
        if link is None:
            return None
        collection = db.get(Collection, link.collection_id)
        if collection is None or collection.user_id != user_id:
            return None
        db.expunge(collection)
        return collection


def _chunks(collection_id: str):
    from app.db.models import Chunk

    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(Chunk)
                .where(Chunk.collection_id == collection_id)
                .order_by(Chunk.file_id, Chunk.ord)
            )
        )
        for row in rows:
            db.expunge(row)
        return rows


def _spying_embedder() -> tuple[list[list[str]], object]:
    calls: list[list[str]] = []

    def embed(texts: list[str]) -> list[list[float]]:
        calls.append(list(texts))
        return [[0.9, 0.8, 0.7] for _ in texts]

    return calls, embed


def test_dry_run_reports_and_touches_nothing(created: Created) -> None:
    user_id, conversation_id, document_ids = _seed(
        created,
        {"a.txt": ["alpha chunk", "beta chunk"], "b.txt": ["gamma chunk"]},
    )
    calls, embed = _spying_embedder()
    lines: list[str] = []

    with SessionLocal() as db:
        report = migrate(
            db,
            dry_run=True,
            embed_fn=embed,
            emit=lines.append,
            only=[conversation_id],
        )

    assert report.ok and report.dry_run is True
    assert len(report.planned) == 1
    assert report.migrated == [] and report.failed == []
    plan = report.planned[0]
    assert plan.chunk_count == 3
    assert sorted(plan.file_ids) == sorted(document_ids)
    assert plan.reembed is False, "local -> local must not propose a re-embed"
    assert any("[dry-run]" in line and "3 chunk(s)" in line for line in lines)
    assert calls == [], "a dry run must not spend a single embedding call"

    # Nothing changed: no collection row, no link, and the old store is whole.
    assert _collection_for(conversation_id, user_id) is None
    legacy = _get_collection(collection_name_for_conversation(conversation_id))
    assert legacy is not None and legacy.count() == 3


def test_apply_copies_vectors_and_purges_legacy_only_after_counts_match(
    created: Created,
) -> None:
    user_id, conversation_id, document_ids = _seed(
        created,
        {"a.txt": ["alpha chunk", "beta chunk"], "b.txt": ["gamma chunk"]},
    )
    calls, embed = _spying_embedder()
    lines: list[str] = []

    with SessionLocal() as db:
        report = migrate(
            db, embed_fn=embed, emit=lines.append, only=[conversation_id]
        )

    assert report.ok and len(report.migrated) == 1
    assert calls == [], "same model on both sides: vectors must be copied, not recomputed"

    collection = _collection_for(conversation_id, user_id)
    assert collection is not None
    created.collections.append(collection.id)
    assert collection.embedding_model == f"{settings.embedding_model}@1"

    chunks = _chunks(collection.id)
    assert {c.file_id for c in chunks} == set(document_ids)
    # Within a file, order is preserved; the file grouping itself is by id.
    texts_by_file = {
        file_id: [c.text for c in chunks if c.file_id == file_id]
        for file_id in document_ids
    }
    assert texts_by_file[document_ids[0]] == ["alpha chunk", "beta chunk"]
    assert texts_by_file[document_ids[1]] == ["gamma chunk"]
    assert all(c.user_id == user_id for c in chunks)
    # ord is per file: a.txt's two chunks are 0 and 1, not a global counter.
    a_orders = sorted(c.ord for c in chunks if c.file_id == document_ids[0])
    assert a_orders == [0, 1]

    vectors = _get_collection(chroma_collection_name(collection.id))
    assert vectors is not None and vectors.count() == 3
    assert _get_collection(collection_name_for_conversation(conversation_id)) is None, (
        "the legacy store must go only after verification"
    )
    assert any("[done]" in line for line in lines)


def test_model_change_reembeds_from_text(created: Created) -> None:
    user_id, conversation_id, _document_ids = _seed(
        created,
        {"a.txt": ["alpha chunk", "beta chunk"]},
        provider="nvidia:nemotron-3-embed-1b",
    )
    calls, embed = _spying_embedder()

    with SessionLocal() as db:
        report = migrate(db, embed_fn=embed, emit=lambda _line: None, only=[conversation_id])

    assert report.ok
    plan = report.planned[0]
    assert plan.reembed is True, "a different model must re-embed, never mix spaces"
    assert calls == [["alpha chunk", "beta chunk"]]

    collection = _collection_for(conversation_id, user_id)
    assert collection is not None
    created.collections.append(collection.id)
    store = _get_collection(chroma_collection_name(collection.id))
    assert store is not None
    payload = store.get(include=["embeddings"])
    flat = [value for row in payload["embeddings"].tolist() for value in row]
    assert flat == pytest.approx([0.9, 0.8, 0.7, 0.9, 0.8, 0.7]), (
        "the re-embedded vectors must be what the embedder returned"
    )
    assert _get_collection(collection_name_for_conversation(conversation_id)) is None


def test_failed_embedding_keeps_the_original_store(created: Created) -> None:
    user_id, conversation_id, _document_ids = _seed(
        created,
        {"a.txt": ["alpha chunk", "beta chunk"]},
        provider="nvidia:nemotron-3-embed-1b",
    )

    def explode(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("no key, no vectors")

    with SessionLocal() as db:
        report = migrate(db, embed_fn=explode, emit=lambda _line: None, only=[conversation_id])

    assert not report.ok
    assert report.failed and report.failed[0][0] == conversation_id
    assert "no key" in report.failed[0][1]
    legacy = _get_collection(collection_name_for_conversation(conversation_id))
    assert legacy is not None and legacy.count() == 2, (
        "a failed re-embed must never cost the original data"
    )
    # The partial rows are resumable: running again must not error out.
    assert _collection_for(conversation_id, user_id) is not None


def test_verification_failure_keeps_the_original_store(
    created: Created, monkeypatch
) -> None:
    user_id, conversation_id, _document_ids = _seed(
        created, {"a.txt": ["alpha chunk", "beta chunk"]}
    )

    monkeypatch.setattr(migrate_module, "_verify", lambda *args, **kwargs: False)

    with SessionLocal() as db:
        report = migrate(
            db, embed_fn=lambda texts: [[0.1, 0.2, 0.3] for _ in texts],
            emit=lambda _line: None,
            only=[conversation_id],
        )

    assert not report.ok
    assert "Verification failed" in report.failed[0][1]
    legacy = _get_collection(collection_name_for_conversation(conversation_id))
    assert legacy is not None and legacy.count() == 2
    # The vectors written before the failed verification are tracked for cleanup.
    collection = _collection_for(conversation_id, user_id)
    if collection is not None:
        created.collections.append(collection.id)


def test_conversation_without_legacy_store_is_skipped(created: Created) -> None:
    user_id, conversation_id, _document_ids = _seed(created, {"a.txt": ["alpha"]})
    # Remove the legacy store: as if the app already cleaned up.
    purge_conversation_collection(conversation_id)

    with SessionLocal() as db:
        report = migrate(db, embed_fn=lambda texts: [], emit=lambda _line: None, only=[conversation_id])

    assert report.ok
    assert report.planned == [] and report.migrated == []
    assert report.skipped and report.skipped[0][0] == conversation_id
    assert _collection_for(conversation_id, user_id) is None


def test_chunks_of_deleted_files_are_not_migrated(created: Created) -> None:
    user_id, conversation_id, document_ids = _seed(
        created, {"a.txt": ["alpha", "beta"], "gone.txt": ["orphan"]}
    )
    # The second document's row was deleted (its vectors were not).
    with SessionLocal() as db:
        db.delete(db.get(Document, document_ids[1]))
        db.commit()

    calls, embed = _spying_embedder()
    with SessionLocal() as db:
        report = migrate(db, embed_fn=embed, emit=lambda _line: None, only=[conversation_id])

    assert report.ok and len(report.migrated) == 1
    plan = report.planned[0]
    assert plan.chunk_count == 2, "a chunk whose file row is gone has no home"
    assert plan.skipped_unattributed == 1

    collection = _collection_for(conversation_id, user_id)
    assert collection is not None
    created.collections.append(collection.id)
    chunks = _chunks(collection.id)
    assert [c.text for c in chunks] == ["alpha", "beta"]
    vectors = _get_collection(chroma_collection_name(collection.id))
    assert vectors is not None and vectors.count() == 2


def test_second_run_resumes_without_duplicates(
    created: Created, monkeypatch
) -> None:
    """A run that failed verification leaves rows; re-running finishes the job."""
    user_id, conversation_id, document_ids = _seed(
        created, {"a.txt": ["alpha", "beta"]}
    )
    verdicts = iter([False, True])
    monkeypatch.setattr(
        migrate_module, "_verify", lambda *args, **kwargs: next(verdicts)
    )
    embed = lambda texts: [[0.1, 0.2, 0.3] for _ in texts]  # noqa: E731

    with SessionLocal() as db:
        first = migrate(db, embed_fn=embed, emit=lambda _line: None, only=[conversation_id])
    assert not first.ok, "the first run must fail verification"
    collection = _collection_for(conversation_id, user_id)
    assert collection is not None
    created.collections.append(collection.id)
    assert len(_chunks(collection.id)) == 2
    assert _get_collection(collection_name_for_conversation(conversation_id)) is not None

    with SessionLocal() as db:
        second = migrate(db, embed_fn=embed, emit=lambda _line: None, only=[conversation_id])

    assert second.ok and len(second.migrated) == 1
    chunks = _chunks(collection.id)
    assert [c.text for c in chunks if c.file_id == document_ids[0]] == ["alpha", "beta"], (
        "a resumed run must not duplicate or drop chunks"
    )
    assert len(chunks) == 2
    vectors = _get_collection(chroma_collection_name(collection.id))
    assert vectors is not None and vectors.count() == 2
    assert _get_collection(collection_name_for_conversation(conversation_id)) is None
    # One link row, not one per run.
    with SessionLocal() as db:
        links = list(
            db.scalars(
                select(ConversationCollection).where(
                    ConversationCollection.conversation_id == conversation_id
                )
            )
        )
        assert len(links) == 1
