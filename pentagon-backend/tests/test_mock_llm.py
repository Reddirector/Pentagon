"""The mock LLM must fragment like the real stream, or the tests prove nothing."""

import asyncio
import json

import pytest

from app.evals.mock_llm import MockLLM, ScriptedTurn


def test_ainvoke_plays_turns_in_order_and_records_prompts():
    llm = MockLLM(
        [
            ScriptedTurn(tool_calls=({"name": "calculator", "args": {"expression": "2+2"}, "id": "call_1"},)),
            ScriptedTurn(text="It is 4."),
        ]
    )

    first = asyncio.run(llm.ainvoke(["hello"]))
    second = asyncio.run(llm.ainvoke(["hello", first]))

    assert first.tool_calls[0]["name"] == "calculator"
    assert first.tool_calls[0]["args"] == {"expression": "2+2"}
    assert second.content == "It is 4."
    assert llm.calls == 2
    assert len(llm.prompts[1]) == 2


def test_bind_tools_records_what_the_model_was_offered():
    llm = MockLLM([ScriptedTurn(text="ok")])
    bound = llm.bind_tools([{"type": "function", "function": {"name": "calculator"}}])
    assert bound is llm
    assert llm.bound_tools[0][0]["function"]["name"] == "calculator"


def test_error_turn_raises_the_scripted_exception():
    boom = RuntimeError("429")
    llm = MockLLM([ScriptedTurn(error=boom)])
    with pytest.raises(RuntimeError, match="429"):
        asyncio.run(llm.ainvoke([]))


def test_out_of_script_answers_instead_of_spinning():
    llm = MockLLM([])
    result = asyncio.run(llm.ainvoke([]))
    assert result.content == ""
    assert result.tool_calls == []


def _collect_stream(llm: MockLLM, messages):
    async def run():
        return [chunk async for chunk in llm.astream(messages)]

    return asyncio.run(run())


def test_astream_fragments_text_but_reassembles_exactly():
    llm = MockLLM([ScriptedTurn(text="The answer is 4, exactly.")])
    chunks = _collect_stream(llm, [])

    assert len(chunks) > 3, "the stream should arrive in several pieces"
    assert "".join(chunk.content for chunk in chunks) == "The answer is 4, exactly."


def test_astream_tool_call_deltas_reassemble_per_index():
    """The fragmentation is the point: arguments arrive in pieces keyed by index."""
    llm = MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {"name": "web_search", "args": {"query": "pune weather today"}, "id": "call_7"},
                    {"name": "calculator", "args": {"expression": "12*9"}, "id": "call_8"},
                )
            )
        ]
    )
    chunks = _collect_stream(llm, [])

    by_index: dict[int, dict] = {}
    for chunk in chunks:
        for delta in chunk.tool_call_chunks:
            entry = by_index.setdefault(delta["index"], {"name": None, "id": None, "args": ""})
            if delta.get("name"):
                entry["name"] = delta["name"]
            if delta.get("id"):
                entry["id"] = delta["id"]
            entry["args"] += delta.get("args") or ""

    assert by_index[0]["name"] == "web_search"
    assert by_index[0]["id"] == "call_7"
    assert json.loads(by_index[0]["args"]) == {"query": "pune weather today"}
    assert by_index[1]["name"] == "calculator"
    assert json.loads(by_index[1]["args"]) == {"expression": "12*9"}
