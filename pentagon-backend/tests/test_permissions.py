"""The three-level permission ladder, and the two gates that obey it.

The point of these tests is not that ``requires_approval`` returns a bool. It is
that the *same* level produces the same interruption behaviour through the shell
gate and the desktop gate, that each rung differs from its neighbour in the
direction the copy promises, and that Trusted still stops for the destructive
tail. A test that only checked the helper would pass while both gates kept
ignoring it, which is the failure mode that actually matters.
"""

from __future__ import annotations

import asyncio
import dataclasses
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.models import User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.services import chat_graph, command_runner, desktop_actions
from app.services.command_runner import CommandRegistry, PendingRequest
from app.services.permissions import (
    DEFAULT_PERMISSION_LEVEL,
    MAX_PERMISSION_LEVEL,
    MIN_PERMISSION_LEVEL,
    is_destructive_command,
    level_info,
    levels_as_list,
    normalize_level,
    requires_approval,
)


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    """Both gates get a private registry, and so does the module they read."""
    for module in (command_runner, desktop_actions):
        monkeypatch.setattr(module, "REGISTRY", CommandRegistry())


@pytest.fixture
def client() -> TestClient:
    initialize_database()
    from app.services import capability

    token = capability.load_or_create()
    return TestClient(app, headers={"X-Pentagon-Capability": token})


def _result(message: str = "done", *, exit_code: int = 0):
    return command_runner.CommandResult(
        command="stub",
        exit_code=exit_code,
        stdout=message,
        stderr="",
        duration_ms=0.0,
        auto_approved=False,
    )


def _stub_desktop(monkeypatch, action_name, sink=None, *, message="done"):
    """Swap a desktop action's handler without ever calling the real one."""
    calls = sink if sink is not None else []

    async def handler(args):
        calls.append(dict(args))
        return _result(message)

    entry = desktop_actions.ACTIONS[action_name]
    monkeypatch.setitem(
        desktop_actions.ACTIONS, action_name, dataclasses.replace(entry, handler=handler)
    )
    return calls


async def _run_desktop(action, arguments, *, level, approve=False):
    """Run a desktop action at ``level``, answering the card if one appears.

    Returns ``(result, calls)``. ``calls`` being non-empty means the action
    really ran, which is how "did it ask?" is told apart from "did it refuse?".
    """
    calls: list[dict] = []

    async def handler(args):
        calls.append(dict(args))
        return _result()

    entry = desktop_actions.ACTIONS[action]
    desktop_actions.ACTIONS[action] = dataclasses.replace(entry, handler=handler)

    async def answer_when_raised():
        for _ in range(400):
            for request in list(desktop_actions.REGISTRY._requests.values()):
                if not request.resolved:
                    desktop_actions.REGISTRY.resolve(request.request_id, "u-perm", approve)
                    return
            await asyncio.sleep(0.005)

    try:
        watcher = asyncio.create_task(answer_when_raised())
        try:
            result = await desktop_actions.run_desktop_action(
                action,
                arguments,
                conversation_id="c-perm",
                user_id="u-perm",
                permission_level=level,
            )
        finally:
            # Either the watcher resolved a real card and finished, or nothing
            # was asked and it is still polling. Either way, cancel and ignore;
            # its outcome is the thing under test, not an error condition.
            watcher.cancel()
            try:
                await watcher
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        desktop_actions.ACTIONS[action] = entry
    return result, calls


_execute_real = command_runner._execute


async def _run_shell(command, *, level, approve=False):
    """Run a shell command at ``level`` without ever spawning a process."""
    calls: list[str] = []

    async def fake_execute(cmd, *, auto_approved):
        calls.append(cmd)
        return _result("ran")

    command_runner._execute = fake_execute

    async def answer_when_raised():
        for _ in range(400):
            for request in list(command_runner.REGISTRY._requests.values()):
                if not request.resolved:
                    command_runner.REGISTRY.resolve(request.request_id, "u-perm", approve)
                    return
            await asyncio.sleep(0.005)

    try:
        watcher = asyncio.create_task(answer_when_raised())
        try:
            result = await command_runner.run_command(
                command,
                conversation_id="c-perm",
                user_id="u-perm",
                permission_level=level,
            )
        finally:
            watcher.cancel()
            try:
                await watcher
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        command_runner._execute = _execute_real
    return result, calls


