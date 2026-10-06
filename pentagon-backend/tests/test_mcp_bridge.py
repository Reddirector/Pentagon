"""T10: MCP tools arrive through the bridge -- only from user config.

A fake MCP server (a plain Python script speaking JSONL over stdio) stands
in for the real thing: handshake, paginated tools/list, tools/call, an
always-failing tool, and a slow one. The tests pin the rules: annotation-
mapped tiers, write-by-default for unknown capabilities, honest envelopes
for refusals/timeouts/deserts, exactly-one-restart behaviour, and config
that is malformed in every way still never raises or spawns a wrong command.
"""

import asyncio
import json
import sys

import pytest

from app.agent.bootstrap import build_registry
from app.agent.schemas import ToolContext
from app.config import settings
from app.services import mcp_bridge

# A minimal MCP stdio server: initialize -> tools/list (paginated in two
# pages) -> tools/call. Also answers ping, to prove the bridge replies to
# server-initiated requests instead of deadlocking.
_FAKE_SERVER = r'''
import json, sys, time

def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()

TOOLS = [
    {"name": "echo-text", "description": "Echo the argument back.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                     "required": ["text"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "boom", "description": "Always fails.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "wipe", "description": "Destructive.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": False, "destructiveHint": True}},
    {"name": "plain", "description": "No annotations at all.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "sleepy", "description": "Sleeps past any sane timeout.",
     "inputSchema": {"type": "object", "properties": {}}},
]

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if "id" not in msg:
        continue  # notification (e.g. notifications/initialized)
    method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": msg["id"],
              "result": {"protocolVersion": msg["params"]["protocolVersion"],
                         "capabilities": {"tools": {}},
                         "serverInfo": {"name": "fake", "version": "1"}}})
    elif method == "ping":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
    elif method == "tools/list":
        cursor = (msg.get("params") or {}).get("cursor")
        if cursor is None:
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "result": {"tools": TOOLS[:3], "nextCursor": "page2"}})
        else:
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "result": {"tools": TOOLS[3:]}})
    elif method == "tools/call":
        params = msg["params"] or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "echo-text":
            if "text" not in args:
                send({"jsonrpc": "2.0", "id": msg["id"],
                      "error": {"code": -32602, "message": "missing text argument"}})
            else:
                send({"jsonrpc": "2.0", "id": msg["id"],
                      "result": {"content": [{"type": "text",
                                              "text": "echo: " + str(args.get("text"))}]}})
        elif name == "boom":
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "result": {"content": [{"type": "text",
                                          "text": "nope: refused by design"}],
                             "isError": True}})
        elif name == "wipe":
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "result": {"content": [{"type": "text", "text": "wiped"}]}})
        elif name == "plain":
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "result": {"content": [{"type": "text", "text": "plain ok"}]}})
        elif name == "sleepy":
            time.sleep(8)
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "result": {"content": [{"type": "text", "text": "woke"}]}})
        else:
            send({"jsonrpc": "2.0", "id": msg["id"],
                  "error": {"code": -32602, "message": "unknown tool"}})
    else:
        send({"jsonrpc": "2.0", "id": msg["id"],
              "error": {"code": -32601, "message": "method not found"}})
'''


def _ctx() -> ToolContext:
    return ToolContext(
        user_id="u", conversation_id="c", turn_id="t", permission_level=2
    )


def _run(coro):
    """Run one scenario and tear the bridge down inside the same loop.

    Sessions are bound to the loop that spawned them (as in production,
    where the lifespan's loop owns them), so cleanup belongs there too.
    """

    async def _with_cleanup():
        try:
            await coro
        finally:
            await mcp_bridge.shutdown()

    asyncio.run(_with_cleanup())


def _configure(tmp_path, monkeypatch, *, tier: str | None = None) -> str:
    script = tmp_path / "fake_mcp.py"
    script.write_text(_FAKE_SERVER, encoding="utf-8")
    entry: dict = {"name": "lab", "command": [sys.executable, str(script)]}
    if tier is not None:
        entry["tier"] = tier
    monkeypatch.setattr(settings, "mcp_servers", json.dumps([entry]))
    return str(script)


