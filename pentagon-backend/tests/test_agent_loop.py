"""The agent loop, end to end against the mock LLM and the real core tools."""

import asyncio
import json
from uuid import uuid4

import pytest
from langchain_core.messages import ToolMessage

from app.agent.bootstrap import build_registry
from app.agent.loop import TurnRequest, run_turn
from app.agent.registry import ToolRegistry
from app.agent.schemas import Budget, ToolResult, ToolSpec
from app.db.models import Conversation, User
from app.db.session import SessionLocal
from app.evals.mock_llm import MockLLM, ScriptedTurn


@pytest.fixture(autouse=True)
def _loop_rows():
    """The user and conversation rows the trace flush's foreign keys want."""
    with SessionLocal() as db:
        if db.get(User, "loop-test") is None:
            db.add(User(id="loop-test"))
        if db.get(Conversation, "conv-test") is None:
            db.add(Conversation(id="conv-test", user_id="loop-test", title="loop"))
        db.commit()
    yield


def _request(**overrides) -> TurnRequest:
    fields = {
        "user_id": "loop-test",
        "conversation_id": "conv-test",
        "turn_id": str(uuid4()),
        "permission_level": 2,
        "user_message": "What time is it?",
        "system_prompt": "You are Pentagon.",
    }
    fields.update(overrides)
    return TurnRequest(**fields)


def _collect(registry, model, request, **kwargs):
    async def run():
        return [
            event
            async for event in run_turn(registry, model, request, **kwargs)
        ]

    return asyncio.run(run())


def _names(events):
    return [event.name for event in events]


def _payloads(events, name):
    return [event.payload for event in events if event.name == name]


def test_plain_answer_streams_tokens_and_ends_done():
    registry = build_registry()
    model = MockLLM([ScriptedTurn(text="It is Tuesday, and 2+2 is 4.")])

    events = _collect(registry, model, _request())

    streamed = "".join(p["content"] for p in _payloads(events, "token"))
    assert streamed == "It is Tuesday, and 2+2 is 4."
    assert _names(events)[-1] == "done"
    done = _payloads(events, "done")[0]
    assert done["llm_calls"] == 1
    assert done["tool_calls"] == 0


def test_single_tool_round_trip_executes_and_answers():
    registry = build_registry()
    model = MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {"name": "calculator", "args": {"expression": "6*7"}, "id": "call_1"},
                )
            ),
            ScriptedTurn(text="Six times seven is 42."),
        ]
    )

    events = _collect(registry, model, _request(user_message="what is 6*7"))

    starts = _payloads(events, "tool_start")
    results = _payloads(events, "tool_result")
    assert starts == [{"tool": "calculator", "id": "call_1"}]
    assert results[0]["status"] == "ok"
    assert results[0]["ok"] is True
    assert _names(events)[-1] == "done"
    assert "".join(p["content"] for p in _payloads(events, "token")).endswith("42.")

    # The transcript the second model call saw: assistant tool call, then the
    # tool message carrying the envelope with the computed value.
    second_prompt = model.prompts[1]
    tool_messages = [m for m in second_prompt if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call_1"
    envelope = json.loads(tool_messages[0].content)
    assert envelope["ok"] is True
    assert envelope["data"]["value"] == 42


def test_streamed_arguments_are_reassembled_from_fragments():
    """The mock fragments args into 4-char deltas; exact execution proves assembly."""
    registry = build_registry()
    model = MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {
                        "name": "calculator",
                        "args": {"expression": "(1 + 0.07) ** 30 * 1500"},
                        "id": "call_9",
                    },
                )
            ),
            ScriptedTurn(text="done"),
        ]
    )

    events = _collect(registry, model, _request())

    result = _payloads(events, "tool_result")[0]
    assert result["status"] == "ok"
    # A reassembly bug would have changed the number; compare against the
    # same expression evaluated locally.
    second_prompt = model.prompts[1]
    envelope = json.loads(
        next(m for m in second_prompt if isinstance(m, ToolMessage)).content
    )
    assert envelope["data"]["value"] == (1 + 0.07) ** 30 * 1500


def test_unknown_tool_gets_corrective_result_and_the_turn_recovers():
    registry = build_registry()
    model = MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {"name": "get_time_now", "args": {}, "id": "call_bad"},
                    {"name": "calculator", "args": {"expression": "2+2"}, "id": "call_ok"},
                )
            ),
            ScriptedTurn(text="Answered anyway."),
        ]
    )

    events = _collect(registry, model, _request())

    results = _payloads(events, "tool_result")
    assert results[0]["status"] == "error"
    assert results[1]["status"] == "ok"
    bad = json.loads(
        next(m for m in model.prompts[1] if isinstance(m, ToolMessage)).content
    )
    assert bad["ok"] is False
    assert bad["error"]["code"] == "NOT_FOUND"
    assert "calculator" in bad["error"]["message"]
    assert _names(events)[-1] == "done"