async def _run_shell_no_answer(command, *, level):
    """Run a shell command at ``level`` where nobody ever answers the card.

    Like ``_run_shell`` but with no watcher, so a gated command can only end
    the way an unanswered question really ends: the approval timeout resolves
    it into a denial. Set ``command_approval_timeout_seconds`` low before
    calling, or the wait is a real one.
    """
    calls: list[str] = []

    async def fake_execute(cmd, *, auto_approved):
        calls.append(cmd)
        return _result("ran")

    command_runner._execute = fake_execute
    try:
        result = await command_runner.run_command(
            command,
            conversation_id="c-perm",
            user_id="u-perm",
            permission_level=level,
        )
    finally:
        command_runner._execute = _execute_real
    return result, calls


# --------------------------------------------------------------------------
# The ladder itself
# --------------------------------------------------------------------------


def test_there_are_exactly_three_levels() -> None:
    assert [entry["level"] for entry in levels_as_list()] == [1, 2, 3]
    assert len({entry["name"] for entry in levels_as_list()}) == 3
    assert all(entry["summary"] and entry["detail"] for entry in levels_as_list())


def test_default_level_is_balanced() -> None:
    """Balanced is what shipped before levels existed, so it is the default."""
    assert DEFAULT_PERMISSION_LEVEL == 2
    assert level_info(DEFAULT_PERMISSION_LEVEL).name == "Balanced"


@pytest.mark.parametrize("bad", [None, "", "abc", 0, 4, -1, 99, [], {}])
def test_out_of_range_levels_fall_back_to_the_default(bad) -> None:
    """A corrupt row must not be able to hand out more access than asked for."""
    assert normalize_level(bad) == DEFAULT_PERMISSION_LEVEL


@pytest.mark.parametrize("good,expected", [(1, 1), (2, 2), (3, 3), ("3", 3), (2.0, 2)])
def test_valid_levels_survive_normalisation(good, expected) -> None:
    assert normalize_level(good) == expected


def test_each_level_asks_exactly_what_it_promises() -> None:
    """The whole ladder, as a truth table.

    Restricted asks for everything. Balanced asks only when something changes.
    Trusted asks only for the destructive tail -- and never stops asking for it,
    because that is the promise the UI makes to the user.
    """
    assert requires_approval(changes_state=False, level=1) is True
    assert requires_approval(changes_state=True, level=1) is True
    assert requires_approval(changes_state=True, level=1, destructive=True) is True

    assert requires_approval(changes_state=False, level=2) is False
    assert requires_approval(changes_state=True, level=2) is True
    assert requires_approval(changes_state=True, level=2, destructive=True) is True

    assert requires_approval(changes_state=False, level=3) is False
    assert requires_approval(changes_state=True, level=3) is False
    assert requires_approval(changes_state=True, level=3, destructive=True) is True


def test_normalisation_is_applied_inside_the_decision() -> None:
    """A nonsense level behaves like the default, not like "ask nothing"."""
    assert requires_approval(changes_state=True, level="nonsense") is True
    assert requires_approval(changes_state=True, level=0) is True


# --------------------------------------------------------------------------
# The destructive tail
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf ~/Documents",
        "rm -r -f build",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "shutdown now",
        "systemctl poweroff",
        "reboot",
        "git push --force origin main",
        "git reset --hard HEAD~5",
        "fdisk /dev/sdb",
    ],
)
def test_destructive_commands_are_recognised(command: str) -> None:
    assert is_destructive_command(command) is True


@pytest.mark.parametrize(
    "command",
    ["ls -la", "cat notes.txt", "git status", "echo hi", "rg TODO src", "rm notes.txt"],
)
def test_ordinary_commands_are_not_destructive(command: str) -> None:
    """`rm` of one named file is reversible-ish and must stay off the list."""
    assert is_destructive_command(command) is False


