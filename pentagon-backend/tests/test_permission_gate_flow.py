"""The autonomy gate: who runs unattended, who waits, and what a decision leaves.

The gate is the one place a chat tool call passes through before execution.
These tests drive the real graph with a scripted model and a real checkpointer,
so the interrupt, the approval and the execution that follows are the same
objects production uses -- not a stand-in for them.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import select

from app.config import settings
from app.db.models import ActionAuditLog, AutonomySetting, PerToolOverride, User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.services import capability, chat_graph, command_runner
from app.services.permission_gate import _category_for


class _ScriptedModel:
    """Returns queued responses, one per model call, counting the calls."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.calls = 0
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages, config=None):
        self.calls += 1
        return self.responses.pop(0) if self.responses else AIMessage(content="done")


def _write_call(command: str, call_id: str = "call_1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "run_shell_command", "args": {"command": command}, "id": call_id}
        ],
    )


@pytest.fixture(autouse=True)
def _commands_enabled(monkeypatch):
    monkeypatch.setattr(settings, "command_tool_enabled", True)
    monkeypatch.setattr(settings, "command_approval_timeout_seconds", 0.2)
    monkeypatch.setattr(settings, "command_max_calls_per_turn", 4)
    command_runner.REGISTRY = command_runner.CommandRegistry()
    yield
    command_runner.REGISTRY = command_runner.CommandRegistry()


@pytest.fixture(autouse=True)
def isolated_token(tmp_path, monkeypatch):
    """The authorising endpoints need a capability file that is not the user's."""
    monkeypatch.setattr(
        settings, "capability_token_path", str(tmp_path / "capability-token")
    )
    capability.reset_cache()
    yield
    capability.reset_cache()


@pytest.fixture
def user_id() -> str:
    initialize_database()
    new_id = f"gate-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=new_id, command_tool_enabled=True))
        db.commit()
    return new_id


def _graph(model: _ScriptedModel, user_id: str, monkeypatch):
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_a, **_k: model)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _c: False)
    graph = chat_graph.build_chat_graph(
        "unused-key",
        "test-model",
        user_id=user_id,
        use_web_search=False,
        command_tool_enabled=True,
        checkpointer=InMemorySaver(),
    )
    return graph


def _state(user_id: str, conversation_id: str):
    return chat_graph.initial_chat_state(
        user_id=user_id,
        conversation_id=conversation_id,
        message="run it",
        history=[],
        use_web_search=False,
        command_tool_enabled=True,
    )


def _decisions(user_id: str) -> list[str]:
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(ActionAuditLog)
                .where(ActionAuditLog.user_id == user_id)
                .order_by(ActionAuditLog.timestamp)
            )
        )
    return [row.decision for row in rows]


def test_shell_category_follows_the_command_classifier() -> None:
    """Read-only commands are read_only_info; state-changing ones local_shell."""
    assert _category_for("run_shell_command", {"command": "ls -la"}) == "read_only_info"
    assert _category_for("run_shell_command", {"command": "git status"}) == "read_only_info"
    assert _category_for("run_shell_command", {"command": "echo x > f"}) == "local_shell"
    assert _category_for("run_shell_command", {}) == "local_shell"


def test_a_read_only_command_runs_unattended_and_is_audited(
    user_id: str, monkeypatch, tmp_path
) -> None:
    model = _ScriptedModel(
        [_write_call("echo gate-read-only"), AIMessage(content="done")]
    )
    graph = _graph(model, user_id, monkeypatch)
    conversation_id = str(uuid4())
    config = {"configurable": {"thread_id": conversation_id}}

    result = asyncio.run(
        graph.ainvoke(_state(user_id, conversation_id), config=config)
    )

    assert [run["command"] for run in result["command_runs"]] == ["echo gate-read-only"]
    assert result["command_runs"][0]["exit_code"] == 0
    assert _decisions(user_id) == ["auto_approved"]


def test_a_write_command_pauses_and_only_runs_after_approval(
    user_id: str, monkeypatch, tmp_path
) -> None:
    target = tmp_path / "approved.txt"
    model = _ScriptedModel(
        [
            _write_call(f"echo yes > {target}"),
            AIMessage(content="The file is written."),
        ]
    )
    graph = _graph(model, user_id, monkeypatch)
    conversation_id = str(uuid4())
    config = {"configurable": {"thread_id": conversation_id}}

    asyncio.run(graph.ainvoke(_state(user_id, conversation_id), config=config))

    snap = asyncio.run(graph.aget_state(config))
    cards = [interrupt.value for interrupt in (snap.interrupts or ())]
    assert cards, "a state-changing command has to stop for approval"
    assert cards[0]["type"] == "approval_required"
    assert cards[0]["category"] == "local_shell"
    assert not target.exists(), "the command ran before the user approved it"

    asyncio.run(
        graph.ainvoke(
            Command(resume={"decision": "approved", "approved_this_session": True}),
            config=config,
        )
    )

    assert target.exists(), "an approved command has to actually run"
    assert target.read_text().strip() == "yes"
    assert "user_approved" in _decisions(user_id)


