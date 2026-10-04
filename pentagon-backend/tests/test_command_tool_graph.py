"""The shell tool inside the chat graph, and the endpoints that govern it.

Three things are worth proving here, and none of them is "a command ran":

* With the tool off, the model is handed no tool at all and the graph behaves
  exactly as it did before this feature existed.
* With the tool on, a tool call becomes a command, the command's output comes
  back to the model as a ToolMessage, and the model gets a second turn.
* The HTTP surface cannot be used to switch the tool on when the server has it
  switched off, or to approve somebody else's request.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from app.config import settings
from app.db.models import ApiKey, User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.security.crypto import encrypt_api_key
from app.services import chat_graph, command_runner


@pytest.fixture
def client() -> TestClient:
    initialize_database()
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_registry():
    """Every test gets a private pending-request registry."""
    command_runner.REGISTRY = command_runner.CommandRegistry()
    yield
    command_runner.REGISTRY = command_runner.CommandRegistry()


@pytest.fixture
def server_allows_commands(monkeypatch):
    monkeypatch.setattr(settings, "command_tool_enabled", True)
    monkeypatch.setattr(settings, "command_approval_timeout_seconds", 0.2)
    monkeypatch.setattr(settings, "command_max_calls_per_turn", 4)


@pytest.fixture
def user_id() -> str:
    new_id = f"cmdtool-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=new_id, command_tool_enabled=True))
        db.add(
            ApiKey(
                user_id=new_id,
                encrypted_key=encrypt_api_key("nvapi-test-command-key"),
                masked_key="nvapi-...key",
            )
        )
        db.commit()
    return new_id


def _state(command_tool_enabled: bool = True):
    return chat_graph.initial_chat_state(
        user_id="test-user",
        conversation_id="test-conversation",
        message="What is in the README?",
        history=[],
        use_web_search=False,
        command_tool_enabled=command_tool_enabled,
    )


class _ScriptedModel:
    """Returns queued responses, recording what it was asked each time."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.seen: list[list] = []
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages, config=None):
        self.seen.append(list(messages))
        return self.responses.pop(0) if self.responses else AIMessage(content="done")


def _tool_call(command: str, call_id: str = "call_1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "run_shell_command", "args": {"command": command}, "id": call_id}],
    )


def _graph_with(model, *, enabled: bool, monkeypatch):
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_a, **_k: model)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: False)
    return chat_graph.build_chat_graph(
        "unused-key", "test-model", user_id="test-user", use_web_search=False,
        command_tool_enabled=enabled,
    )


def test_tool_is_never_offered_when_disabled(server_allows_commands, monkeypatch) -> None:
    """The server switch alone is enough to keep the model tool-less."""
    model = _ScriptedModel([AIMessage(content="no tools here")])
    graph = _graph_with(model, enabled=False, monkeypatch=monkeypatch)

    result = asyncio.run(graph.ainvoke(_state(command_tool_enabled=False)))

    assert model.bound_tools is None, "the tool was bound even though it was disabled"
    assert result["answer"] == "no tools here"
    assert result["command_runs"] == []


def test_tool_is_not_offered_when_the_server_switch_is_off(monkeypatch) -> None:
    """A client cannot enable the tool for itself by flipping its own flag."""
    monkeypatch.setattr(settings, "command_tool_enabled", False)
    model = _ScriptedModel([AIMessage(content="hello")])
    graph = _graph_with(model, enabled=True, monkeypatch=monkeypatch)

    asyncio.run(graph.ainvoke(_state(command_tool_enabled=True)))

    assert model.bound_tools is None


def test_a_read_only_command_runs_and_its_output_reaches_the_model(
    server_allows_commands, monkeypatch
) -> None:
    model = _ScriptedModel(
        [
            _tool_call("echo hello-from-the-shell"),
            AIMessage(content="The shell said hello-from-the-shell."),
        ]
    )
    graph = _graph_with(model, enabled=True, monkeypatch=monkeypatch)

    result = asyncio.run(graph.ainvoke(_state()))

    assert [run["command"] for run in result["command_runs"]] == ["echo hello-from-the-shell"]
    assert result["command_runs"][0]["exit_code"] == 0
    assert result["command_runs"][0]["auto_approved"] is True
    assert result["answer"] == "The shell said hello-from-the-shell."
    # The second turn must have seen the tool output.
    assert len(model.seen) == 2
    tool_messages = [m for m in model.seen[1] if m.type == "tool"]
    assert tool_messages, "the tool result never reached the model"
    assert "hello-from-the-shell" in tool_messages[0].content