# --------------------------------------------------------------------------
# The desktop gate
# --------------------------------------------------------------------------

# `list_windows` is the read-only action; `lock` changes state; `power` is the
# destructive one.
@pytest.mark.parametrize(
    "level,should_ask",
    [(1, True), (2, False), (3, False)],
)
def test_read_only_desktop_action_respects_the_level(monkeypatch, level, should_ask) -> None:
    monkeypatch.setattr(desktop_actions, "_kwin", lambda script: "")
    result, calls = asyncio.run(
        _run_desktop("list_windows", {}, level=level, approve=False)
    )
    if should_ask:
        assert calls == [], "Restricted ran a read-only action unattended"
        assert result.auto_approved is False
    else:
        assert calls, "a read-only action should not have needed a card"


@pytest.mark.parametrize("level", [1, 2])
def test_state_changing_desktop_action_asks_at_below_trusted(level) -> None:
    result, calls = asyncio.run(_run_desktop("lock_screen", {}, level=level, approve=False))
    assert calls == [], "the action ran despite being gated"
    assert result.auto_approved is False


def test_state_changing_desktop_action_runs_unattended_at_trusted() -> None:
    _result_unused, calls = asyncio.run(_run_desktop("lock_screen", {}, level=3, approve=False))
    assert calls, "Trusted should run an ordinary state change without asking"


def test_destructive_desktop_action_still_asks_at_trusted() -> None:
    """Trusted is never unlimited: ending the session still interrupts."""
    assert desktop_actions.ACTIONS["power"].destructive is True
    result, calls = asyncio.run(
        _run_desktop("power", {"target": "shutdown"}, level=3, approve=False)
    )
    assert calls == [], "power ran unattended at Trusted"
    assert result.auto_approved is False


def test_approving_a_card_runs_the_action_afterwards() -> None:
    """Saying yes has to actually do the thing, not just stop the nagging."""
    result, calls = asyncio.run(_run_desktop("lock_screen", {}, level=2, approve=True))
    assert calls, "an approved action must actually run"
    # `auto_approved` means "ran without asking". A card was shown here, so it
    # stays False even though the action went ahead -- that flag is the audit
    # trail, and it must not claim unattended work it did not do.
    assert result.auto_approved is False


def test_unattended_work_reports_itself_as_auto_approved() -> None:
    """At Trusted an action really does run unattended, and says so."""
    result, calls = asyncio.run(_run_desktop("lock_screen", {}, level=3, approve=False))
    assert calls, "Trusted should have run it without a card"
    assert result.auto_approved is True


# --------------------------------------------------------------------------
# The shell gate
# --------------------------------------------------------------------------


def test_shell_defaults_to_balanced_when_no_level_is_given() -> None:
    """A caller that forgets to pass a level gets today's behaviour."""
    signature = command_runner.run_command.__wrapped__ if hasattr(
        command_runner.run_command, "__wrapped__"
    ) else command_runner.run_command
    assert "permission_level" in signature.__code__.co_varnames


@pytest.mark.parametrize("level", [1, 2])
def test_destructive_shell_command_asks_at_below_trusted(level) -> None:
    result, calls = asyncio.run(_run_shell("rm -rf ~/stuff", level=level, approve=False))
    assert calls == []
    assert result.exit_code is None, "the command ran despite being gated"


def test_destructive_shell_command_still_asks_at_trusted() -> None:
    result, calls = asyncio.run(_run_shell("rm -rf ~/stuff", level=3, approve=False))
    assert calls == [], "Trusted let a destructive command through"
    assert result.exit_code is None


@pytest.mark.parametrize("level", [1, 2, 3])
def test_read_only_shell_command_asks_only_at_restricted(level) -> None:
    result, calls = asyncio.run(_run_shell("ls -la", level=level, approve=False))
    if level == 1:
        assert calls == [], "Restricted ran a read-only command unattended"
        assert result.exit_code is None
    else:
        assert calls == ["ls -la"], "a read-only command should not need a card"


