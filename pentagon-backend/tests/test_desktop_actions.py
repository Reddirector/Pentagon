"""Desktop control: the actions themselves and the approval gate in front of them.

The interesting claims are not "an action ran", they are:

* Listing windows runs unattended; everything that changes state waits for the
  user, because the whole feature is "open and close things on my machine".
* A denial, a timeout or an unanswered request changes nothing at all.
* Somebody else's ``user_id`` cannot approve or even see a pending request.
* No action can be talked into running a shell, and no argument can smuggle
  one past the URL, path or application-name checks.

Nothing in here touches the real desktop: every handler that would shell out is
replaced through the registry before it runs.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from app.services import chat_graph, desktop_actions
from app.services.command_runner import CommandRegistry, PendingRequest


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    """Every test gets a private pending-request registry."""
    fresh = CommandRegistry()
    monkeypatch.setattr(desktop_actions, "REGISTRY", fresh)
    return fresh


def _stub(monkeypatch, action_name, sink=None, *, message="done", exit_code=0):
    """Replace a handler without ever calling the real one.

    ``ACTIONS`` captures handler references when it is built, so patching the
    module attribute would not take effect; the registry entry is what the
    dispatcher actually calls.
    """
    calls = sink if sink is not None else []

    async def handler(args):
        calls.append(dict(args))
        return _result(message, exit_code=exit_code)

    entry = desktop_actions.ACTIONS[action_name]
    monkeypatch.setitem(
        desktop_actions.ACTIONS, action_name, dataclasses.replace(entry, handler=handler)
    )
    return calls


def _result(message: str, *, exit_code=0, stderr=""):
    from app.services.command_runner import CommandResult

    return CommandResult(
        command="stub",
        exit_code=exit_code,
        stdout=message,
        stderr=stderr,
        duration_ms=0.0,
        auto_approved=False,
    )


async def _answer_when_raised(user_id, approved):
    """Wait for a request to appear, then answer it."""
    for _ in range(400):
        for request in list(desktop_actions.REGISTRY._requests.values()):
            if not request.resolved:
                desktop_actions.REGISTRY.resolve(request.request_id, user_id, approved)
                return request
        await asyncio.sleep(0.01)
    raise AssertionError("no pending request was ever raised")


# --------------------------------------------------------------------------
# What is on offer
# --------------------------------------------------------------------------


def test_every_documented_action_exists():
    for name in (
        "list_windows", "system_info", "open_app", "open_url", "open_path",
        "focus_window", "close_window", "close_app", "launch_desktop_file",
        "screenshot", "volume", "media", "notify", "lock_screen", "dark_mode",
        "power",
    ):
        assert name in desktop_actions.ACTIONS


def test_desktop_file_launch_is_confined_to_applications_folders(tmp_path):
    """The .desktop file is executed, so its path must not be arbitrary."""
    outside = tmp_path / "evil.desktop"
    outside.write_text("[Desktop Entry]\nExec=/bin/sh\n")
    assert desktop_actions._desktop_file_path(str(outside)) is None
    for hostile in (
        "/etc/passwd",
        "/tmp/anything.desktop",
        "~/.config/autostart/evil.desktop",
        "notadesktopfile",
        "",
    ):
        assert desktop_actions._desktop_file_path(hostile) is None, hostile
    real = "/usr/share/applications/kcalc.desktop"
    if os.path.isfile(real):
        assert desktop_actions._desktop_file_path(real) == real


def _wins(*captions, resource="zenity"):
    return [desktop_actions.Window(c, resource, "") for c in captions]


def _mock_windows(monkeypatch, *captions, resource="zenity"):
    """Make the read-only resolution step find these windows."""
    async def fake_kwin(script, timeout=10.0):
        return _rows(*captions, resource=resource)

    monkeypatch.setattr(desktop_actions, "_kwin", fake_kwin)
    return fake_kwin


def _op(script: str) -> str:
    """Which operation a generated KWin script carries."""
    marker = 'const operation = "'
    start = script.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    return script[start:script.find('"', start)]


def _rows(*captions, resource="zenity"):
    """The shape _kwin returns for a listing operation."""
    return [f"window\t{c}\t{resource}\t-" for c in captions] + ["__END__"]


def test_close_app_reports_a_no_match_instead_of_guessing(monkeypatch):
    async def fake_kwin(_script, timeout=10.0):
        return _rows()

    monkeypatch.setattr(desktop_actions, "_kwin", fake_kwin)
    result = asyncio.run(desktop_actions._action_close_app({"target": "nope"}))
    assert result.exit_code == 1
    assert "not resolved" in result.stderr


def test_close_app_names_every_window_it_asked_to_close(monkeypatch):
    calls: list[str] = []

    async def fake_kwin(script, timeout=10.0):
        calls.append(script)
        if _op(script) == "closeAll":
            return ["matched=Doc - one", "matched=Doc - two", "closed-count=2", "__END__"]
        return _rows("Doc - one", "Doc - two")

    monkeypatch.setattr(desktop_actions, "_kwin", fake_kwin)
    result = asyncio.run(desktop_actions._action_close_app(
        {"target": "doc", "_resolved": _wins("Doc - one", "Doc - two")}))
    assert result.ok
    assert "2 window(s)" in result.stdout
    assert "Doc - one" in result.stdout and "Doc - two" in result.stdout


def test_close_app_says_so_when_a_window_refuses(monkeypatch):
    async def fake_kwin(script, timeout=10.0):
        if _op(script) == "closeAll":
            return ["matched=Doc - one", "refused=Sticky", "closed-count=2", "__END__"]
        return _rows("Doc - one", "Sticky")

    monkeypatch.setattr(desktop_actions, "_kwin", fake_kwin)
    result = asyncio.run(desktop_actions._action_close_app(
        {"target": "doc", "_resolved": _wins("Doc - one", "Sticky")}))
    assert result.ok
    assert "refused to close" in result.stdout
    assert "Sticky" in result.stdout


def test_an_ambiguous_window_refuses_without_ever_asking(monkeypatch):
    """Two matches must never resolve to 'close the first one'.

    The refusal has to happen in the dispatcher, before the approval card: a
    question on screen for something that is about to refuse is worse than no
    question at all.
    """
    acted: list[str] = []

    async def fake_kwin(script, timeout=10.0):
        if _op(script) in ("close", "focus"):
            acted.append(script)
        return _rows("Editor - a", "Editor - b")

    monkeypatch.setattr(desktop_actions, "_kwin", fake_kwin)
    for action in ("close_window", "focus_window"):
        result = asyncio.run(
            desktop_actions.run_desktop_action(
                action, {"target": "editor"}, conversation_id="c1", user_id="u1"
            )
        )
        assert result.exit_code == 1, action
        assert "matches 2 windows" in result.stderr, action
        assert "Editor - a" in result.stderr and "Editor - b" in result.stderr, action
        assert "Retry with an exact title" in result.stderr, action
        # Nothing was ever put in front of the user.
        assert desktop_actions.REGISTRY._requests == {}, action
    assert acted == [], "it acted on an ambiguous target"


def test_a_window_that_matches_nothing_refuses_without_asking(monkeypatch):
    async def fake_kwin(script, timeout=10.0):
        return _rows()

    monkeypatch.setattr(desktop_actions, "_kwin", fake_kwin)
    result = asyncio.run(
        desktop_actions.run_desktop_action(
            "close_window", {"target": "ghost"}, conversation_id="c1", user_id="u1"
        )
    )
    assert result.exit_code == 1
    assert "No open window matches" in result.stderr
    assert desktop_actions.REGISTRY._requests == {}


def test_the_model_cannot_forge_resolved_state(monkeypatch):
    """Underscore keys are the dispatcher's; the model must not supply them."""
    from app.config import settings

    monkeypatch.setattr(settings, "desktop_action_approval_timeout_seconds", 0.15)
    _mock_windows(monkeypatch, "Real - window")
    calls = _stub(monkeypatch, "close_window")

    seen = {}

    async def _scenario():
        task = asyncio.create_task(
            desktop_actions.run_desktop_action(
                "close_window",
                {"target": "Real", "_resolved": [{"caption": "Something Else"}]},
                conversation_id="c1", user_id="u1",
            )
        )
        for _ in range(400):
            if desktop_actions.REGISTRY._requests:
                break
            await asyncio.sleep(0.01)
        pending = list(desktop_actions.REGISTRY._requests.values())[0]
        seen["detail"] = pending.detail
        return await task

    asyncio.run(_scenario())
    # The forged entry was dropped and the target re-resolved from the live
    # session, so the card names the real window and nothing else was closed.
    assert "Real - window" in seen["detail"]
    assert "Something Else" not in seen["detail"]
    assert calls == [], "the handler ran despite the request being denied"