def test_a_denied_command_never_runs(user_id: str, monkeypatch, tmp_path) -> None:
    target = tmp_path / "denied.txt"
    model = _ScriptedModel(
        [_write_call(f"echo no > {target}"), AIMessage(content="Understood.")]
    )
    graph = _graph(model, user_id, monkeypatch)
    conversation_id = str(uuid4())
    config = {"configurable": {"thread_id": conversation_id}}

    asyncio.run(graph.ainvoke(_state(user_id, conversation_id), config=config))
    asyncio.run(
        graph.ainvoke(
            Command(resume={"decision": "denied", "approved_this_session": False}),
            config=config,
        )
    )

    assert not target.exists(), "a denied command was executed"
    assert "user_denied" in _decisions(user_id)


def test_ask_first_time_remembers_the_approval_for_the_session(
    user_id: str, monkeypatch, tmp_path
) -> None:
    with SessionLocal() as db:
        db.add(
            AutonomySetting(
                user_id=user_id, category="local_shell", level="ask_first_time"
            )
        )
        db.commit()

    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    model = _ScriptedModel(
        [
            _write_call(f"echo one > {first}", "call_1"),
            AIMessage(content="done one"),
            _write_call(f"echo two > {second}", "call_2"),
            AIMessage(content="done two"),
        ]
    )
    graph = _graph(model, user_id, monkeypatch)
    conversation_id = str(uuid4())
    config = {"configurable": {"thread_id": conversation_id}}

    asyncio.run(graph.ainvoke(_state(user_id, conversation_id), config=config))
    snap = asyncio.run(graph.aget_state(config))
    assert snap.interrupts, "the first call at ask_first_time has to ask"
    assert not first.exists()

    asyncio.run(
        graph.ainvoke(
            Command(resume={"decision": "approved", "approved_this_session": True}),
            config=config,
        )
    )
    assert first.exists()

    # The next turn's call runs unattended: the session remembers the approval.
    asyncio.run(graph.ainvoke(_state(user_id, conversation_id), config=config))
    snap2 = asyncio.run(graph.aget_state(config))
    assert not snap2.interrupts, "ask_first_time asked a second time in one session"
    assert second.exists()
    with SessionLocal() as db:
        row = db.get(PerToolOverride, (user_id, "run_shell_command", "local_shell"))
        assert row is not None and row.approved_this_session is True


def test_a_second_tool_round_is_gated_too(user_id: str, monkeypatch, tmp_path) -> None:
    """A read-only call cannot smuggle a later write past the gate."""
    target = tmp_path / "second-round.txt"
    model = _ScriptedModel(
        [
            _write_call("echo first-round", "call_1"),
            _write_call(f"echo second > {target}", "call_2"),
            AIMessage(content="done"),
        ]
    )
    graph = _graph(model, user_id, monkeypatch)
    conversation_id = str(uuid4())
    config = {"configurable": {"thread_id": conversation_id}}

    asyncio.run(graph.ainvoke(_state(user_id, conversation_id), config=config))

    snap = asyncio.run(graph.aget_state(config))
    assert snap.interrupts, "the second round's write call bypassed the gate"
    assert not target.exists(), "the second round's write ran before approval"


def test_a_denied_call_that_is_retried_still_asks(user_id: str, monkeypatch, tmp_path) -> None:
    """A denial cannot be talked away by asking again in the same turn."""
    target = tmp_path / "retried.txt"
    model = _ScriptedModel(
        [
            _write_call(f"echo no > {target}", "call_1"),
            _write_call(f"echo no > {target}", "call_2"),
            AIMessage(content="Understood."),
        ]
    )
    graph = _graph(model, user_id, monkeypatch)
    conversation_id = str(uuid4())
    config = {"configurable": {"thread_id": conversation_id}}

    asyncio.run(graph.ainvoke(_state(user_id, conversation_id), config=config))
    asyncio.run(
        graph.ainvoke(
            Command(resume={"decision": "denied", "approved_this_session": False}),
            config=config,
        )
    )

    snap = asyncio.run(graph.aget_state(config))
    assert snap.interrupts, "the retried call after a denial ran without asking"
    assert not target.exists()