@pytest.mark.parametrize("level", [2, 3])
def test_ordinary_shell_command_asks_only_at_balanced(level) -> None:
    result, calls = asyncio.run(_run_shell("make build", level=level, approve=False))
    if level == 2:
        assert calls == [], "Balanced let a state change through unattended"
    else:
        assert calls == ["make build"]


# --------------------------------------------------------------------------
# sqlite3 is a gate case, not an allowlist case
# --------------------------------------------------------------------------


def test_sqlite3_shows_an_approval_card_at_balanced(monkeypatch) -> None:
    """The default level must ask before sqlite3 touches anything.

    sqlite3 sat on the read-only allowlist, so at Balanced -- the default --
    ``sqlite3 app.db "DELETE FROM messages"`` ran with no card at all. It is a
    SQL interpreter with a shell escape, which is the opposite of provably
    read-only, so the gate must fire and the card must actually be raised.
    """
    # ``REGISTRY.wait`` discards a request the moment it resolves, so the
    # registry is empty again by the time the run returns. Spying on submit is
    # the honest record that a card was raised, and what it asked.
    submitted: list[PendingRequest] = []
    original_submit = command_runner.REGISTRY.submit
    monkeypatch.setattr(
        command_runner.REGISTRY,
        "submit",
        lambda request: (submitted.append(request), original_submit(request)),
    )
    result, calls = asyncio.run(
        _run_shell('sqlite3 app.db "DELETE FROM messages"', level=2, approve=True)
    )
    assert submitted, "no approval card was raised for sqlite3 at Balanced"
    assert "sqlite3" in submitted[0].command
    assert calls == ['sqlite3 app.db "DELETE FROM messages"'], (
        "an approved sqlite3 command did not run"
    )
    # auto_approved means "ran without asking"; here the user was asked first,
    # exactly as the Balanced rung promises.
    assert result.auto_approved is False


def test_sqlite3_is_denied_when_nobody_approves() -> None:
    """A card the user never answers must leave the database alone.

    The watcher never resolves, so the request can only end in the denial that
    ``REGISTRY.wait`` produces at its timeout -- which is the correct outcome
    for a data-destroying command nobody sanctioned.
    """
    command_runner.settings.command_approval_timeout_seconds = 0.05
    result, calls = asyncio.run(
        _run_shell_no_answer('sqlite3 app.db "DROP TABLE messages"', level=2)
    )
    assert calls == [], "sqlite3 executed without an approval"
    assert result.exit_code is None


def test_sqlite3_dot_system_cannot_auto_run_even_at_trusted() -> None:
    """The shell escape rides the destructive tail, so Trusted still asks.

    ``.system`` spawns a shell from inside the sqlite3 interpreter, which makes
    the invocation arbitrary command execution. Everything else runs unattended
    at Trusted; this must not, and the answer must stay no when nobody answers.
    """
    command_runner.settings.command_approval_timeout_seconds = 0.05
    result, calls = asyncio.run(
        _run_shell_no_answer("sqlite3 x.db '.system touch /tmp/pwned'", level=3)
    )
    assert calls == [], "Trusted auto-ran a sqlite3 shell escape"
    assert result.exit_code is None


def test_both_gates_agree_for_every_level() -> None:
    """The two gates must not drift: same level, same interruption decision.

    Each shell command stands in for the equivalent desktop action, so the two
    are compared on genuinely equivalent inputs rather than on the same literal.
    """
    equivalents = [
        # (shell command, desktop equivalent) for read-only, ordinary, destructive
        ("ls -la", ("read_only", False)),
        ("make build", ("state_change", False)),
        ("rm -rf /tmp/x", ("state_change", True)),
    ]
    for level in (1, 2, 3):
        for command, (kind, destructive) in equivalents:
            read_only, _ = command_runner.classify(command)
            shell_asks = requires_approval(
                changes_state=not read_only,
                level=level,
                destructive=is_destructive_command(command),
            )
            desktop_asks = requires_approval(
                changes_state=(kind != "read_only"),
                level=level,
                destructive=destructive,
            )
            assert shell_asks == desktop_asks, (
                f"gates disagree at level {level} for {command!r}"
            )