def test_approval_card_names_the_window_it_resolved(monkeypatch):
    async def fake_kwin(script, timeout=10.0):
        if _op(script) == "list":
            return _rows("Editor - a", resource="code")
        return ["matched=Editor - a", "__END__"]

    monkeypatch.setattr(desktop_actions, "_kwin", fake_kwin)
    _stub(monkeypatch, "close_window")
    observed = {}

    async def _scenario():
        task = asyncio.create_task(
            desktop_actions.run_desktop_action(
                "close_window", {"target": "code"}, conversation_id="c1", user_id="u1"
            )
        )
        for _ in range(400):
            if desktop_actions.REGISTRY._requests:
                break
            await asyncio.sleep(0.01)
        pending = list(desktop_actions.REGISTRY._requests.values())[0]
        observed["detail"] = pending.detail
        desktop_actions.REGISTRY.resolve(pending.request_id, "u1", True)
        return await task

    asyncio.run(_scenario())
    assert "Editor - a" in observed["detail"]


def test_detail_reaches_the_pending_listing(monkeypatch):
    async def fake_kwin(script, timeout=10.0):
        return _rows("Editor - a", "Editor - b")

    monkeypatch.setattr(desktop_actions, "_kwin", fake_kwin)
    _stub(monkeypatch, "close_app")

    async def _scenario():
        task = asyncio.create_task(
            desktop_actions.run_desktop_action(
                "close_app", {"target": "editor"}, conversation_id="c1", user_id="u1"
            )
        )
        for _ in range(400):
            if desktop_actions.REGISTRY._requests:
                break
            await asyncio.sleep(0.01)
        rows = desktop_actions.REGISTRY.pending_for("c1", "u1")
        desktop_actions.REGISTRY.resolve(
            list(desktop_actions.REGISTRY._requests.values())[0].request_id, "u1", True
        )
        await task
        return rows

    rows = asyncio.run(_scenario())
    assert "2 windows" in rows[0]["detail"]
    assert "Editor - a" in rows[0]["detail"]


