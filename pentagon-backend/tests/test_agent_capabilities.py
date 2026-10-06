"""Capability probing and the prompted fallback, both against the mock LLM."""

import pytest

from app.agent.capabilities import ProbeResult, ensure_probed, _probe_async
from app.agent.prompted_tools import parse_tool_calls, prompt_for_tools
from app.db.models import ModelCapabilities
from app.db.session import SessionLocal
from app.evals.mock_llm import MockLLM, ScriptedTurn


@pytest.fixture(autouse=True)
def _clean_capabilities():
    with SessionLocal() as db:
        for row in db.query(ModelCapabilities).all():
            db.delete(row)
        db.commit()
    yield


def _time_call_model() -> MockLLM:
    return MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {"name": "get_current_time", "args": {"timezone": "UTC"}, "id": "p1"},
                )
            ),
            ScriptedTurn(
                tool_calls=(
                    {"name": "get_current_time", "args": {"timezone": "UTC"}, "id": "p2"},
                    {"name": "calculator", "args": {"expression": "12*9"}, "id": "p3"},
                )
            ),
        ]
    )


def test_probe_scores_native_and_parallel_from_the_mock():
    import asyncio

    model = _time_call_model()
    result = asyncio.run(_probe_async(model))

    assert result["native_tools"] is True
    assert result["parallel_tools"] is True
    assert result.badge == "Strong"
    assert model.calls == 2


def test_probe_downgrades_when_parallel_calls_are_absent():
    import asyncio

    model = MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {"name": "get_current_time", "args": {}, "id": "p1"},
                )
            ),
            # Asked for two things, answers with one call: not parallel.
            ScriptedTurn(
                tool_calls=(
                    {"name": "get_current_time", "args": {}, "id": "p2"},
                )
            ),
        ]
    )
    result = asyncio.run(_probe_async(model))
    assert result.badge == "Basic"


def test_probe_fails_a_model_that_never_calls_tools():
    import asyncio

    model = MockLLM([ScriptedTurn(text="I think it is 3 pm.")])
    result = asyncio.run(_probe_async(model))
    assert result.badge == "Prompted-only"


def test_probe_result_is_cached_and_reused():
    model = _time_call_model()
    first = ensure_probed(model, "mock/model-a")
    again = ensure_probed(model, "mock/model-a")

    assert again == first
    assert model.calls == 2, "the second lookup must be served from the cache"

    with SessionLocal() as db:
        row = db.get(ModelCapabilities, "mock/model-a")
    assert row is not None and row.native_tools is True


def test_badge_levels():
    assert ProbeResult(native_tools=True, parallel_tools=True).badge == "Strong"
    assert ProbeResult(native_tools=True, parallel_tools=False).badge == "Basic"
    assert ProbeResult(native_tools=False, parallel_tools=True).badge == "Prompted-only"


# --- the prompted protocol ---------------------------------------------------

def test_prompt_lists_tools_compactly():
    text = prompt_for_tools([])
    assert "tool_call" in text
    assert "Never invent a tool result" in text


def test_parser_extracts_single_and_multiple_calls():
    reply = (
        'Let me check both.\n'
        '<tool_call>{"name": "get_current_time", "arguments": {"timezone": "UTC"}}</tool_call>\n'
        '<tool_call>{"name": "calculator", "arguments": {"expression": "1+1"}}</tool_call>'
    )
    calls, problems = parse_tool_calls(reply)
    assert problems == []
    assert [c["name"] for c in calls] == ["get_current_time", "calculator"]
    assert calls[0]["args"] == {"timezone": "UTC"}


def test_parser_reports_malformed_blocks_but_keeps_good_ones():
    reply = (
        '<tool_call>{"name": "calculator", "arguments": {"expression": 1+1}}</tool_call>\n'
        '<tool_call>{"name": "calculator", "arguments": {"expression": "1+1"}}</tool_call>'
    )
    calls, problems = parse_tool_calls(reply)
    assert len(calls) == 1 and calls[0]["args"] == {"expression": "1+1"}
    assert len(problems) == 1 and "calculator" in problems[0]


def test_parser_ignores_prose_outside_blocks():
    calls, problems = parse_tool_calls("Here is my plan: run the thing.")
    assert calls == [] and problems == []


def test_parser_handles_fenced_and_trailing_comma_json():
    reply = '<tool_call>```json\n{"name": "calculator", "arguments": {"expression": "2+2",},}\n```</tool_call>'
    calls, problems = parse_tool_calls(reply)
    assert problems == []
    assert calls[0]["args"]["expression"] == "2+2"