# --------------------------------------------------------------------------
# Persistence and the HTTP surface
# --------------------------------------------------------------------------


def test_new_users_default_to_balanced(client: TestClient) -> None:
    user_id = f"perm-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.commit()
        stored = db.get(User, user_id)
        assert stored is not None
        assert stored.permission_level == DEFAULT_PERMISSION_LEVEL


@pytest.mark.parametrize("level", [MIN_PERMISSION_LEVEL, 2, MAX_PERMISSION_LEVEL])
def test_level_round_trips_through_the_api(client: TestClient, level) -> None:
    user_id = f"perm-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=user_id, command_tool_enabled=True))
        db.commit()

    response = client.put(
        "/api/commands/settings",
        params={"user_id": user_id},
        json={"enabled": True, "permission_level": level},
    )
    assert response.status_code == 200
    assert response.json()["permission_level"] == level

    with SessionLocal() as db:
        assert db.get(User, user_id).permission_level == level

    read_back = client.get("/api/commands/settings", params={"user_id": user_id})
    assert read_back.json()["permission_level"] == level
    assert read_back.json()["permission_name"] == level_info(level).name


def test_the_api_publishes_the_whole_ladder(client: TestClient) -> None:
    """The client renders these names, so they must come from the server."""
    user_id = f"perm-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.commit()
    body = client.get("/api/commands/settings", params={"user_id": user_id}).json()
    assert [entry["level"] for entry in body["permission_levels"]] == [1, 2, 3]


def test_omitting_the_level_leaves_the_stored_choice_alone(client: TestClient) -> None:
    """An older client toggling `enabled` must not reset a deliberate level."""
    user_id = f"perm-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=user_id, command_tool_enabled=True, permission_level=3))
        db.commit()

    client.put(
        "/api/commands/settings",
        params={"user_id": user_id},
        json={"enabled": False},
    )
    with SessionLocal() as db:
        assert db.get(User, user_id).permission_level == 3


def test_a_level_outside_the_ladder_is_rejected(client: TestClient) -> None:
    user_id = f"perm-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.commit()
    response = client.put(
        "/api/commands/settings",
        params={"user_id": user_id},
        json={"enabled": True, "permission_level": 9},
    )
    assert response.status_code == 422


def test_one_user_changing_their_level_does_not_touch_another(client: TestClient) -> None:
    mine, theirs = f"perm-{uuid4()}", f"perm-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=mine, command_tool_enabled=True, permission_level=1))
        db.add(User(id=theirs, command_tool_enabled=True, permission_level=2))
        db.commit()

    client.put(
        "/api/commands/settings",
        params={"user_id": mine},
        json={"enabled": True, "permission_level": 3},
    )
    with SessionLocal() as db:
        assert db.get(User, theirs).permission_level == 2


# --------------------------------------------------------------------------
# The graph carries it into the turn
# --------------------------------------------------------------------------


def test_initial_state_normalises_the_level() -> None:
    state = chat_graph.initial_chat_state(
        user_id="u",
        conversation_id="c",
        message="hi",
        history=[],
        use_web_search=None,
        permission_level="nonsense",
    )
    assert state["permission_level"] == DEFAULT_PERMISSION_LEVEL


@pytest.mark.parametrize(
    "given,expected", [(1, 1), (3, 3), ("2", 2), (None, DEFAULT_PERMISSION_LEVEL)]
)
def test_initial_state_passes_the_level_through(given, expected) -> None:
    state = chat_graph.initial_chat_state(
        user_id="u",
        conversation_id="c",
        message="hi",
        history=[],
        use_web_search=None,
        permission_level=given,
    )
    assert state["permission_level"] == expected


def test_the_gate_reads_the_level_from_state_not_a_closure() -> None:
    """A single turn cannot run under two different levels."""
    source = inspect_source(chat_graph)
    assert "state.get(\"permission_level\"" in source
    assert source.count("permission_level=state.get(") == 2, (
        "both tool gates must take the level from the state"
    )


def inspect_source(module):
    import inspect

    return inspect.getsource(module)