def test_shell_requests_have_no_detail(monkeypatch):
    """The extra field must not disturb the shell tool's own cards."""
    from app.services import command_runner

    _stub(monkeypatch, "close_window")
    request = command_runner.PendingRequest(
        request_id="abc", conversation_id="c1", user_id="u1",
        command="ls -la", reason="asked", created_at=0.0,
    )
    assert request.detail == ""
    assert command_runner.REGISTRY.pending_for("c1", "u1") == []
    command_runner.REGISTRY.submit(request)
    assert command_runner.REGISTRY.pending_for("c1", "u1")[0]["detail"] == ""


def test_desktop_timeout_is_independent_of_the_shell_timeout(monkeypatch):
    """Desktop actions wait on their own knob, not the shell's."""
    from app.config import settings

    monkeypatch.setattr(settings, "command_approval_timeout_seconds", 30.0)
    monkeypatch.setattr(settings, "desktop_action_approval_timeout_seconds", 0.15)
    _mock_windows(monkeypatch, "Firefox")
    calls = _stub(monkeypatch, "close_window")
    result = asyncio.run(
        desktop_actions.run_desktop_action(
            "close_window", {"target": "x"}, conversation_id="c1", user_id="u1"
        )
    )
    # If the shell timeout were used, this would have sat for 30 seconds.
    assert calls == []
    assert result.exit_code is None
    assert result.auto_approved is False


def test_window_script_supports_closing_every_match():
    script = desktop_actions._windows_script("closeAll", "doc")
    assert 'const operation = "closeAll";' in script
    assert "for (const w of matches)" in script


def test_only_read_only_actions_run_unattended():
    assert desktop_actions.AUTO_APPROVED_ACTIONS == {"list_windows", "system_info"}


def test_every_state_changing_action_needs_approval():
    for name, action in desktop_actions.ACTIONS.items():
        if name in {"list_windows", "system_info"}:
            continue
        assert action.needs_approval, name
        assert action.changes_state, name


