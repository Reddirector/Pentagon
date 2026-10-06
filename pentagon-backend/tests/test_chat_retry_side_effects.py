"""A retried turn must not repeat the side effects of the failed attempt.

The 429 retry re-invokes the whole graph from the same input. When the failed
attempt already executed commands -- a shell run, a desktop action, a location
lookup -- a naive replay runs them a second time, silently at Trusted. The gate
added to ``_stream_chat`` reads ``final_state["command_runs"]``, the graph's own
audit trail of machine side effects: an attempt that executed anything is never
retried, and the turn ends with an error that says why.

The tests below drive the real graph (real shell runner, real registry) through
the HTTP route, with only the model faked -- so the command executions being
counted are the same executions a real turn would perform.
"""

from __future__ import annotations

import json

import pytest

from typing import Any
from uuid import uuid4

from sqlalchemy import select

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from app.config import settings
from app.db.models import ApiKey, Message, User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.security.crypto import encrypt_api_key
from app.services import chat_graph, command_runner


@pytest.fixture(autouse=True)
def isolated_registry():
    """A private pending-request registry for every test."""
    command_runner.REGISTRY = command_runner.CommandRegistry()
    yield
    command_runner.REGISTRY = command_runner.CommandRegistry()


class _RateLimitedAfterToolModel:
    """Asks for the command, then 429s -- on every attempt.

    Each attempt makes two model calls: the first asks to run the marker
    command (the graph really executes it), the second -- the follow-up that
    would turn the tool result into an answer -- raises with a ``status_code``
    of 429, exactly the attribute ``_status_code`` reads. A retry therefore
    asks for the command again, which is precisely the replay the gate must
    refuse: without it the shell sees the command once per attempt.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages, config=None):
        self.calls += 1
        if self.calls % 2 == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "run_shell_command",
                        "args": {"command": "echo retried-command-marker"},
                        "id": f"call_{self.calls}",
                    }
                ],
            )
        error = RuntimeError("429")
        error.status_code = 429
        raise error


class _RateLimitedImmediatelyModel:
    """429s on the very first model call, before anything could execute."""

    def __init__(self) -> None:
        self.calls = 0
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages, config=None):
        self.calls += 1
        error = RuntimeError("429")
        error.status_code = 429
        raise error


def _setup(monkeypatch) -> tuple[str, str]:
    monkeypatch.setattr(
        settings, "key_encryption_secret", SecretStr(Fernet.generate_key().decode())
    )
    # Keep the retry honest: real back-off sleeps, but the first one is 1s and
    # the gate must prevent it from ever being reached in the exactly-once test.
    monkeypatch.setattr(settings, "command_tool_enabled", True)
    initialize_database()
    user_id = f"retry-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=user_id, command_tool_enabled=True))
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
            "/api/conversations", json={"user_id": user_id, "title": "Retry"}
        ).json()["id"]
    return user_id, conversation_id


def _chat(client: TestClient, user_id: str, conversation_id: str):
    return client.post(
        "/api/chat",
        json={
            "user_id": user_id,
            "conversation_id": conversation_id,
            "model": "test/model",
            "message": "run the marker command",
        },
    )


def _events(response_text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in response_text.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        name = block.split("\n", 1)[0].removeprefix("event: ").strip()
        data_line = next(
            (line for line in block.split("\n") if line.startswith("data: ")), ""
        )
        payload = json.loads(data_line[len("data: ") :]) if data_line else {}
        events.append((name, payload))
    return events


def test_retry_does_not_reexecute_commands_already_run(
    monkeypatch, isolated_registry
):
    """A command executed before the 429 must run exactly once for the turn.

    Every attempt asks for ``echo`` through the real shell runner, then the
    follow-up model call raises 429. The streamed tool result is silenced (see
    below) so nothing else stands between the 429 and a retry: without the
    gate, each attempt re-invokes the graph and the command runs again. The
    gate must end the turn with an error instead -- and the shell must have
    seen the command exactly once.
    """
    executions: list[str] = []
    real_execute = command_runner._execute

    async def counting_execute(command: str, *, auto_approved: bool):
        executions.append(command)
        return await real_execute(command, auto_approved=auto_approved)

    monkeypatch.setattr(command_runner, "_execute", counting_execute)
    # The old retry carried an accidental safety net: the tool result streams
    # as a token (langgraph's messages mode), so any executed command already
    # set ``emitted_token``, which suppressed the retry too. The gate must not
    # lean on that accident -- tool output is not meant to be chat text, and a
    # future streaming change would silently reopen the bug. Silencing the
    # streamed result leaves the gate as the only thing between the 429 and a
    # replay, which is exactly the situation it exists for.
    monkeypatch.setattr(command_runner.CommandResult, "as_text", lambda self: "")

    model = _RateLimitedAfterToolModel()
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *a, **k: model)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _c: False)

    def _build(api_key, model_name, **kwargs):
        return chat_graph.build_chat_graph(api_key, model_name, **kwargs)

    monkeypatch.setattr("app.routes.chat.build_chat_graph", _build)

    user_id, conversation_id = _setup(monkeypatch)

    with TestClient(app) as client:
        response = _chat(client, user_id, conversation_id)

    text = response.text
    events = _events(text)

    assert executions == ["echo retried-command-marker"], (
        f"the command executed {len(executions)} times, not exactly once: {executions!r}"
    )
    assert model.calls == 2, (
        f"expected the follow-up model call to be attempted exactly once more, "
        f"saw {model.calls}"
    )
    errors = [payload for name, payload in events if name == "error"]
    assert errors, "the turn ended without an error event"
    assert "will not run twice" in errors[-1]["message"]
    # ToolMessage stdout streams as a token (langgraph messages mode), so the
    # stream legitimately contains the command output. What must never happen
    # is a second beginning of an answer after the turn was given up on: once
    # the error is out, the stream is over.
    error_index = next(
        i for i, (name, _payload) in enumerate(events) if name == "error"
    )
    late_tokens = [
        payload for name, payload in events[error_index + 1 :] if name == "token"
    ]
    assert not late_tokens, (
        f"the failed turn streamed a new answer after the error: {late_tokens!r}"
    )
    # And the turn must have ended quickly: the 1s+ back-off of a real retry
    # chain would only run if the gate had failed.
    assert ": ping" not in text


def test_retry_without_executed_commands_still_happens(monkeypatch, isolated_registry):
    """Nothing executed yet means today's behaviour: the retry is allowed.

    The model 429s on its very first call, so the graph cannot have executed
    anything. The retry must proceed -- the second attempt answers normally and
    the turn completes with a real reply and a done event.
    """
    attempts: list[int] = []

    class _RecoveringModel:
        def __init__(self) -> None:
            self.calls = 0
            self.bound_tools = None

        def bind_tools(self, tools):
            self.bound_tools = tools
            return self

        async def ainvoke(self, messages, config=None):
            self.calls += 1
            attempts.append(self.calls)
            if self.calls == 1:
                error = RuntimeError("429")
                error.status_code = 429
                raise error
            return AIMessage(content="recovered on the retry")

    recovering_model = _RecoveringModel()
    monkeypatch.setattr(
        chat_graph, "make_chat_model", lambda *a, **k: recovering_model
    )
    monkeypatch.setattr(chat_graph, "has_documents", lambda _c: False)
    monkeypatch.setattr(
        "app.routes.chat.build_chat_graph",
        lambda *a, **k: chat_graph.build_chat_graph(*a, **k),
    )

    user_id, conversation_id = _setup(monkeypatch)

    with TestClient(app) as client:
        response = _chat(client, user_id, conversation_id)

    events = _events(response.text)
    names = [name for name, _payload in events]

    assert attempts == [1, 2], (
        f"expected exactly two model calls (429, then the retry), saw {attempts}"
    )
    assert "token" in names, "the retried attempt never produced an answer"
    assert "done" in names, "the retried turn never completed"
    assert not any(name == "error" for name in names), (
        "a clean retry must not surface an error event"
    )

    with SessionLocal() as db:
        replies = [
            message.content
            for message in db.scalars(
                select(Message).where(Message.conversation_id == conversation_id)
            )
        ]
    # The assistant reply really persisted, exactly as a normal turn's does.
    assert "recovered on the retry" in " ".join(replies)


def test_a_clean_turn_is_untouched_by_the_gate(monkeypatch, isolated_registry):
    """A turn with no 429 at all behaves exactly as before the gate existed."""

    class _PlainModel:
        def __init__(self) -> None:
            self.calls = 0
            self.bound_tools = None

        def bind_tools(self, tools):
            self.bound_tools = tools
            return self

        async def ainvoke(self, messages, config=None):
            self.calls += 1
            return AIMessage(content="plain answer")

    plain_model = _PlainModel()
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *a, **k: plain_model)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _c: False)
    monkeypatch.setattr(
        "app.routes.chat.build_chat_graph", lambda *a, **k: chat_graph.build_chat_graph(*a, **k)
    )

    user_id, conversation_id = _setup(monkeypatch)

    with TestClient(app) as client:
        response = _chat(client, user_id, conversation_id)

    # If the turn failed before the stream, say so loudly instead of failing
    # opaquely on the model-call count below.
    assert response.status_code == 200, response.text
    if plain_model.calls == 0:
        pytest.fail(
            "the model was never called; stream was: " + response.text[:500]
        )

    events = _events(response.text)
    names = [name for name, _payload in events]

    assert plain_model.calls == 1
    assert names[-1] == "done"
    assert not any(name == "error" for name in names)
