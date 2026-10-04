"""Timestamps have to name the instant they mean, and paths must stay put.

Two things the API was getting wrong, both reproduced against the live server
before the fix.

Timestamps: SQLite has no datetime type, so a ``DateTime(timezone=True)``
column round-tripped through it came back *naive* -- the UTC offset silently
dropped. Pydantic then serialised that with no suffix at all
(``"2026-10-04T06:16:28.144951"``), and ``new Date()`` in a browser reads an
offset-less timestamp as **local** time. Every timestamp the client received
was therefore off by the client's UTC offset, and the sidebar filed a thread
started at 02:30 IST under "Yesterday".

Paths: ``MessageResponse`` mirrored the ORM object, so the ``image_path``
column -- an absolute server path such as
``/srv/app/image_uploads/<conversation id>/<message id>.png`` -- went out in
every conversation response. No client ever read it.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
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


# An ISO-8601 instant only means something if it says which instant.
_OFFSETLESS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$")


def _assert_timestamp_names_an_instant(value: object, label: str) -> None:
    assert isinstance(value, str), f"{label} was {type(value).__name__}, not a string"
    assert not _OFFSETLESS.match(value), (
        f"{label} = {value!r} carries no UTC offset, so every client reads it "
        f"as local time and places it hours away from the real instant"
    )
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None, f"{label} = {value!r} did not survive parsing as an instant"


def _seed(conversation_id: str | None = None, **conversation_kwargs) -> tuple[str, str]:
    user_id = f"timestamp-test-{uuid4()}"
    conversation_id = conversation_id or str(uuid4())
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.add(Conversation(id=conversation_id, user_id=user_id, title="Clock", **conversation_kwargs))
        db.flush()
        db.add(
            Message(
                id=str(uuid4()),
                conversation_id=conversation_id,
                role="user",
                content="What time is it?",
                model_used="nvidia/test",
            )
        )
        db.commit()
    return user_id, conversation_id


def test_orm_returns_timezone_aware_utc() -> None:
    """The decorator is the fix; assert it at the layer that was losing it."""
    initialize_database()
    user_id, conversation_id = _seed()
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation.updated_at.tzinfo is not None
        assert conversation.updated_at.utcoffset() == timedelta(0)
        message = conversation.messages[0]
        assert message.created_at.tzinfo is not None
        assert message.created_at.utcoffset() == timedelta(0)
    with SessionLocal() as db:
        db.delete(db.get(Conversation, conversation_id))
        db.delete(db.get(User, user_id))
        db.commit()


def test_naive_datetime_written_directly_comes_back_as_utc() -> None:
    """A naive value is stored as UTC, matching what ``utc_now`` writes.

    Rows written before the fix are already naive in the database, so this is
    also the path that repairs history: old rows load as UTC rather than as a
    local reading.
    """
    initialize_database()
    user_id, conversation_id = _seed()
    naive = datetime(2026, 10, 3, 20, 30, 0)
    with SessionLocal() as db:
        db.get(Conversation, conversation_id).updated_at = naive
        db.commit()
    with SessionLocal() as db:
        loaded = db.get(Conversation, conversation_id).updated_at
        assert loaded.tzinfo is not None
        assert loaded == naive.replace(tzinfo=UTC)
    with SessionLocal() as db:
        db.delete(db.get(Conversation, conversation_id))
        db.delete(db.get(User, user_id))
        db.commit()


def test_conversation_list_timestamps_carry_an_offset(client: TestClient) -> None:
    user_id, conversation_id = _seed()

    response = client.get("/api/conversations", params={"user_id": user_id})

    assert response.status_code == 200
    rows = response.json()
    assert [row["id"] for row in rows] == [conversation_id]
    _assert_timestamp_names_an_instant(rows[0]["updated_at"], "ConversationSummary.updated_at")


def test_conversation_detail_timestamps_carry_an_offset(client: TestClient) -> None:
    user_id, conversation_id = _seed()

    response = client.get(
        f"/api/conversations/{conversation_id}", params={"user_id": user_id}
    )

    assert response.status_code == 200
    payload = response.json()
    _assert_timestamp_names_an_instant(payload["updated_at"], "ConversationResponse.updated_at")
    assert payload["messages"], "the seeded thread should have one message"
    _assert_timestamp_names_an_instant(
        payload["messages"][0]["created_at"], "MessageResponse.created_at"
    )


def test_document_timestamps_carry_an_offset(client: TestClient) -> None:
    user_id, conversation_id = _seed()
    with SessionLocal() as db:
        db.add(
            Document(
                id=str(uuid4()),
                user_id=user_id,
                conversation_id=conversation_id,
                collection_name="timestamp-test",
                filename="notes.txt",
                chunk_count=1,
            )
        )
        db.commit()

    response = client.get(
        "/api/documents",
        params={"user_id": user_id, "conversation_id": conversation_id},
    )

    assert response.status_code == 200
    _assert_timestamp_names_an_instant(response.json()[0]["created_at"], "DocumentResponse.created_at")


def test_emitted_offset_matches_utc_to_the_microsecond(client: TestClient) -> None:
    """Guards against a fix that merely appends a wrong-looking 'Z'."""
    user_id, conversation_id = _seed()
    exact = datetime(2026, 10, 3, 20, 30, 0, 123456, tzinfo=UTC)
    with SessionLocal() as db:
        db.get(Conversation, conversation_id).updated_at = exact
        db.commit()

    response = client.get(
        f"/api/conversations/{conversation_id}", params={"user_id": user_id}
    )

    emitted = datetime.fromisoformat(response.json()["updated_at"].replace("Z", "+00:00"))
    assert emitted == exact


def test_conversation_response_does_not_leak_the_server_image_path(
    client: TestClient,
) -> None:
    user_id, conversation_id = _seed()
    secret_path = "/srv/pentagon/image_uploads/should-never-be-sent/secret.png"
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        conversation.messages[0].image_path = secret_path
        db.commit()

    response = client.get(
        f"/api/conversations/{conversation_id}", params={"user_id": user_id}
    )

    assert response.status_code == 200
    body = response.text
    assert secret_path not in body
    assert "image_path" not in body
    # The column itself must survive: the deletion sweep reads it.
    with SessionLocal() as db:
        assert db.get(Conversation, conversation_id).messages[0].image_path == secret_path