def test_tool_schema_enumerates_exactly_the_registry():
    schema = desktop_actions.DESKTOP_TOOL_SCHEMA["function"]
    assert schema["name"] == "run_desktop_action"
    assert sorted(schema["parameters"]["properties"]["action"]["enum"]) == sorted(
        desktop_actions.ACTIONS
    )


def test_unknown_action_is_refused_and_names_alternatives():
    result = asyncio.run(
        desktop_actions.run_desktop_action(
            "self_destruct", {}, conversation_id="c1", user_id="u1"
        )
    )
    assert not result.ok
    assert "list_windows" in result.stderr


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------


def test_read_only_action_needs_no_approval(monkeypatch):
    calls = _stub(monkeypatch, "list_windows")
    result = asyncio.run(
        desktop_actions.run_desktop_action(
            "list_windows", {}, conversation_id="c1", user_id="u1"
        )
    )
    assert result.ok
    assert result.auto_approved is True
    assert calls == [{}]
    assert desktop_actions.REGISTRY._requests == {}


def test_state_change_waits_for_the_user(monkeypatch):
    calls = _stub(monkeypatch, "open_app")
    observed = {}

    async def _scenario():
        task = asyncio.create_task(
            desktop_actions.run_desktop_action(
                "open_app", {"target": "firefox"}, conversation_id="c1", user_id="u1"
            )
        )
        for _ in range(400):
            if desktop_actions.REGISTRY._requests:
                break
            await asyncio.sleep(0.01)
        pending = list(desktop_actions.REGISTRY._requests.values())[0]
        observed["command"] = pending.command
        observed["reason"] = pending.reason
        # The critical moment: the request is on screen and nothing has run.
        observed["calls_before_decision"] = list(calls)
        desktop_actions.REGISTRY.resolve(pending.request_id, "u1", True)
        return await task

    result = asyncio.run(_scenario())
    assert observed["calls_before_decision"] == [], "the action ran before the user said yes"
    assert "firefox" in observed["command"]
    assert observed["reason"]
    assert calls == [{"target": "firefox"}]
    assert result.ok


def test_denial_changes_nothing(monkeypatch):
    calls = _stub(monkeypatch, "lock_screen")

    async def _scenario():
        task = asyncio.create_task(
            desktop_actions.run_desktop_action(
                "lock_screen", {}, conversation_id="c1", user_id="u1"
            )
        )
        await _answer_when_raised("u1", False)
        return await task

    result = asyncio.run(_scenario())
    assert calls == []
    assert result.exit_code is None
    assert "did not approve" in result.stderr


def test_silence_is_a_denial(monkeypatch):
    from app.config import settings

    # Desktop actions have their own, shorter window -- patching the shell one
    # would leave this waiting out the real 120s.
    monkeypatch.setattr(settings, "desktop_action_approval_timeout_seconds", 0.15)
    _mock_windows(monkeypatch, "Firefox")
    calls = _stub(monkeypatch, "close_window")
    result = asyncio.run(
        desktop_actions.run_desktop_action(
            "close_window", {"target": "firefox"}, conversation_id="c1", user_id="u1"
        )
    )
    assert calls == []
    assert result.exit_code is None
    assert result.auto_approved is False


def test_another_user_cannot_approve(monkeypatch):
    calls = _stub(monkeypatch, "power")
    seen = {}

    async def _scenario():
        task = asyncio.create_task(
            desktop_actions.run_desktop_action(
                "power", {"target": "shutdown"}, conversation_id="c1", user_id="owner"
            )
        )
        for _ in range(400):
            if desktop_actions.REGISTRY._requests:
                break
            await asyncio.sleep(0.01)
        pending = list(desktop_actions.REGISTRY._requests.values())[0]
        seen["attacker_resolve"] = desktop_actions.REGISTRY.resolve(pending.request_id, "attacker", True)
        seen["attacker_get"] = desktop_actions.REGISTRY.get(pending.request_id, "attacker")
        seen["attacker_sees"] = desktop_actions.REGISTRY.pending_for("c1", "attacker")
        seen["owner_resolve"] = desktop_actions.REGISTRY.resolve(pending.request_id, "owner", True)
        return await task

    result = asyncio.run(_scenario())
    assert seen["attacker_resolve"] is False
    assert seen["attacker_get"] is None
    assert seen["attacker_sees"] == []
    assert seen["owner_resolve"] is True
    assert calls == [{"target": "shutdown"}]
    assert result.ok


