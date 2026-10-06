"""Regressions from two user-visible bugs.

* **Citations vanished on reload.** ``sources_used`` was emitted on the live
  stream only and never written down, so a reloaded conversation kept the
  answer and lost every source that justified it.
* **The column is JSON text but the API field disagreed with it.** ``sources_used``
  holds the same object the live stream emits, keyed by kind. Typing the field
  as a list made the decoder throw every real citation away and reload the
  conversation with nulls, which is the same vanishing bug wearing a new hat.
  The decoder still has to survive nulls, blanks and rubbish without 500-ing a
  conversation.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.db.models import Message, User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.schemas import MessageResponse


@pytest.fixture
def client() -> TestClient:
    initialize_database()
    return TestClient(app)


def test_sources_column_is_added_to_existing_databases(tmp_path):
    """A database created before this fix must gain the column, not fail."""
    import sqlite3

    from app.db.session import initialize_database as initialise

    db_file = tmp_path / "legacy.db"
    connection = sqlite3.connect(db_file)
    connection.execute(
        "CREATE TABLE messages (id VARCHAR(36) PRIMARY KEY, conversation_id VARCHAR(36),"
        " role VARCHAR(16), content TEXT, model_used VARCHAR(255),"
        " created_at DATETIME)"
    )
    connection.commit()
    connection.close()

    url = f"sqlite:///{db_file}"
    from app.config import settings

    original = settings.database_url
    original_engine = None
    try:
        import app.db.session as session_module

        original_engine = session_module.engine
        settings.database_url = url
        from sqlalchemy import create_engine, inspect

        session_module.engine = create_engine(url)
        initialise()
        columns = {c["name"] for c in inspect(session_module.engine).get_columns("messages")}
        assert "sources_used" in columns
    finally:
        from app.config import settings as s

        s.database_url = original
        if original_engine is not None:
            import app.db.session as session_module

            session_module.engine = original_engine


@pytest.mark.parametrize(
    "stored,expected",
    [
        (
            '{"web": [{"title": "KDE", "url": "https://kde.org"}], "documents": []}',
            {"web": [{"title": "KDE", "url": "https://kde.org"}], "documents": []},
        ),
        (None, None),
        ("", None),
        ("not json at all", None),
        ('["a bare list is not the shape"]', None),
        (17, None),
    ],
)
def test_stored_sources_decode_without_breaking_the_response(stored, expected):
    from datetime import datetime, timezone

    message = MessageResponse(
        id="m1",
        role="assistant",
        content="hello",
        model_used="test",
        created_at=datetime.now(timezone.utc),
        sources_used=stored,
    )
    assert message.sources_used == expected


def test_a_reloaded_conversation_still_has_its_citations(client):
    """The bug itself: write a message with sources, read it back."""
    """The bug itself: write a message with sources, read it back."""
    initialize_database()
    user_id = "sources-user"
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.commit()
    conversation_id = client.post(
        "/api/conversations", json={"user_id": user_id, "title": "Cited"}
    ).json()["id"]
    payload = json.dumps({"web": [{"title": "KDE", "url": "https://kde.org"}], "documents": []})
    with SessionLocal() as db:
        db.add(
            Message(
                conversation_id=conversation_id,
                role="assistant",
                content="Plasma is the desktop.",
                model_used="test-model",
                sources_used=payload,
            )
        )
        db.commit()

    messages = client.get(
        "/api/conversations/" + conversation_id, params={"user_id": user_id}
    ).json()["messages"]

    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert assistant["sources_used"] == {
        "web": [{"title": "KDE", "url": "https://kde.org"}],
        "documents": [],
    }


def test_a_null_column_reaches_the_client_as_null_not_an_empty_list(client):
    """The decoder's NULL case.

    Named for what it actually covers: a row whose column is NULL must arrive as
    null, never as []. Whether a *real* turn with no search writes NULL is a
    different question, answered by the parametrized real-turn test below --
    this one hand-writes the row and so can never see the write path.
    """
    initialize_database()
    user_id = "no-sources-user"
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.commit()
    conversation_id = client.post(
        "/api/conversations", json={"user_id": user_id, "title": "Plain"}
    ).json()["id"]
    with SessionLocal() as db:
        db.add(
            Message(
                conversation_id=conversation_id,
                role="assistant",
                content="No search was used.",
                model_used="test-model",
            )
        )
        db.commit()

    messages = client.get(
        "/api/conversations/" + conversation_id, params={"user_id": user_id}
    ).json()["messages"]
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert assistant["sources_used"] is None


def test_the_response_model_still_hides_the_server_path(client):
    """image_path must not come back just because sources now does."""
    initialize_database()
    user_id = "path-user"
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.commit()
    conversation_id = client.post(
        "/api/conversations", json={"user_id": user_id, "title": "T"}
    ).json()["id"]
    with SessionLocal() as db:
        db.add(
            Message(
                conversation_id=conversation_id,
                role="user",
                content="look",
                model_used="m",
                image_path="/home/someone/secret/image_uploads/x.png",
            )
        )
        db.commit()
    messages = client.get(
        "/api/conversations/" + conversation_id, params={"user_id": user_id}
    ).json()["messages"]
    assert "image_path" not in messages[0]


@pytest.mark.parametrize(
    "use_web_search,expect_citations",
    [(True, True), (False, False)],
    ids=["with_search", "without_search"],
)
def test_a_real_turn_persists_its_citations(
    monkeypatch, use_web_search: bool, expect_citations: bool
):
    """The write path, not just the column.

    Writing a Message with sources by hand proves the column round-trips. It
    proves nothing about whether a real answer saves its own evidence, which is
    the half that was broken. This drives /api/chat with a faked model.

    Both directions matter. A turn that searched must keep its citations, and a
    turn that did not must store NULL rather than an empty ``{"web": [],
    "documents": []}`` shell -- a hand-written row could never catch that,
    because by hand the column is simply left unset.
    """
    from uuid import uuid4

    from cryptography.fernet import Fernet
    from langchain_core.messages import AIMessage
    from pydantic import SecretStr

    from app.config import settings
    from app.db.models import ApiKey
    from app.security.crypto import encrypt_api_key
    from app.services import chat_graph

    initialize_database()
    user_id = f"citations-turn-{uuid4()}"
    conversation_id = str(uuid4())
    monkeypatch.setattr(
        settings, "key_encryption_secret", SecretStr(Fernet.generate_key().decode())
    )

    class FakeModel:
        async def ainvoke(self, messages, config=None):
            return AIMessage(content="Here is what I found.")

    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *a, **k: FakeModel())
    monkeypatch.setattr(chat_graph, "has_documents", lambda _c: False)

    async def fake_search(*_args, **_kwargs):
        return [
            {
                "title": "KDE Plasma",
                "url": "https://kde.org/plasma",
                "snippet": "A desktop shell.",
            }
        ]

    monkeypatch.setattr(chat_graph, "search_web", fake_search)

    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.add(
            ApiKey(
                user_id=user_id,
                encrypted_key=encrypt_api_key("nvapi-test-key"),
                masked_key="nvapi-...key",
            )
        )
        db.commit()

    conversation = client_for_chat().post(
        "/api/conversations", json={"user_id": user_id, "title": "Cited turn"}
    ).json()
    assert conversation["id"]

    with TestClient(app) as client:
        client.post(
            "/api/chat",
            json={
                "user_id": user_id,
                "conversation_id": conversation["id"],
                "model": "nvidia/nemotron-3-super-120b-a12b",
                "message": "What is Plasma?",
                "use_web_search": use_web_search,
            },
        )
        stored = client.get(
            f"/api/conversations/{conversation['id']}", params={"user_id": user_id}
        ).json()["messages"]

    assistant = [m for m in stored if m["role"] == "assistant"]
    assert assistant, "the turn produced no assistant message"
    sources = assistant[0]["sources_used"]
    if not expect_citations:
        assert sources is None, (
            "a turn that used no search stored an empty sources shell: "
            f"{sources!r}"
        )
        return
    assert sources, "the answer was saved with no citations, which is the original bug"
    # The reloaded shape must match what the live stream sent, because that is
    # what ``SourcesButton`` reads: an object keyed by kind, not a flat list.
    assert "kde.org" in json.dumps(sources)
    assert any("kde.org" in (row.get("url") or "") for row in sources["web"])


def client_for_chat() -> TestClient:
    initialize_database()
    return TestClient(app)