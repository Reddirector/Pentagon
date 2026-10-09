"""Context management: a 200 KB result never enters the context whole."""

import asyncio
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.bootstrap import build_registry
from app.agent.context import (
    ContextBudget,
    ScratchStore,
    ToolScratchNote,
    _STORE_TTL_SECONDS,
    compact_history,
    estimate_tokens,
)
from app.agent.loop import TurnRequest, run_turn
from app.agent.schemas import Budget
from app.db.models import Conversation, User
from app.db.session import SessionLocal
from app.evals.mock_llm import MockLLM, ScriptedTurn


def test_estimate_tokens_is_conservative():
    assert estimate_tokens("") == 0
    assert estimate_tokens("word " * 100) >= 100 // 2
    assert estimate_tokens("x" * 400) == 100


def test_small_results_skip_the_store():
    store = ScratchStore()
    assert store.store("web_search", "short text") is None


def test_big_result_is_stored_paged_and_searched():
    store = ScratchStore()
    big = ("line one\n" * 2000) + "the needle is here\n" + ("filler\n" * 2000)
    stored = store.store("fetch_url", big)

    assert stored is not None
    page = store.page(stored.handle, offset=0, limit=100)
    assert len(page["text"]) == 100
    assert page["total_chars"] == len(big)
    assert page["has_more"] is True

    found = store.search(stored.handle, "needle")
    assert found["matches"] and "needle" in found["matches"][0]["text"]


def test_expired_handles_are_cleaned_on_read():
    store = ScratchStore()
    stored = store.store("fetch_url", "x" * 10_000)
    # Force-expire relative to the process clock. Rewinding to 0.0 only counts
    # as expired once the host has been up longer than the TTL, which made this
    # test pass or fail with the machine's uptime.
    object.__setattr__(
        stored, "created_at", time.monotonic() - _STORE_TTL_SECONDS - 1
    )
    assert store.page(stored.handle) is None


def test_scratch_note_points_at_the_handle():
    store = ScratchStore()
    stored = store.store("web_search", "A" * 20_000)
    note = ToolScratchNote("web_search", "A" * ScratchStore.head_chars(), stored).as_content()
    assert "read_result" in note
    assert stored.handle in note
    assert "20,000" in note or "20000" in note


def test_loop_truncates_a_giant_tool_result_to_head_plus_handle():
    with SessionLocal() as db:
        if db.get(User, "loop-test") is None:
            db.add(User(id="loop-test"))
        if db.get(Conversation, "conv-test") is None:
            db.add(Conversation(id="conv-test", user_id="loop-test", title="loop"))
        db.commit()

    registry = build_registry()
    giant = "Z" * 200_000

    async def fake_search(query):
        return [{"title": "Giant page", "url": "https://example/giant", "content": giant}]

    from unittest.mock import patch

    model = MockLLM(
        [
            ScriptedTurn(
                tool_calls=({"name": "web_search", "args": {"query": "giant"}, "id": "c1"},)
            ),
            ScriptedTurn(text="The page is huge; I read the head."),
        ]
    )

    request = TurnRequest(
        user_id="loop-test",
        conversation_id="conv-test",
        turn_id="t-giant",
        permission_level=2,
        user_message="read the giant page",
        system_prompt="You are Pentagon.",
    )

    async def collect():
        return [
            event
            async for event in run_turn(registry, model, request, budget=Budget(max_llm_calls=5))
        ]

    with patch("app.tools.web_search.search_web", fake_search):
        events = asyncio.run(collect())

    from langchain_core.messages import ToolMessage

    tool_messages = [
        m for m in model.prompts[1] if isinstance(m, ToolMessage)
    ]
    assert len(tool_messages) == 1
    content = tool_messages[0].content
    assert len(content) < 20_000, "the giant result must not enter the context whole"
    assert "read_result" in content
    assert "res_" in content
    done = [e for e in events if e.name == "done"][0]
    assert done.payload["tool_calls"] == 1


def test_compact_history_masks_old_tool_results():
    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="q1"),
        AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "x"}, "id": "c1"}]),
        ToolMessage(content="W" * 30_000, tool_call_id="c1"),
        HumanMessage(content="q2"),
        AIMessage(content="a2"),
        HumanMessage(content="q3"),
        AIMessage(content="a3"),
        HumanMessage(content="q4"),
        AIMessage(content="a4"),
        HumanMessage(content="q5"),
        AIMessage(content="a5"),
        HumanMessage(content="q6"),
        AIMessage(content="a6"),
        HumanMessage(content="q7 - the actual current question"),
    ]
    compacted = compact_history(messages, keep_recent=6)
    assert compacted[0].content == "system"
    stubs = [m for m in compacted if isinstance(m, ToolMessage)]
    assert len(stubs) == 1
    assert len(stubs[0].content) < 200
    assert "omitted" in stubs[0].content
    assert compacted[-1].content == "q7 - the actual current question"


def test_compact_history_respects_a_token_ceiling():
    messages = [SystemMessage(content="system")]
    for i in range(30):
        messages.append(HumanMessage(content="Q" * 400))
        messages.append(AIMessage(content="A" * 400))
    compacted = compact_history(messages, keep_recent=6, max_history_tokens=2_000)
    total = sum(len(str(m.content)) for m in compacted[1:])
    assert total / 4 <= 2_000 + 500, "dropping oldest turns must bring history under budget"


def test_context_budget_shares():
    messages = [
        SystemMessage(content="s" * 400),
        HumanMessage(content="h" * 400),
        ToolMessage(content="t" * 400, tool_call_id="c"),
    ]
    counts = ContextBudget(max_context=10_000).counts(messages)
    assert counts["system"] == 100
    assert counts["history"] == 100
    assert counts["tool"] == 100
    assert counts["budget_total"] == 9_000
