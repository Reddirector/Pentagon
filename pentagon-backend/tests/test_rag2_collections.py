"""Collections: CRUD works, and nobody reads somebody else's rows.

The Supabase half of the isolation contract lives in
``supabase/migrations/rag2.sql`` (RLS enabled + ``own rows`` policies); the
local-first half is that every query here filters on ``user_id``. Both are
under test, because a policy file nobody executes and a query nobody scopes
are the same as having neither.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.models import Chunk, Collection, Conversation, ConversationCollection, Document, IndexJob, User
from app.db.session import SessionLocal
from app.main import app
from app.rag2 import collections as service
from app.rag2.store import chroma_collection_name

RAG_SQL = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "rag2.sql"

RLS_TABLES = [
    "collections",
    "collection_files",
    "conversation_collections",
    "chunks",
    "kg_entities",
    "kg_relations",
    "kg_provenance",
    "kg_communities",
    "index_jobs",
]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def pair() -> tuple[str, str]:
    """(owner, intruder), two local users with a conversation each."""
    owner = f"col-owner-{uuid4()}"
    intruder = f"col-intruder-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=owner))
        db.add(User(id=intruder))
        db.commit()
        db.add(Conversation(id=str(uuid4()), user_id=owner, title="Owner thread"))
        db.add(Conversation(id=str(uuid4()), user_id=intruder, title="Intruder thread"))
        db.commit()
    return owner, intruder


def _seed_file(user_id: str, conversation_id: str) -> str:
    with SessionLocal() as db:
        document = Document(
            user_id=user_id,
            conversation_id=conversation_id,
            collection_name="legacy",
            filename="notes.txt",
            chunk_count=1,
        )
        db.add(document)
        db.commit()
        return document.id


def _conversation_id(user_id: str) -> str:
    from sqlalchemy import select

    with SessionLocal() as db:
        return db.scalar(
            select(Conversation.id).where(
                Conversation.user_id == user_id, Conversation.title.like("%thread")
            )
        )


def test_create_list_get_rename_delete(client: TestClient, pair: tuple[str, str]) -> None:
    owner, _intruder = pair
    created = client.post(
        "/api/collections",
        json={"user_id": owner, "name": "Policy docs", "description": "v1"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    collection_id = body["id"]
    # The stored model is an id@version ref, never a bare name: a version bump
    # must be able to invalidate vectors.
    assert body["embedding_model"].endswith("@1")
    assert body["file_count"] == 0 and body["chunk_count"] == 0

    listed = client.get(f"/api/collections?user_id={owner}").json()
    assert [row["id"] for row in listed] == [collection_id]

    renamed = client.patch(
        f"/api/collections/{collection_id}?user_id={owner}", json={"name": "Policy v2"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Policy v2"

    deleted = client.delete(f"/api/collections/{collection_id}?user_id={owner}")
    assert deleted.status_code == 204
    assert client.get(f"/api/collections/{collection_id}?user_id={owner}").status_code == 404


def test_foreign_collection_is_a_404_everywhere(client: TestClient, pair: tuple[str, str]) -> None:
    owner, intruder = pair
    collection_id = client.post(
        "/api/collections", json={"user_id": owner, "name": "Private"}
    ).json()["id"]

    assert client.get(f"/api/collections/{collection_id}?user_id={intruder}").status_code == 404
    assert (
        client.patch(
            f"/api/collections/{collection_id}?user_id={intruder}", json={"name": "Stolen"}
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/collections/{collection_id}?user_id={intruder}").status_code
        == 404
    )
    # And the row is untouched, not merely hidden.
    assert client.get(f"/api/collections/{collection_id}?user_id={owner}").json()["name"] == "Private"
    # The intruder's own list shows nothing of the owner's.
    assert client.get(f"/api/collections?user_id={intruder}").json() == []


def test_unknown_embedding_model_is_rejected_at_creation(client: TestClient, pair) -> None:
    owner, _intruder = pair
    response = client.post(
        "/api/collections",
        json={"user_id": owner, "name": "x", "embedding_model": "acme/unverified-model"},
    )
    assert response.status_code == 422, response.text
    # Rejected before storage: a collection whose model cannot embed is broken.
    with SessionLocal() as db:
        assert service.list_collections(db, owner) == []


def test_collection_cap_is_enforced(client: TestClient, pair, monkeypatch) -> None:
    owner, _intruder = pair
    monkeypatch.setattr(service, "MAX_COLLECTIONS_PER_USER", 1)
    assert client.post("/api/collections", json={"user_id": owner, "name": "one"}).status_code == 201
    assert client.post("/api/collections", json={"user_id": owner, "name": "two"}).status_code == 409


def test_files_attach_only_to_owned_documents(client: TestClient, pair: tuple[str, str]) -> None:
    owner, intruder = pair
    collection_id = client.post(
        "/api/collections", json={"user_id": owner, "name": "Files"}
    ).json()["id"]
    owner_file = _seed_file(owner, _conversation_id(owner))
    intruder_file = _seed_file(intruder, _conversation_id(intruder))

    ok = client.post(
        f"/api/collections/{collection_id}/files",
        json={"user_id": owner, "file_id": owner_file},
    )
    assert ok.status_code == 201, ok.text

    # Linking somebody else's document would make it readable through this
    # collection, so it must fail exactly like a foreign collection.
    stolen = client.post(
        f"/api/collections/{collection_id}/files",
        json={"user_id": owner, "file_id": intruder_file},
    )
    assert stolen.status_code == 404

    assert client.get(
        f"/api/collections/{collection_id}/files?user_id={owner}"
    ).json() == [owner_file]
    # The intruder cannot even list the collection's files.
    assert (
        client.get(f"/api/collections/{collection_id}/files?user_id={intruder}").status_code
        == 404
    )


def test_implicit_conversation_collection_is_created_once(client: TestClient, pair) -> None:
    owner, intruder = pair
    conversation_id = _conversation_id(owner)

    with SessionLocal() as db:
        first = service.ensure_conversation_collection(db, owner, conversation_id)
        second = service.ensure_conversation_collection(db, owner, conversation_id)
        assert first is not None and second is not None
        assert first.id == second.id, "a second upload must land in the same scope"
        assert first.name.startswith("Owner thread")

        other_conversation = client.post(
            "/api/conversations", json={"user_id": owner, "title": "Another"}
        ).json()["id"]
        third = service.ensure_conversation_collection(db, owner, other_conversation)
        assert third is not None and third.id != first.id

        # Scoped: the intruder asking about the owner's conversation gets nothing.
        assert service.ensure_conversation_collection(db, intruder, conversation_id) is None
        assert service.ensure_conversation_collection(db, owner, "no-such-conv") is None


def test_conversation_link_requires_both_sides(client: TestClient, pair: tuple[str, str]) -> None:
    owner, intruder = pair
    collection_id = client.post(
        "/api/collections", json={"user_id": owner, "name": "Scoped"}
    ).json()["id"]
    intruder_conversation = _conversation_id(intruder)

    denied = client.post(
        f"/api/collections/{collection_id}/conversations",
        json={"user_id": owner, "conversation_id": intruder_conversation},
    )
    assert denied.status_code == 404

    own_conversation = _conversation_id(owner)
    allowed = client.post(
        f"/api/collections/{collection_id}/conversations",
        json={"user_id": owner, "conversation_id": own_conversation},
    )
    assert allowed.status_code == 201
    assert client.get(
        f"/api/collections/{collection_id}/conversations?user_id={owner}"
    ).json() == [own_conversation]
    assert (
        client.get(
            f"/api/collections/{collection_id}/conversations?user_id={intruder}"
        ).status_code
        == 404
    )


def test_chunks_and_jobs_are_scoped_by_owner(pair: tuple[str, str]) -> None:
    """RLS-equivalent reads: a foreign id sees no rows, in every new table."""
    owner, intruder = pair
    conversation_id = _conversation_id(owner)
    file_id = _seed_file(owner, conversation_id)

    with SessionLocal() as db:
        collection = service.create_collection(db, user_id=owner, name="Chunks")
        db.add(
            Chunk(
                user_id=owner,
                collection_id=collection.id,
                file_id=file_id,
                ord=0,
                text="A passage only the owner may read.",
                lang="en",
                script="Latn",
            )
        )
        db.commit()

        assert len(service.list_chunks(db, owner, collection.id)) == 1
        assert service.list_chunks(db, intruder, collection.id) == []
        assert service.chunk_counts(db, owner, collection.id) == 1
        assert service.chunk_counts(db, intruder, collection.id) == 0
        assert service.get_collection(db, intruder, collection.id) is None

    from app.rag2.jobs import default_queue

    job = default_queue.enqueue(
        user_id=owner, collection_id=collection.id, kind="ingest"
    )
    assert default_queue.get(job.id, user_id=owner) is not None
    assert default_queue.get(job.id, user_id=intruder) is None
    assert [j.id for j in default_queue.list(owner)] == [job.id]
    assert default_queue.list(intruder) == []


def test_collection_delete_removes_rows_and_vectors(pair: tuple[str, str]) -> None:
    """Deletion leaves nothing behind: rows cascade, vectors are purged."""
    owner, _intruder = pair
    conversation_id = _conversation_id(owner)
    file_id = _seed_file(owner, conversation_id)

    with SessionLocal() as db:
        collection = service.create_collection(db, user_id=owner, name="Doomed")
        db.add(
            Chunk(
                user_id=owner,
                collection_id=collection.id,
                file_id=file_id,
                ord=0,
                text="soon gone",
            )
        )
        db.commit()
        collection_id = collection.id

    # Give it a vector store, as an indexed collection would have.
    from app.rag2 import store as vector_store
    from app.services.document_store import _client

    name = chroma_collection_name(collection_id)
    _client().get_or_create_collection(name=name, embedding_function=None)
    assert vector_store.collection_vectors(collection_id) is not None

    with SessionLocal() as db:
        assert service.delete_collection(db, owner, collection_id) is True

    with SessionLocal() as db:
        assert db.get(Collection, collection_id) is None
        assert service.list_chunks(db, owner, collection_id) == []
        from sqlalchemy import select

        links = list(
            db.scalars(
                select(ConversationCollection).where(
                    ConversationCollection.collection_id == collection_id
                )
            )
        )
        assert links == []
        jobs = list(
            db.scalars(select(IndexJob).where(IndexJob.collection_id == collection_id))
        )
        assert jobs == []
    assert vector_store.collection_vectors(collection_id) is None


def test_rag2_sql_enables_rls_with_owner_policies() -> None:
    """The Supabase deliverable must declare the same isolation we enforce."""
    sql = RAG_SQL.read_text(encoding="utf-8").lower()
    for table in RLS_TABLES:
        assert f"alter table {table} enable row level security;" in sql, (
            f"rag2.sql does not enable RLS on {table}"
        )
        policy = f'create policy "own rows" on {table} for all using (auth.uid() = user_id)'
        assert policy in sql, f"rag2.sql has no owner policy for {table}"
        assert "with check (auth.uid() = user_id)" in sql