def test_never_allow_blocks_at_the_gate_without_a_card(
    user_id: str, monkeypatch, tmp_path
) -> None:
    """The refusal is enforced by the backend, not hidden by the UI."""
    with SessionLocal() as db:
        db.add(
            AutonomySetting(
                user_id=user_id, category="local_shell", level="never_allow"
            )
        )
        db.commit()

    target = tmp_path / "never.txt"
    model = _ScriptedModel(
        [_write_call(f"echo nope > {target}"), AIMessage(content="Understood.")]
    )
    graph = _graph(model, user_id, monkeypatch)
    conversation_id = str(uuid4())
    config = {"configurable": {"thread_id": conversation_id}}

    result = asyncio.run(
        graph.ainvoke(_state(user_id, conversation_id), config=config)
    )

    assert not target.exists(), "a never_allow command was executed"
    messages = [getattr(m, "content", "") for m in result["tool_messages"]]
    assert any("not permitted" in str(content) for content in messages)
    assert _decisions(user_id) == ["blocked_never_allow"]


def test_ask_first_time_approval_does_not_leak_to_another_user(
    user_id: str, monkeypatch, tmp_path
) -> None:
    """Session approvals are scoped to the user who granted them."""
    with SessionLocal() as db:
        db.add(
            AutonomySetting(
                user_id=user_id, category="local_shell", level="ask_first_time"
            )
        )
        db.commit()
    other_id = f"gate-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=other_id, command_tool_enabled=True))
        db.commit()
    with SessionLocal() as db:
        db.add(
            AutonomySetting(
                user_id=other_id, category="local_shell", level="ask_first_time"
            )
        )
        db.commit()

    first = tmp_path / "first-user.txt"
    model = _ScriptedModel(
        [
            _write_call(f"echo one > {first}", "call_1"),
            AIMessage(content="done one"),
        ]
    )
    graph = _graph(model, user_id, monkeypatch)
    conversation_id = str(uuid4())
    config = {"configurable": {"thread_id": conversation_id}}

    asyncio.run(graph.ainvoke(_state(user_id, conversation_id), config=config))
    asyncio.run(
        graph.ainvoke(
            Command(resume={"decision": "approved", "approved_this_session": True}),
            config=config,
        )
    )
    assert first.exists()
    with SessionLocal() as db:
        row = db.get(PerToolOverride, (user_id, "run_shell_command", "local_shell"))
        assert row is not None and row.approved_this_session is True

    # The other user has no approval of their own and must still be asked.
    other_target = tmp_path / "other-user.txt"
    other_model = _ScriptedModel(
        [
            _write_call(f"echo two > {other_target}", "call_1"),
            AIMessage(content="done two"),
        ]
    )
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_a, **_k: other_model)
    other_graph = chat_graph.build_chat_graph(
        "unused-key",
        "test-model",
        user_id=other_id,
        use_web_search=False,
        command_tool_enabled=True,
        checkpointer=InMemorySaver(),
    )
    other_conversation = str(uuid4())
    other_config = {"configurable": {"thread_id": other_conversation}}
    asyncio.run(
        other_graph.ainvoke(
            _state(other_id, other_conversation), config=other_config
        )
    )

    other_snap = asyncio.run(other_graph.aget_state(other_config))
    assert other_snap.interrupts, "one user's approval leaked to another user"
    assert not other_target.exists()


def test_autonomy_settings_round_trip_reports_what_was_saved(user_id: str) -> None:
    client = TestClient(
        app, headers={"X-Pentagon-Capability": capability.load_or_create()}
    )

    put = client.put(
        "/api/autonomy-settings/local_shell",
        params={"user_id": user_id},
        json={"level": "ask_first_time"},
    )
    assert put.status_code == 200

    got = client.get("/api/autonomy-settings", params={"user_id": user_id})
    assert got.status_code == 200
    assert got.json()["settings"]["local_shell"] == "ask_first_time"


def test_audit_log_endpoint_returns_stored_rows(user_id: str) -> None:
    client = TestClient(
        app, headers={"X-Pentagon-Capability": capability.load_or_create()}
    )
    with SessionLocal() as db:
        db.add(
            ActionAuditLog(
                id=str(uuid4()),
                user_id=user_id,
                conversation_id="conversation-audit",
                tool_name="run_shell_command",
                category="local_shell",
                autonomy_level_at_time="always_ask",
                decision="user_approved",
                arguments_summary="run_shell_command(command=ls)",
            )
        )
        db.commit()

    response = client.get("/api/audit-log", params={"user_id": user_id})

    assert response.status_code == 200
    rows = response.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["decision"] == "user_approved"
    assert rows[0]["tool_name"] == "run_shell_command"