def _handlers() -> dict:
    return {spec.name: handler for spec, handler in mcp_bridge.registered_tools()}


# --- config parsing: bad input never raises or spawns ----------------------


def test_parse_servers_accepts_a_valid_entry():
    configs, problems = mcp_bridge.parse_servers(
        json.dumps(
            [
                {
                    "name": "My Files!",
                    "command": ["npx", "-y", "server-filesystem", "/data"],
                    "tier": "read",
                    "env": {"TOKEN": "x"},
                }
            ]
        )
    )
    assert problems == []
    assert configs[0].name == "my_files"  # normalised for the registry
    assert configs[0].tier == "read"
    assert configs[0].command[0] == "npx"
    assert configs[0].env == {"TOKEN": "x"}


def test_parse_servers_survives_every_malformed_shape():
    assert mcp_bridge.parse_servers("not json")[0] == []
    assert mcp_bridge.parse_servers('{"name": "x"}')[1]  # not an array
    configs, problems = mcp_bridge.parse_servers(
        json.dumps(
            [
                {"name": "no-command"},
                {"command": ["ls"]},  # no name
                {"name": "bad-tier", "command": ["ls"], "tier": "mega"},
                {"name": "empty", "command": []},
                42,
                {"name": "ok", "command": ["ls"]},
                {"name": "ok", "command": ["ls"]},  # duplicate
            ]
        )
    )
    assert [c.name for c in configs] == ["bad_tier", "ok"]
    # the bad tier fell back to write, and each skip is reported
    assert configs[0].tier == "write"
    assert len(problems) == 6


def test_registered_tools_is_empty_before_connect():
    # No test configures servers at import time; until connect_all runs the
    # registry must not invent remote tools.
    assert mcp_bridge.BRIDGE._sessions == {} or all(
        not s.tools for s in mcp_bridge.BRIDGE._sessions.values()
    )


# --- the full round trip against the fake server ---------------------------