def test_pending_listing_is_scoped_to_owner_and_conversation():
    request = PendingRequest(
        request_id=uuid4().hex,
        conversation_id="c1",
        user_id="owner",
        command="Lock the screen",
        reason="asked",
        created_at=0.0,
    )
    desktop_actions.REGISTRY.submit(request)
    assert len(desktop_actions.REGISTRY.pending_for("c1", "owner")) == 1
    assert desktop_actions.REGISTRY.pending_for("c1", "someone_else") == []
    assert desktop_actions.REGISTRY.pending_for("other-conversation", "owner") == []


# --------------------------------------------------------------------------
# Arguments cannot smuggle anything
# --------------------------------------------------------------------------


def test_open_url_only_accepts_http_and_https():
    for hostile in (
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/html,<script>",
        "ftp://example.com",
        "chrome://settings",
    ):
        assert desktop_actions._safe_url(hostile) is None, hostile
    assert desktop_actions._safe_url("https://example.com") == "https://example.com"
    assert desktop_actions._safe_url("http://localhost:5173") == "http://localhost:5173"


def test_open_app_rejects_anything_that_is_not_an_application_name():
    for hostile in (
        "firefox; rm -rf ~",
        "firefox && curl evil.test",
        "../../bin/sh",
        "/usr/bin/env",
        "firefox\nrm -rf ~",
        "$(whoami)",
        "",
    ):
        assert desktop_actions._clean_app_name(hostile) is None, hostile
    assert desktop_actions._clean_app_name("firefox") == "firefox"
    assert desktop_actions._clean_app_name(" code ") == "code"
    assert desktop_actions._clean_app_name("Google Chrome") == "Google Chrome"


def test_window_title_is_escaped_before_reaching_the_script():
    hostile = '"; pentagon.closeWindow(); //'
    script = desktop_actions._windows_script("list", hostile)
    # The title is bound as JSON-encoded data on one exact line. The quote is
    # escaped, so the script cannot break out of the string literal.
    assert f'const wanted = {json.dumps(hostile)};' in script
    assert 'const wanted = "' + hostile + '"' not in script
    assert script.count("const wanted =") == 1


def test_window_script_carries_its_operation_and_needle():
    script = desktop_actions._windows_script("close", "Pentagon")
    assert 'const operation = "close";' in script
    assert 'const wanted = "Pentagon";' in script
    assert "__END__" in script


def test_power_only_knows_four_verbs(monkeypatch):
    """The real systemctl calls must never run, so argv is captured instead."""
    seen: list[list[str]] = []

    async def fake_run(argv, timeout=20.0):
        seen.append(argv)
        return 0, "", ""

    monkeypatch.setattr(desktop_actions, "_run_argv", fake_run)
    for good in ("suspend", "hibernate", "shutdown", "reboot"):
        assert asyncio.run(desktop_actions._action_power({"target": good})).ok
    assert seen == [
        ["systemctl", "suspend"],
        ["systemctl", "hibernate"],
        ["systemctl", "poweroff"],
        ["systemctl", "reboot"],
    ]
    for bad in ("", "explode", "reboot --force", "shutdown; rm -rf /"):
        assert asyncio.run(desktop_actions._action_power({"target": bad})).exit_code == 1


def test_lock_screen_uses_the_screensaver_interface(monkeypatch):
    seen: list[list[str]] = []

    async def fake_run(argv, timeout=20.0):
        seen.append(argv)
        return 0, "", ""

    monkeypatch.setattr(desktop_actions, "_run_argv", fake_run)
    assert asyncio.run(desktop_actions._action_lock({})).ok
    assert seen[0][:2] == ["qdbus6", "org.freedesktop.ScreenSaver"]


def test_volume_rejects_an_unknown_action(monkeypatch):
    monkeypatch.setattr(desktop_actions.shutil, "which", lambda name: "/usr/bin/pactl")
    assert asyncio.run(
        desktop_actions._action_volume({"target": "set-my-vol-to-9000"})
    ).exit_code == 1


def test_dark_mode_rejects_an_unknown_action():
    assert asyncio.run(desktop_actions._action_dark_mode({"target": "sideways"})).exit_code == 1