def test_duplicate_call_is_reused_not_executed():
    registry = build_registry()
    calls = (
        {"name": "calculator", "args": {"expression": "123456 * 654321"}, "id": "c1"},
        {"name": "calculator", "args": {"expression": "123456 * 654321"}, "id": "c2"},
    )
    model = MockLLM(
        [ScriptedTurn(tool_calls=calls), ScriptedTurn(text="Same number twice.")]
    )

    events = _collect(registry, model, _request())

    results = _payloads(events, "tool_result")
    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "reused"
    reused = json.loads(
        next(m for m in model.prompts[1] if isinstance(m, ToolMessage) and m.tool_call_id == "c2").content
    )
    assert "already called" in reused["data"]["note"]
    assert reused["data"]["result"]["value"] == 123456 * 654321
    assert isinstance(reused["data"]["result"], dict)


def test_budget_forces_a_tools_disabled_wrap_up():
    registry = build_registry()
    # The model keeps asking for tools; the budget must cut it off and still
    # get one final prose call with tools disabled.
    loop_calls = ScriptedTurn(
        tool_calls=({"name": "calculator", "args": {"expression": "1+1"}, "id": "c"},)
    )
    model = MockLLM([loop_calls, loop_calls, loop_calls, ScriptedTurn(text="")])

    events = _collect(
        registry,
        model,
        _request(),
        budget=Budget(max_llm_calls=3, max_tool_calls=16, max_seconds=60),
    )

    statuses = [p["message"] for p in _payloads(events, "status")]
    assert any("budget" in s.lower() for s in statuses)
    # The wrap-up ran unbound: only the first two calls ever saw tool schemas.
    assert len(model.bound_tools) == 2
    assert model.calls == 3
    assert _names(events)[-1] == "done"
    done = _payloads(events, "done")[0]
    assert done["llm_calls"] == 3


def test_turn_never_ends_silently_when_the_model_keeps_looping():
    registry = build_registry()
    loop_calls = ScriptedTurn(
        tool_calls=({"name": "calculator", "args": {"expression": "1+1"}, "id": "c"},)
    )
    model = MockLLM([loop_calls, loop_calls, loop_calls, ScriptedTurn(text="")])

    events = _collect(
        registry,
        model,
        _request(),
        budget=Budget(max_llm_calls=3, max_tool_calls=16, max_seconds=60),
    )

    assert _payloads(events, "error"), "a wrap-up with no prose must surface an error"


def test_invalid_arguments_come_back_as_a_corrective_message():
    registry = build_registry()
    model = MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {"name": "calculator", "args": {"expression": "__import__('os')"}, "id": "c1"},
                )
            ),
            ScriptedTurn(text="The calculator only does arithmetic."),
        ]
    )

    _collect(registry, model, _request())

    envelope = json.loads(
        next(m for m in model.prompts[1] if isinstance(m, ToolMessage)).content
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "INVALID_ARGS"
    assert "numeric expression" in envelope["error"]["hint"].lower()


def test_slow_tool_is_cut_off_at_its_timeout():
    registry = ToolRegistry()

    async def slow(args, ctx):
        await asyncio.sleep(5)
        return ToolResult.success("never")

    registry.register(
        ToolSpec(
            name="slow_probe",
            description="A tool that never finishes in time.",
            parameters={"type": "object", "properties": {}},
            timeout_s=1,
        ),
        slow,
    )
    model = MockLLM(
        [
            ScriptedTurn(tool_calls=({"name": "slow_probe", "args": {}, "id": "c1"},)),
            ScriptedTurn(text="It hung, I moved on."),
        ]
    )

    events = _collect(registry, model, _request())

    result = _payloads(events, "tool_result")[0]
    assert result["status"] == "timeout"
    assert result["ok"] is False
    assert _names(events)[-1] == "done"


def test_tool_exception_becomes_an_upstream_envelope():
    registry = ToolRegistry()

    async def broken(args, ctx):
        raise RuntimeError("disk on fire")

    registry.register(
        ToolSpec(
            name="broken_probe",
            description="A tool that raises.",
            parameters={"type": "object", "properties": {}},
        ),
        broken,
    )
    model = MockLLM(
        [
            ScriptedTurn(tool_calls=({"name": "broken_probe", "args": {}, "id": "c1"},)),
            ScriptedTurn(text="Noted."),
        ]
    )

    events = _collect(registry, model, _request())

    result = _payloads(events, "tool_result")[0]
    assert result["status"] == "error"
    envelope = json.loads(
        next(m for m in model.prompts[1] if isinstance(m, ToolMessage)).content
    )
    assert envelope["error"]["code"] == "UPSTREAM"
    assert "disk on fire" in envelope["error"]["message"]