def test_a_write_command_that_is_denied_is_reported_to_the_model(
    server_allows_commands, monkeypatch, tmp_path
) -> None:
    """Denial is information, not silence: the model must learn it was refused."""
    target = tmp_path / "must-not-appear.txt"
    model = _ScriptedModel(
        [
            _tool_call(f"echo nope > {target}"),
            AIMessage(content="Understood, I will not do that."),
        ]
    )
    graph = _graph_with(model, enabled=True, monkeypatch=monkeypatch)

    result = asyncio.run(graph.ainvoke(_state()))

    assert not target.exists(), "a denied command was executed"
    tool_messages = [m for m in model.seen[1] if m.type == "tool"]
    assert "did not approve" in tool_messages[0].content
    assert result["answer"] == "Understood, I will not do that."


def test_an_unsupported_tool_name_is_never_executed(
    server_allows_commands, monkeypatch, tmp_path
) -> None:
    """The model can only ask for the one tool this graph offers."""
    target = tmp_path / "should-not-exist.txt"
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "delete_everything", "args": {"path": str(target)}, "id": "call_x"},
        ],
    )
    model = _ScriptedModel([response, AIMessage(content="I cannot do that.")])
    graph = _graph_with(model, enabled=True, monkeypatch=monkeypatch)

    result = asyncio.run(graph.ainvoke(_state()))

    assert result["command_runs"] == []
    assert not target.exists()


def test_a_tool_call_without_a_command_is_rejected(
    server_allows_commands, monkeypatch
) -> None:
    response = AIMessage(
        content="", tool_calls=[{"name": "run_shell_command", "args": {}, "id": "call_empty"}]
    )
    model = _ScriptedModel([response, AIMessage(content="Sorry, I had no command.")])
    graph = _graph_with(model, enabled=True, monkeypatch=monkeypatch)

    asyncio.run(graph.ainvoke(_state()))

    tool_messages = [m for m in model.seen[1] if m.type == "tool"]
    assert "rejected" in tool_messages[0].content


def test_the_loop_stops_at_the_per_turn_limit(
    server_allows_commands, monkeypatch
) -> None:
    """A model that keeps asking must not loop forever."""
    monkeypatch.setattr(settings, "command_max_calls_per_turn", 2)
    # Every turn asks for another read-only command, so only the limit can end it.
    model = _ScriptedModel(
        [
            _tool_call("echo one", "c1"),
            _tool_call("echo two", "c2"),
            _tool_call("echo three", "c3"),
            _tool_call("echo four", "c4"),
            AIMessage(content="stopping now"),
        ]
    )
    graph = _graph_with(model, enabled=True, monkeypatch=monkeypatch)

    result = asyncio.run(graph.ainvoke(_state()))

    assert len(result["command_runs"]) <= 2, "the loop ran past the per-turn limit"


def test_command_runs_are_recorded_in_the_trace(
    server_allows_commands, monkeypatch
) -> None:
    model = _ScriptedModel([_tool_call("echo traced"), AIMessage(content="done")])
    graph = _graph_with(model, enabled=True, monkeypatch=monkeypatch)

    result = asyncio.run(graph.ainvoke(_state()))

    trace = result["execution_trace"]["run_command"]
    assert trace["command_count"] == 1
    assert trace["commands"] == ["echo traced"]


# --- HTTP surface ---------------------------------------------------------


def test_every_response_model_renders_a_valid_openapi_schema() -> None:
    """A malformed field breaks /openapi.json, not the endpoint itself.

    `Field(default=300.0, description=0)` shipped once: the description was the
    integer 0 rather than a string, which every route test passed straight
    through and only surfaced as a 500 on the docs page. Asserting on the
    endpoint's own response cannot see that, so assert on the schema.
    """
    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    command_settings = schema["components"]["schemas"]["CommandSettings"]
    assert "enabled" in command_settings["properties"]
    assert "available" in command_settings["properties"]
    assert isinstance(
        command_settings["properties"]["approval_timeout_seconds"], dict
    )


def test_settings_report_availability_and_default_to_off(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "command_tool_enabled", False)
    new_id = f"cmdtool-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=new_id))
        db.commit()

    response = client.get("/api/commands/settings", params={"user_id": new_id})

    assert response.status_code == 200
    body = response.json()
    assert body == {"enabled": False, "available": False, "approval_timeout_seconds": settings.command_approval_timeout_seconds}


