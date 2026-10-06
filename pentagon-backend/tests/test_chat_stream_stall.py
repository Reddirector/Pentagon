"""The stream must end when the provider goes silent.

Observed live: POST /api/chat returned 200, emitted only the ``conversation``
event, and then nothing -- no error event, no persisted reply -- until the
client gave up. Nothing raises when an upstream stalls, so a bare ``async for``
over ``graph.astream`` waits forever. These tests drive a graph that does
exactly that and prove the turn ends with a visible error instead of hanging.

The graphs here are fakes handed to the route by replacing
``app.routes.chat.build_chat_graph``, so the stream's own machinery -- the
silence clock, the keep-alive comments, the persistence on timeout -- is what
is under test, not the langgraph loop.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import settings
from app.db.models import ApiKey, Message, User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.routes import chat
from app.security.crypto import encrypt_api_key
from app.services import command_runner
from app.services.command_runner import PendingRequest


def _stalling_graph(tokens: tuple[str, ...] = ()) -> Any:
    """A graph that streams the given tokens and then never speaks again."""

    class StallingGraph:
        async def astream(self, _input: Any, **_kwargs: Any):
            from langchain_core.messages import AIMessage

            for token in tokens:
                yield {"type": "messages", "data": (AIMessage(content=token), {})}
            # The stall itself: no chunk, no exception, no end. A bare
            # ``async for`` would wait out the full hour.
            await asyncio.sleep(3600)

    return StallingGraph()


def _provision(monkeypatch) -> tuple[str, str]:
    """A user with a stored key and one conversation, ready to chat."""
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    monkeypatch.setattr(
        settings, "key_encryption_secret", SecretStr(Fernet.generate_key().decode())
    )
    initialize_database()
    user_id = f"stall-{uuid4()}"
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
    with TestClient(app) as client:
        conversation_id = client.post(
            "/api/conversations", json={"user_id": user_id, "title": "Stall"}
        ).json()["id"]
    return user_id, conversation_id


def _patch_clocks(monkeypatch, *, stall: float = 1.0, slack: float = 0.3) -> None:
    """Shrink every silence window so the tests run in seconds, not minutes."""
    monkeypatch.setattr(settings, "nvidia_timeout_seconds", stall)
    monkeypatch.setattr(chat, "_STALL_POLL_SECONDS", 0.1)
    monkeypatch.setattr(chat, "_STALL_SLACK_SECONDS", slack)


def test_stalled_upstream_ends_with_an_error_event(monkeypatch):
    """A silent provider must produce an error event, not an eternal silence.

    The stall budget is one second; if the clock did not exist this request
    would never return and the test would hang -- which is the bug, observed.
    The keep-alive comments must also be on the wire: they are how a client
    tells a quiet stream from a dead one.
    """
    _patch_clocks(monkeypatch)
    user_id, conversation_id = _provision(monkeypatch)
    monkeypatch.setattr(chat, "build_chat_graph", lambda *a, **k: _stalling_graph())

    started = time.perf_counter()
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "user_id": user_id,
                "conversation_id": conversation_id,
                "model": "test/model",
                "message": "hello",
            },
        )
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert "event: conversation" in response.text
    assert "event: error" in response.text, response.text
    assert "stopped responding" in response.text
    assert ": ping" in response.text, (
        "the silence carried no keep-alive comments, so a client cannot "
        "distinguish waiting from gone"
    )
    assert elapsed < 1.8, (
        f"the deadline did not hold: the stream ran {elapsed:.1f}s "
        f"against a 1.0s stall budget"
    )


def test_stall_after_tokens_persists_the_partial_answer(monkeypatch):
    """Whatever streamed before the silence must survive a reload.

    The user's message was committed before the stream opened, so a stall that
    persists nothing leaves the thread as a question with no reply. The partial
    answer is the one thing the turn did produce; it is saved.
    """
    _patch_clocks(monkeypatch)
    user_id, conversation_id = _provision(monkeypatch)
    monkeypatch.setattr(
        chat, "build_chat_graph", lambda *a, **k: _stalling_graph(("Par", "tial"))
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "user_id": user_id,
                "conversation_id": conversation_id,
                "model": "test/model",
                "message": "hello",
            },
        )
        stored = client.get(
            f"/api/conversations/{conversation_id}", params={"user_id": user_id}
        ).json()["messages"]

    assert "event: token" in response.text
    assert "event: error" in response.text
    assistant = [m for m in stored if m["role"] == "assistant"]
    assert len(assistant) == 1, "the stalled turn left no reply behind"
    assert assistant[0]["content"] == "Partial"
    with SessionLocal() as db:
        rows = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation_id,
                Message.role == "assistant",
            )
            .all()
        )
    assert len(rows) == 1
    assert rows[0].content == "Partial"


def test_stall_before_any_token_persists_no_empty_reply(monkeypatch):
    """An empty stall persists nothing.

    An empty assistant bubble would read as a broken reply rather than as a
    turn that timed out, so an answer that never started is not written.
    """
    _patch_clocks(monkeypatch)
    user_id, conversation_id = _provision(monkeypatch)
    monkeypatch.setattr(chat, "build_chat_graph", lambda *a, **k: _stalling_graph())

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "user_id": user_id,
                "conversation_id": conversation_id,
                "model": "test/model",
                "message": "hello",
            },
        )
        stored = client.get(
            f"/api/conversations/{conversation_id}", params={"user_id": user_id}
        ).json()["messages"]

    assert "event: error" in response.text
    assert not [m for m in stored if m["role"] == "assistant"], (
        "a turn that never produced a token must not leave an empty reply"
    )


def test_pending_approval_extends_the_deadline(monkeypatch):
    """An unanswered question keeps the stream open; it is not a dead provider.

    While an approval card is on screen the graph produces nothing, which is
    indistinguishable from a stall unless the clock knows to wait. The request
    here sits in the registry for half a second (its own approval window
    resolving it, as ``REGISTRY.wait`` would), and the stream must outlive the
    one-second stall budget because of it.
    """
    _patch_clocks(monkeypatch)
    # approval_budget = 1.0 (approval) + 0.0 (command) + 1.0 (LLM) + 0.3 (slack)
    monkeypatch.setattr(settings, "command_approval_timeout_seconds", 1.0)
    monkeypatch.setattr(settings, "command_timeout_seconds", 0.0)
    user_id, conversation_id = _provision(monkeypatch)
    monkeypatch.setattr(chat, "build_chat_graph", lambda *a, **k: _stalling_graph())

    request = PendingRequest(
        request_id=uuid4().hex,
        conversation_id=conversation_id,
        user_id=user_id,
        command="echo hi",
        reason="test",
        created_at=time.time(),
    )
    command_runner.REGISTRY.submit(request)
    # The user answers halfway through the approval window, exactly as the
    # real approval flow would resolve the request.
    resolved = threading.Event()

    def _answer():
        command_runner.REGISTRY.resolve(request.request_id, user_id, True)
        resolved.set()

    timer = threading.Timer(0.5, _answer)
    timer.start()
    try:
        started = time.perf_counter()
        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "model": "test/model",
                    "message": "hello",
                },
            )
        elapsed = time.perf_counter() - started
    finally:
        timer.join()
        command_runner.REGISTRY.discard(request.request_id)

    assert resolved.is_set()
    assert "event: error" in response.text
    assert elapsed > 2.0, (
        f"the pending question did not extend the deadline: the stream ended "
        f"after {elapsed:.1f}s, within the 1.0s stall budget it should have "
        f"outlived"
    )