def test_media_rejects_an_unknown_action():
    assert asyncio.run(desktop_actions._action_media({"target": "reformat"})).exit_code == 1


def test_open_path_rejects_a_remote_url():
    assert asyncio.run(
        desktop_actions._action_open_path({"target": "https://example.com"})
    ).exit_code == 1


def test_impossible_argument_never_reaches_the_user(monkeypatch):
    """A card on screen must always describe something that could actually happen."""
    for action, bad_target in (
        ("open_url", "file:///etc/passwd"),
        ("open_app", "firefox; rm -rf ~"),
        ("power", "explode"),
        ("media", "reformat"),
        ("dark_mode", "sideways"),
        ("volume", "set-my-vol-to-9000"),
    ):
        calls = _stub(monkeypatch, action)
        # It returns without ever awaiting a decision, so this completes at once.
        result = asyncio.run(
            desktop_actions.run_desktop_action(
                action, {"target": bad_target}, conversation_id="c1", user_id="u1"
            )
        )
        assert result.exit_code == 1, action
        assert calls == [], action
        # Nothing was ever raised for approval, so the user was not bothered.
        assert desktop_actions.REGISTRY._requests == {}, action
        assert result.stderr, action


def test_valid_arguments_still_go_through_the_gate(monkeypatch):
    """The pre-check must not swallow a legitimate request."""
    calls = _stub(monkeypatch, "open_app")

    async def _scenario():
        task = asyncio.create_task(
            desktop_actions.run_desktop_action(
                "open_app", {"target": "firefox"}, conversation_id="c1", user_id="u1"
            )
        )
        await _answer_when_raised("u1", True)
        return await task

    result = asyncio.run(_scenario())
    assert calls == [{"target": "firefox"}]
    assert result.ok


# --------------------------------------------------------------------------
# The graph only offers the tool when it is switched on
# --------------------------------------------------------------------------