def test_settings_can_be_enabled_when_the_server_allows_it(
    client: TestClient, server_allows_commands
) -> None:
    new_id = f"cmdtool-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=new_id))
        db.commit()

    response = client.put(
        "/api/commands/settings", params={"user_id": new_id}, json={"enabled": True}
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    with SessionLocal() as db:
        assert db.get(User, new_id).command_tool_enabled is True


def test_settings_refuse_to_enable_when_the_server_forbids_it(client: TestClient) -> None:
    monkeypatch_free = settings.command_tool_enabled
    try:
        settings.command_tool_enabled = False
        new_id = f"cmdtool-{uuid4()}"
        with SessionLocal() as db:
            db.add(User(id=new_id))
            db.commit()

        response = client.put(
            "/api/commands/settings", params={"user_id": new_id}, json={"enabled": True}
        )

        assert response.status_code == 403
        with SessionLocal() as db:
            assert db.get(User, new_id).command_tool_enabled is False
    finally:
        settings.command_tool_enabled = monkeypatch_free


def test_a_decision_cannot_cross_users(client: TestClient) -> None:
    request = command_runner.PendingRequest(
        request_id="req-cross-user",
        conversation_id="c1",
        user_id="owner",
        command="rm file",
        reason="because",
        created_at=0.0,
    )
    command_runner.REGISTRY.submit(request)

    wrong = client.post(
        "/api/commands/decide",
        json={"request_id": "req-cross-user", "approved": True, "user_id": "intruder"},
    )
    assert wrong.json() == {"resolved": False}
    assert not request.resolved

    right = client.post(
        "/api/commands/decide",
        json={"request_id": "req-cross-user", "approved": True, "user_id": "owner"},
    )
    assert right.json() == {"resolved": True}
    assert request.decision is True


def test_pending_is_reachable_while_the_turn_is_still_open(client: TestClient) -> None:
    """The approval question must be answerable before the turn finishes.

    This is the defect that shipped first: the stream blocks inside the tool
    node waiting for a decision, so a `command_request` event pushed down that
    same stream could never arrive -- the client would sit on a spinner until
    the request timed out and was denied. The pending endpoint is what makes the
    question visible, so it is the thing under test here.
    """
    request = command_runner.PendingRequest(
        request_id="req-open",
        conversation_id="c-open",
        user_id="u1",
        command="rm -rf /tmp/whatever",
        reason="cleaning up",
        created_at=0.0,
    )
    command_runner.REGISTRY.submit(request)

    response = client.get(
        "/api/commands/pending",
        params={"user_id": "u1", "conversation_id": "c-open"},
    )

    assert response.status_code == 200
    rows = response.json()
    assert rows == [
        {"request_id": "req-open", "command": "rm -rf /tmp/whatever", "reason": "cleaning up"}
    ]


def test_pending_only_shows_your_own_requests(client: TestClient) -> None:
    for name, owner in (("p1", "u1"), ("p2", "u2")):
        command_runner.REGISTRY.submit(
            command_runner.PendingRequest(
                request_id=name, conversation_id="c1", user_id=owner,
                command="ls", reason="", created_at=0.0,
            )
        )

    response = client.get(
        "/api/commands/pending",
        params={"user_id": "u1", "conversation_id": "c1"},
    )

    assert response.status_code == 200
    assert [row["request_id"] for row in response.json()] == ["p1"]


def test_migration_adds_the_column_to_an_existing_database(tmp_path, monkeypatch) -> None:
    """An existing database gains the column instead of failing to start.

    This is the upgrade path every current user takes: their `users` table
    already exists, so `create_all` will not add anything and only the explicit
    ALTER in initialize_database can.
    """
    import sqlite3

    from sqlalchemy import create_engine, inspect

    from app.db import session as session_module

    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE users (id VARCHAR(128) PRIMARY KEY, created_at DATETIME)"
    )
    connection.execute("INSERT INTO users (id, created_at) VALUES ('legacy', '2026-01-01')")
    connection.commit()
    connection.close()

    engine = create_engine(f"sqlite:///{database}")
    monkeypatch.setattr(session_module, "engine", engine)
    session_module.initialize_database()

    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert "command_tool_enabled" in columns, "the migration did not run"

    # And the pre-existing row defaults to off, which is the safe direction.
    with engine.connect() as connection:
        value = connection.exec_driver_sql(
            "SELECT command_tool_enabled FROM users WHERE id = 'legacy'"
        ).scalar()
    assert value in (0, False), f"an existing user was opted in by the migration: {value!r}"