def test_full_round_trip_against_a_fake_server(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    async def scenario():
        await mcp_bridge.connect_all()
        assert mcp_bridge.problems() == []
        # tools/list came back paginated: all five arrived
        handlers = _handlers()
        assert set(handlers) == {
            "mcp_lab_echo_text",
            "mcp_lab_boom",
            "mcp_lab_wipe",
            "mcp_lab_plain",
            "mcp_lab_sleepy",
        }
        # tiers: annotations win, unknown stays approval-gated at write
        tiers = {
            spec.name: spec.tier
            for spec, _ in mcp_bridge.registered_tools()
        }
        assert tiers["mcp_lab_echo_text"] == "read"
        assert tiers["mcp_lab_wipe"] == "destructive"
        assert tiers["mcp_lab_plain"] == "write"
        # every bridged spec satisfies the registry's own validation
        for spec, _ in mcp_bridge.registered_tools():
            assert spec.validation_errors() == []
            assert spec.untrusted is True
            assert spec.parallel_safe is False
        # a read call round-trips through the envelope
        result = await handlers["mcp_lab_echo_text"]({"text": "hi"}, _ctx())
        assert result.ok is True
        assert result.data["content"] == "echo: hi"
        assert result.data["server"] == "lab"
        # a server-side isError becomes an honest failure...
        result = await handlers["mcp_lab_boom"]({}, _ctx())
        assert result.ok is False
        assert result.error.code == "UPSTREAM"
        assert "refused by design" in result.error.message
        # ...and so does a JSON-RPC error (the server rejected the call)
        result = await handlers["mcp_lab_echo_text"]({}, _ctx())
        assert result.ok is False and result.error.code == "UPSTREAM"
        assert "missing text argument" in result.error.message
        # a whole unknown-tool error surfaces as RemoteError at the session
        session = mcp_bridge.session("lab")
        with pytest.raises(mcp_bridge.RemoteError):
            await session.call_tool("nope", {})

    _run(scenario())


def test_registry_picks_up_connected_bridged_tools(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    async def scenario():
        await mcp_bridge.connect_all()
        registry = build_registry()
        assert "mcp_lab_echo_text" in registry.names()
        assert registry.get("mcp_lab_plain").spec.tier == "write"

    _run(scenario())


def test_configured_tier_applies_when_annotations_are_absent(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, tier="read")

    async def scenario():
        await mcp_bridge.connect_all()
        tiers = {
            spec.name: spec.tier for spec, _ in mcp_bridge.registered_tools()
        }
        assert tiers["mcp_lab_plain"] == "read"
        # An explicit destructiveHint still escalates past a read config.
        assert tiers["mcp_lab_wipe"] == "destructive"

    _run(scenario())


def test_dead_server_is_restarted_by_its_next_call(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)

    async def scenario():
        await mcp_bridge.connect_all()
        handlers = _handlers()
        session = mcp_bridge.session("lab")
        assert session is not None and session.alive
        session._proc.kill()
        await session._proc.wait()
        assert not session.alive
        # The very next call re-spawns and succeeds instead of erroring.
        result = await handlers["mcp_lab_echo_text"]({"text": "back"}, _ctx())
        assert result.ok is True
        assert result.data["content"] == "echo: back"
        assert session.alive

    _run(scenario())


def test_timeout_is_an_honest_envelope_and_drops_the_server(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(mcp_bridge, "_CALL_TIMEOUT_SECONDS", 1.0)

    async def scenario():
        await mcp_bridge.connect_all()
        handlers = _handlers()
        session = mcp_bridge.session("lab")
        result = await handlers["mcp_lab_sleepy"]({}, _ctx())
        assert result.ok is False
        assert result.error.code == "TIMEOUT"
        assert not session.alive  # wedged session dropped, not kept

    _run(scenario())


def test_parallel_calls_into_one_server_serialize_without_corruption(
    tmp_path, monkeypatch
):
    _configure(tmp_path, monkeypatch)

    async def scenario():
        await mcp_bridge.connect_all()
        handlers = _handlers()
        results = await asyncio.gather(
            handlers["mcp_lab_echo_text"]({"text": "a"}, _ctx()),
            handlers["mcp_lab_echo_text"]({"text": "b"}, _ctx()),
        )
        assert [r.ok for r in results] == [True, True]
        contents = sorted(r.data["content"] for r in results)
        assert contents == ["echo: a", "echo: b"]

    _run(scenario())


def test_a_broken_command_is_a_problem_not_an_explosion(monkeypatch):
    monkeypatch.setattr(
        settings,
        "mcp_servers",
        json.dumps(
            [{"name": "ghost", "command": ["/definitely/not/a/binary"]}]
        ),
    )

    async def scenario():
        await mcp_bridge.connect_all()
        assert any("ghost" in problem for problem in mcp_bridge.problems())
        assert mcp_bridge.registered_tools() == []

    _run(scenario())


def test_derive_tier_maps_annotations_and_defaults():
    assert mcp_bridge.derive_tier({"readOnlyHint": True}, "write") == "read"
    assert mcp_bridge.derive_tier({"destructiveHint": True}, "read") == "destructive"
    assert mcp_bridge.derive_tier({}, "write") == "write"
    assert mcp_bridge.derive_tier({}, "read") == "read"
    # readOnlyHint is the only way down: false+non-destructive still gated.
    assert (
        mcp_bridge.derive_tier({"readOnlyHint": False, "destructiveHint": False}, "write")
        == "write"
    )


def test_safe_tool_name_is_registry_legal():
    name = mcp_bridge.safe_tool_name("Lab Server!", "read-file")
    assert name == "mcp_lab_server_read_file"
    from app.agent.schemas import ToolSpec

    probe = ToolSpec(
        name=name,
        description="probe",
        parameters={"type": "object", "properties": {}},
    )
    assert probe.validation_errors() == []
