from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.models import Conversation, Document, Message, User
from app.db.session import SessionLocal, initialize_database
from app.main import app


@pytest.fixture
def client() -> TestClient:
    initialize_database()
    return TestClient(app)


def _seed_conversation(title: str = "Original title") -> tuple[str, str]:
    user_id = f"manage-test-{uuid4()}"
    conversation_id = str(uuid4())
    with SessionLocal() as db:
        db.add(User(id=user_id))
        conversation = Conversation(
            id=conversation_id,
            user_id=user_id,
            title=title,
            active_model="nvidia/nemotron-3-nano-30b-a3b",
        )
        db.add(conversation)
        # Flush the parents first: the messages and documents below reference
        # them, and SQLite enforces those foreign keys inside this transaction.
        db.flush()
        db.add(
            Message(
                id=str(uuid4()),
                conversation_id=conversation_id,
                role="user",
                content="What is the codeword?",
                model_used="nvidia/nemotron-3-nano-30b-a3b",
            )
        )
        db.add(
            Message(
                id=str(uuid4()),
                conversation_id=conversation_id,
                role="assistant",
                content="Violet.",
                model_used="nvidia/nemotron-3-nano-30b-a3b",
            )
        )
        db.add(
            Document(
                id=str(uuid4()),
                user_id=user_id,
                conversation_id=conversation_id,
                collection_name="manage-test",
                filename="notes.md",
                chunk_count=3,
            )
        )
        db.commit()
    return user_id, conversation_id


def test_rename_conversation_updates_title(client: TestClient) -> None:
    _user_id, conversation_id = _seed_conversation()

    response = client.patch(
        f"/api/conversations/{conversation_id}/title",
        json={"title": "  Deployment plan  "},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Deployment plan"
    with SessionLocal() as db:
        stored = db.get(Conversation, conversation_id)
        assert stored is not None
        assert stored.title == "Deployment plan"


def test_rename_conversation_rejects_blank_title(client: TestClient) -> None:
    _user_id, conversation_id = _seed_conversation()

    response = client.patch(
        f"/api/conversations/{conversation_id}/title",
        json={"title": "   "},
    )

    assert response.status_code == 422
    with SessionLocal() as db:
        stored = db.get(Conversation, conversation_id)
        assert stored is not None
        assert stored.title == "Original title"


def test_rename_unknown_conversation_is_404(client: TestClient) -> None:
    response = client.patch(
        "/api/conversations/does-not-exist/title",
        json={"title": "Anything"},
    )

    assert response.status_code == 404


def test_delete_conversation_removes_messages_and_documents(client: TestClient) -> None:
    user_id, conversation_id = _seed_conversation()

    response = client.delete(f"/api/conversations/{conversation_id}")

    assert response.status_code == 204
    assert response.content == b""
    with SessionLocal() as db:
        assert db.get(Conversation, conversation_id) is None
        assert db.query(Message).filter(Message.conversation_id == conversation_id).count() == 0
        assert db.query(Document).filter(Document.conversation_id == conversation_id).count() == 0
        assert db.query(Conversation).filter(Conversation.user_id == user_id).count() == 0


def test_delete_unknown_conversation_is_404(client: TestClient) -> None:
    assert client.delete("/api/conversations/does-not-exist").status_code == 404


def test_delete_is_idempotent_after_removal(client: TestClient) -> None:
    _user_id, conversation_id = _seed_conversation()

    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 204
    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 404