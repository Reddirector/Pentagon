"""Deleting a thread has to remove what it stored outside the database.

The confirm dialog in the sidebar and in Settings tells the user that deleting
a thread "removes the thread and its messages from the server". That was only
ever true of the SQL rows. Uploaded images were written to
``image_uploads/<conversation id>/`` and every chunk of every uploaded document
was embedded into a Chroma collection named after a hash of the conversation
id. Both survived the delete, so the full text of an indexed document and every
picture sent to a thread stayed on disk indefinitely after the UI promised it
was gone.

Now the delete path also clears the langgraph checkpointer state for that
conversation id, so a deleted thread cannot be resumed from a stale interrupt
snapshot.
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
from app.services.checkpointer import is_sqlite_backend, sqlite_checkpoint_path

pytestmark = pytest.mark.skipif(
    not is_sqlite_backend(),
    reason=(
        "asserts the SQLite checkpoint file on disk; the Postgres purge path is "
        "covered by tests/test_postgres_backend.py"
    ),
)


def _checkpoint_db_path() -> Path:
    """The SQLite checkpointer the chat route uses for interrupt state."""
    return Path(sqlite_checkpoint_path())


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


def test_delete_conversation_clears_its_checkpoint_state(
    client: TestClient,
) -> None:
    """A deleted conversation must not keep its interrupt/approval state.

    The chat route builds its langgraph config as
    ``{"configurable": {"thread_id": conversation.id}}`` and never passes a
    namespace of its own, and ``adelete_thread(thread_id)`` is what the delete
    path calls. This writes a synthetic interrupt into the same thread, then
    proves the delete path actually clears it.
    """
    import asyncio

    from langgraph.checkpoint.base import Checkpoint
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Interrupt

    user_id, conversation_id = _seed_conversation_with_image()
    db_path = _checkpoint_db_path()
    checkpoint_config = {
        "configurable": {
            "thread_id": conversation_id,
            "checkpoint_ns": "",
            "checkpoint_id": "test-checkpoint",
        },
    }

    async def _write_interrupt_state() -> None:
        # Writing first is what creates langgraph's lazily-created tables in a
        # fresh database, so the read below must never hit "no such table".
        async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
            await saver.aput(
                checkpoint_config,
                checkpoint=Checkpoint(
                    v=0,
                    id="test-checkpoint",
                    ts="0",
                    channel_values={},
                    channel_versions={},
                    versions_seen={},
                    updated_channels=None,
                ),
                metadata={"source": "test", "step": 0},
                new_versions={},
            )
            await saver.aput_writes(
                checkpoint_config,
                writes=(
                    (
                        "__ interrupt __",
                        Interrupt(
                            value={
                                "type": "approval_required",
                                "tool_call_id": "pending",
                                "user_id": user_id,
                                "label": "Some tool",
                                "summary": "Do something.",
                            }
                        ),
                    ),
                ),
                task_id="test-task",
            )

    async def _read_interrupt_state() -> object | None:
        async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
            stored = await saver.aget_tuple(checkpoint_config)
            if stored is None or not stored.pending_writes:
                return None
            for _task_id, _channel, payload in stored.pending_writes:
                return payload
            return None

    asyncio.run(_write_interrupt_state())
    before = asyncio.run(_read_interrupt_state())
    assert before is not None

    response = client.delete(f"/api/conversations/{conversation_id}?user_id={user_id}")
    assert response.status_code == 204

    assert asyncio.run(_read_interrupt_state()) is None
