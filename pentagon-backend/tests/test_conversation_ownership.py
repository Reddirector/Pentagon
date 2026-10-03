"""Conversation endpoints must be scoped to the owning user.

The API has no session auth -- ``user_id`` travels in the request -- so the
only boundary available is that every lookup filters on the owner. These tests
pin that down for the four routes that address a conversation by id, because a
missing owner filter there lets any caller read, rename, delete or re-model
somebody else's thread by guessing or leaking its UUID.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.models import Conversation, Message, User
from app.db.session import SessionLocal, initialize_database
from app.main import app


@pytest.fixture
def client() -> TestClient:
    initialize_database()
    return TestClient(app)


def _seed_pair() -> tuple[str, str, str]:
    """Return (owner_id, intruder_id, conversation_id)."""
    owner_id = f"owner-{uuid4()}"
    intruder_id = f"intruder-{uuid4()}"
    conversation_id = str(uuid4())
    with SessionLocal() as db:
        db.add(User(id=owner_id))
        db.add(User(id=intruder_id))
        conversation = Conversation(
            id=conversation_id,
            user_id=owner_id,
            title="Owner private thread",
            active_model="nvidia/nemotron-3-nano-30b-a3b",
        )
        db.add(conversation)
        db.flush()
        db.add(
            Message(
                id=str(uuid4()),
                conversation_id=conversation_id,
                role="user",
                content="Secret question",
                model_used="nvidia/nemotron-3-nano-30b-a3b",
            )
        )
        db.commit()
    return owner_id, intruder_id, conversation_id


def test_read_requires_the_owning_user(client: TestClient) -> None:
    owner_id, intruder_id, conversation_id = _seed_pair()

    allowed = client.get(f"/api/conversations/{conversation_id}?user_id={owner_id}")
    assert allowed.status_code == 200
    assert allowed.json()["title"] == "Owner private thread"

    denied = client.get(f"/api/conversations/{conversation_id}?user_id={intruder_id}")
    assert denied.status_code == 404


def test_missing_user_id_is_rejected(client: TestClient) -> None:
    _owner_id, _intruder_id, conversation_id = _seed_pair()
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 422


def test_rename_requires_the_owning_user(client: TestClient) -> None:
    owner_id, intruder_id, conversation_id = _seed_pair()
    url = f"/api/conversations/{conversation_id}/title"

    denied = client.patch(
        f"{url}?user_id={intruder_id}",
        json={"title": "Hijacked"},
    )
    assert denied.status_code == 404

    # The title must be untouched, not merely rejected.
    with SessionLocal() as db:
        assert db.get(Conversation, conversation_id).title == "Owner private thread"

    allowed = client.patch(f"{url}?user_id={owner_id}", json={"title": "Renamed"})
    assert allowed.status_code == 200
    assert allowed.json()["title"] == "Renamed"


def test_delete_requires_the_owning_user(client: TestClient) -> None:
    owner_id, intruder_id, conversation_id = _seed_pair()

    denied = client.delete(f"/api/conversations/{conversation_id}?user_id={intruder_id}")
    assert denied.status_code == 404

    # The thread and its messages must still exist.
    with SessionLocal() as db:
        assert db.get(Conversation, conversation_id) is not None

    allowed = client.delete(f"/api/conversations/{conversation_id}?user_id={owner_id}")
    assert allowed.status_code == 204
    with SessionLocal() as db:
        assert db.get(Conversation, conversation_id) is None


def test_switch_model_requires_the_owning_user(client: TestClient) -> None:
    owner_id, intruder_id, conversation_id = _seed_pair()

    denied = client.patch(
        f"/api/conversations/{conversation_id}?user_id={intruder_id}",
        json={"model": "nvidia/nemotron-3-nano-30b-a3b"},
    )
    # The request is refused before any model work happens, so it cannot be a
    # validation error about the model itself.
    assert denied.status_code == 404

    with SessionLocal() as db:
        assert db.get(Conversation, conversation_id).active_model == (
            "nvidia/nemotron-3-nano-30b-a3b"
        )