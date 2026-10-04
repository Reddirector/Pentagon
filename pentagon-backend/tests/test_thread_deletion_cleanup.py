"""Deleting a thread has to remove what it stored outside the database.

The confirm dialog in the sidebar and in Settings tells the user that deleting
a thread "removes the thread and its messages from the server". That was only
ever true of the SQL rows. Uploaded images were written to
``image_uploads/<conversation id>/`` and every chunk of every uploaded document
was embedded into a Chroma collection named after a hash of the conversation
id. Both survived the delete, so the full text of an indexed document and every
picture sent to a thread stayed on disk indefinitely after the UI promised it
was gone.
"""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.models import Conversation, Message, User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.services import document_store


@pytest.fixture
def client() -> TestClient:
    initialize_database()
    return TestClient(app)


@pytest.fixture
def upload_root(tmp_path, monkeypatch) -> Path:
    """Point the image upload directory at a throwaway tree for one test."""
    root = tmp_path / "image_uploads"
    root.mkdir()
    monkeypatch.setattr(settings, "image_upload_directory", str(root))
    return root


def _seed_conversation_with_image(upload_root: Path | None = None) -> tuple[str, str]:
    user_id = f"cleanup-test-{uuid4()}"
    conversation_id = str(uuid4())
    image_file = None
    if upload_root is not None:
        image_dir = upload_root / conversation_id
        image_dir.mkdir(parents=True)
        image_file = image_dir / f"{uuid4()}.png"
        image_file.write_bytes(b"\x89PNG\r\n\x1a\n not really a png")

    with SessionLocal() as db:
        db.add(User(id=user_id))
        conversation = Conversation(id=conversation_id, user_id=user_id, title="Has a picture")
        db.add(conversation)
        db.flush()
        db.add(
            Message(
                id=str(uuid4()),
                conversation_id=conversation_id,
                role="user",
                content="What is in this?",
                model_used="nvidia/test",
                image_path=str(image_file) if image_file else None,
            )
        )
        db.commit()
    return user_id, conversation_id


def test_delete_conversation_removes_its_uploaded_images(
    client: TestClient, upload_root: Path
) -> None:
    user_id, conversation_id = _seed_conversation_with_image(upload_root)
    assert (upload_root / conversation_id).exists()

    response = client.delete(f"/api/conversations/{conversation_id}?user_id={user_id}")

    assert response.status_code == 204
    assert not (upload_root / conversation_id).exists()


def test_delete_conversation_leaves_other_threads_images_alone(
    client: TestClient, upload_root: Path
) -> None:
    user_id, deleted_id = _seed_conversation_with_image(upload_root)
    _, kept_id = _seed_conversation_with_image(upload_root)

    client.delete(f"/api/conversations/{deleted_id}?user_id={user_id}")

    assert not (upload_root / deleted_id).exists()
    assert (upload_root / kept_id).exists()


def test_delete_conversation_purges_the_indexed_documents(
    client: TestClient, monkeypatch
) -> None:
    user_id, conversation_id = _seed_conversation_with_image()
    purged: list[str] = []
    monkeypatch.setattr(
        "app.routes.chat.purge_conversation_collection",
        lambda cid: purged.append(cid),
    )

    response = client.delete(f"/api/conversations/{conversation_id}?user_id={user_id}")

    assert response.status_code == 204
    assert purged == [conversation_id]


def test_delete_conversation_succeeds_when_vector_cleanup_fails(
    client: TestClient, monkeypatch
) -> None:
    """A Chroma failure must not turn a successful delete into a 500."""
    user_id, conversation_id = _seed_conversation_with_image()

    def explode(_conversation_id: str) -> None:
        raise RuntimeError("chroma is unavailable")

    monkeypatch.setattr("app.routes.chat.purge_conversation_collection", explode)

    response = client.delete(f"/api/conversations/{conversation_id}?user_id={user_id}")

    assert response.status_code == 204
    with SessionLocal() as db:
        assert db.get(Conversation, conversation_id) is None


def test_purge_conversation_collection_is_a_no_op_for_an_unknown_thread(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "chroma_persist_directory", str(tmp_path / "chroma"))
    document_store._client.cache_clear()

    assert document_store.purge_conversation_collection(str(uuid4())) is False


def test_purge_conversation_collection_drops_an_indexed_thread(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "chroma_persist_directory", str(tmp_path / "chroma"))
    document_store._client.cache_clear()
    conversation_id = str(uuid4())
    client = document_store._client()
    collection = client.get_or_create_collection(
        name=document_store.collection_name_for_conversation(conversation_id),
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )
    collection.add(
        ids=["a"],
        embeddings=[[0.1, 0.2, 0.3]],
        documents=["secret"],
        metadatas=[{"document_id": "doc-1"}],
    )

    assert document_store.purge_conversation_collection(conversation_id) is True
    assert document_store.has_documents(conversation_id) is False