class _ScriptedModel:
    """Mirrors the shell suite's model: records what tools it was bound."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages, config=None):
        return self.responses.pop(0) if self.responses else AIMessage(content="done")


def _bound_tool_names(monkeypatch, *, enabled, command_tool_enabled=True):
    model = _ScriptedModel([AIMessage(content="no tools here")])
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_a, **_k: model)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: False)
    graph = chat_graph.build_chat_graph(
        "unused-key", "test-model", user_id="test-user", use_web_search=False,
        command_tool_enabled=command_tool_enabled,
    )
    state = chat_graph.initial_chat_state(
        user_id="test-user",
        conversation_id="test-conversation",
        message="hello",
        history=[],
        use_web_search=False,
        command_tool_enabled=command_tool_enabled,
    )
    asyncio.run(graph.ainvoke(state))
    return [
        tool.get("function", {}).get("name")
        if isinstance(tool, dict) else getattr(tool, "name", None)
        for tool in (model.bound_tools or [])
    ]


def test_desktop_tool_is_absent_when_the_server_switch_is_off(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "command_tool_enabled", True)
    monkeypatch.setattr(settings, "desktop_actions_enabled", False)
    bound = _bound_tool_names(monkeypatch, enabled=True)
    assert "run_shell_command" in bound
    assert "run_desktop_action" not in bound


def test_desktop_tool_appears_when_both_switches_are_on(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "command_tool_enabled", True)
    monkeypatch.setattr(settings, "desktop_actions_enabled", True)
    bound = _bound_tool_names(monkeypatch, enabled=True)
    assert "run_shell_command" in bound
    assert "run_desktop_action" in bound


def test_desktop_tool_needs_the_user_command_flag_too(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "command_tool_enabled", True)
    monkeypatch.setattr(settings, "desktop_actions_enabled", True)
    bound = _bound_tool_names(
        monkeypatch, enabled=True, command_tool_enabled=False
    )
    assert bound == []


def test_desktop_tool_call_is_dispatched_not_dropped(monkeypatch):
    """A desktop tool call reaches its handler instead of being ignored."""
    from app.config import settings

    monkeypatch.setattr(settings, "command_tool_enabled", True)
    monkeypatch.setattr(settings, "desktop_actions_enabled", True)
    calls: list[dict] = []

    async def handler(args):
        calls.append(dict(args))
        return _result("8 window(s)")

    entry = desktop_actions.ACTIONS["list_windows"]
    monkeypatch.setitem(
        desktop_actions.ACTIONS,
        "list_windows",
        dataclasses.replace(entry, handler=handler),
    )

    model = _ScriptedModel([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "run_desktop_action",
                "args": {"action": "list_windows", "reason": "to answer"},
                "id": "call_1",
            }],
        ),
        AIMessage(content="You have 8 windows open."),
    ])
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_a, **_k: model)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: False)
    graph = chat_graph.build_chat_graph(
        "unused-key", "test-model", user_id="test-user", use_web_search=False,
        command_tool_enabled=True,
    )
    state = chat_graph.initial_chat_state(
        user_id="test-user",
        conversation_id="test-conversation",
        message="what is open?",
        history=[],
        use_web_search=False,
        command_tool_enabled=True,
    )
    result = asyncio.run(graph.ainvoke(state))

    assert calls == [{"action": "list_windows", "reason": "to answer"}]
    assert result["answer"] == "You have 8 windows open."
    assert result["command_runs"][0]["stdout"] == "8 window(s)"

# --------------------------------------------------------------------------
# "open vscode" answered with per-OS instructions instead of opening anything
# --------------------------------------------------------------------------


def _write_desktop(directory, name, exec_line, app_name):
    path = directory / name
    path.write_text(
        "[Desktop Entry]\n"
        f"Type=Application\n"
        f"Name={app_name}\n"
        f"Exec={exec_line}\n",
        encoding="utf-8",
    )


@pytest.fixture
def desktop_dir(tmp_path):
    """A directory of desktop entries, so the resolver is not tested against
    whatever happens to be installed on the machine running the tests."""
    desktop_actions._DESKTOP_CACHE.clear()
    yield tmp_path
    desktop_actions._DESKTOP_CACHE.clear()


@pytest.mark.parametrize(
    "asked,expected_id",
    [
        ("code", "code"),
        ("vscode", "code"),  # the report: "vscode" reaches code.desktop
        ("VS Code", "code"),
        ("Visual Studio Code", "code"),
        ("kcalc", "kcalc"),
        ("KDE Calc", "kcalc"),
    ],
)
def test_app_names_resolve_to_the_installed_launcher(desktop_dir, asked, expected_id):
    _write_desktop(desktop_dir, "code.desktop", "/usr/bin/code %U", "Visual Studio Code")
    _write_desktop(desktop_dir, "kcalc.desktop", "kcalc %U", "KDE Calc")

    candidates = desktop_actions._resolve_app(asked, dirs=(str(desktop_dir),))

    assert candidates, f"{asked!r} resolved to nothing"
    assert candidates[0].argv[-1] == expected_id
    assert candidates[0].binary == os.path.basename(expected_id)


def test_a_name_that_matches_nothing_resolves_to_nothing(desktop_dir):
    _write_desktop(desktop_dir, "code.desktop", "/usr/bin/code %U", "Visual Studio Code")

    assert desktop_actions._resolve_app("aardvark-flavoured-editor", dirs=(str(desktop_dir),)) == []


def test_hidden_and_non_application_entries_are_ignored(desktop_dir):
    (desktop_dir / "hidden.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Secret\nExec=/usr/bin/secret\n"
        "NoDisplay=true\n",
        encoding="utf-8",
    )
    (desktop_dir / "link.desktop").write_text(
        "[Desktop Entry]\nType=Link\nName=Website\nURL=https://example.com\n",
        encoding="utf-8",
    )
    _write_desktop(desktop_dir, "code.desktop", "/usr/bin/code %U", "Visual Studio Code")

    ids = [entry.desktop_id for entry in desktop_actions._desktop_entries((str(desktop_dir),))]

    assert ids == ["code"]


def test_open_app_reports_failure_instead_of_claiming_success(desktop_dir, monkeypatch):
    """The original defect: the launcher exited 0 and nothing opened, and the
    action still answered "Launched." """
    _write_desktop(desktop_dir, "kcalc.desktop", "kcalc %U", "KDE Calc")
    monkeypatch.setattr(desktop_actions, "_DESKTOP_DIRS", (str(desktop_dir),))
    monkeypatch.setattr(desktop_actions, "_resolve_windows", _no_windows)
    monkeypatch.setattr(desktop_actions, "_processes_named", lambda _binary: set())
    monkeypatch.setattr(desktop_actions, "_spawn_detached", lambda _argv: None)
    monkeypatch.setattr(desktop_actions, "_window_keys", _empty_windows)

    result = asyncio.run(desktop_actions._action_open_app({"target": "kcalc"}))

    assert result.exit_code == 1
    assert "Launched" not in result.stdout
    assert "kcalc" in result.stderr


def test_open_app_reports_success_only_once_a_process_exists(desktop_dir, monkeypatch):
    _write_desktop(desktop_dir, "kcalc.desktop", "kcalc %U", "KDE Calc")
    monkeypatch.setattr(desktop_actions, "_DESKTOP_DIRS", (str(desktop_dir),))
    monkeypatch.setattr(desktop_actions, "_resolve_windows", _no_windows)
    monkeypatch.setattr(desktop_actions, "_window_keys", _empty_windows)
    started: list[list[str]] = []

    def fake_spawn(argv):
        started.append(argv)

    monkeypatch.setattr(desktop_actions, "_spawn_detached", fake_spawn)
    # Nothing is running before the launch; the process shows up during the wait.
    fake_processes = [set(), {4242}]
    monkeypatch.setattr(desktop_actions, "_processes_named", lambda _binary: fake_processes.pop(0))

    result = asyncio.run(desktop_actions._action_open_app({"target": "kcalc"}))

    assert started, "nothing was spawned"
    assert result.exit_code == 0
    assert result.stdout.strip() == "Launched KDE Calc."


def test_open_app_says_so_when_the_app_is_already_running(desktop_dir, monkeypatch):
    _write_desktop(desktop_dir, "kcalc.desktop", "kcalc %U", "KDE Calc")
    monkeypatch.setattr(desktop_actions, "_DESKTOP_DIRS", (str(desktop_dir),))
    monkeypatch.setattr(desktop_actions, "_resolve_windows", _no_windows)
    monkeypatch.setattr(desktop_actions, "_window_keys", _empty_windows)
    monkeypatch.setattr(desktop_actions, "_spawn_detached", lambda _argv: None)
    monkeypatch.setattr(desktop_actions, "_processes_named", lambda _binary: {999})

    result = asyncio.run(desktop_actions._action_open_app({"target": "kcalc"}))

    assert result.exit_code == 0
    assert "already running" in result.stdout


async def _no_windows(_needle=""):
    return []


async def _empty_windows():
    return set()


def _prompt_for(monkeypatch, command_tool_enabled: bool) -> str:
    """Run a real turn with a faked model and return the prompt it was given."""
    seen: dict[str, object] = {}

    class FakeModel:
        def bind_tools(self, _tools):
            return self

        async def ainvoke(self, messages, config=None):
            seen["messages"] = messages
            return AIMessage(content="done")

    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_a, **_k: FakeModel())
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: False)
    graph = chat_graph.build_chat_graph(
        "unused-key", "test-model", user_id="u", use_web_search=False,
        command_tool_enabled=command_tool_enabled,
    )
    state = chat_graph.initial_chat_state(
        user_id="u", conversation_id="c", message="open vscode", history=[],
        use_web_search=False, command_tool_enabled=command_tool_enabled,
    )
    asyncio.run(graph.ainvoke(state))
    prompt = str(seen["messages"][0].content)
    if "history" in seen and len(seen["messages"]) > 1:  # pragma: no cover
        prompt = str(seen["messages"][-1].content)
    return prompt


def test_the_prompt_tells_the_model_to_act_rather_than_explain(monkeypatch):
    """Asked to "open vscode", the model answered with per-OS launch
    instructions. The prompt is what stops that recurring."""
    prompt = _prompt_for(monkeypatch, command_tool_enabled=True)

    assert "Act, do not explain" in prompt
    assert "Never answer with step-by-step instructions" in prompt
    # Tools are on, so the "you cannot act yet" note must stay out of the way.
    assert "no machine tools" not in prompt


def test_without_the_command_tool_the_prompt_says_why_instead_of_explaining(monkeypatch):
    prompt = _prompt_for(monkeypatch, command_tool_enabled=False)

    assert "no machine tools" in prompt
    assert "Settings" in prompt
    assert "Act, do not explain" in prompt
