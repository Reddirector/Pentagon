"""T12: grounding verification, capability routing, and the system prompt.

Three surfaces, one theme -- the turn is checked rather than assumed:
``verify_answer``'s deterministic rules, the loop's repair pass (scripted
model, budget-respecting), the native-vs-prompted routing driven by a
seeded capability probe row, and the prompt file the loop opens with when
the caller brings none.
"""

import asyncio

import pytest
from langchain_core.messages import ToolMessage

from app.agent import capabilities, prompted_tools, system_prompt, verify
from app.agent.bootstrap import build_registry
from app.agent.loop import TurnRequest, run_turn
from app.agent.schemas import Budget, ToolContext, ToolResult
from app.db.models import Conversation, ModelCapabilities, User
from app.db.session import SessionLocal
from app.evals.mock_llm import MockLLM, ScriptedTurn

SOURCES = [
    {"url": "https://example.com/report", "title": "Annual report"},
    {"url": "https://other.org/notes", "title": "Notes"},
]


@pytest.fixture(autouse=True)
def _loop_rows():
    """Trace-flush FKs plus a clean capability cache per test."""
    with SessionLocal() as db:
        if db.get(User, "loop-test") is None:
            db.add(User(id="loop-test"))
        if db.get(Conversation, "conv-test") is None:
            db.add(Conversation(id="conv-test", user_id="loop-test", title="loop"))
        db.query(ModelCapabilities).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(ModelCapabilities).delete()
        db.commit()


def _ctx() -> ToolContext:
    return ToolContext(
        user_id="u", conversation_id="c", turn_id="t", permission_level=2
    )


def _request(**overrides) -> TurnRequest:
    fields = {
        "user_id": "loop-test",
        "conversation_id": "conv-test",
        "turn_id": "t-verify",
        "permission_level": 2,
        "user_message": "what does the report say?",
        "system_prompt": "You are Pentagon.",
    }
    fields.update(overrides)
    return TurnRequest(**fields)


async def _collect(registry, model, request, budget=None):
    return [
        event
        async for event in run_turn(
            registry, model, request, budget=budget or Budget(max_llm_calls=6)
        )
    ]


# --- the deterministic rules --------------------------------------------------


def test_verification_passes_for_a_grounded_answer():
    verdict = verify.verify_answer(
        "Growth slowed [1], per the notes [2].", SOURCES
    )
    assert verdict.ok is True
    assert verdict.citations == [1, 2]
    assert verdict.sources == 2


def test_verification_flags_out_of_range_citations_and_foreign_hosts():
    verdict = verify.verify_answer("As shown in [9].", SOURCES)
    assert verdict.ok is False
    assert any("[9]" in problem for problem in verdict.problems)

    verdict = verify.verify_answer("See https://evil.example/bad.", SOURCES)
    assert verdict.ok is False
    assert any("not among the gathered sources" in p for p in verdict.problems)

    verdict = verify.verify_answer("According to reuters.com.", SOURCES)
    assert verdict.ok is False


def test_verification_requires_citations_when_sources_exist():
    verdict = verify.verify_answer("An unsourced claim.", SOURCES)
    assert verdict.ok is False
    assert any("cites none" in problem for problem in verdict.problems)


def test_verification_of_an_empty_answer_fails_cleanly():
    verdict = verify.verify_answer("   ", SOURCES)
    assert verdict.ok is False
    assert "empty" in verdict.problems[0]


def test_gather_sources_walks_any_shape_and_skips_failures():
    good = ToolResult.success(
        {"results": [{"title": "T", "url": "https://a.example/x"}]}
    )
    nested = ToolResult.success(
        {"sources": [{"n": 1, "title": "S", "url": "https://b.example/y"}]}
    )
    failed = ToolResult.failure("UPSTREAM", "search is down")
    rows = verify.gather_sources(
        [("web_search", good), ("deep_research", nested), ("web_search", failed)]
    )
    assert [row["url"] for row in rows] == [
        "https://a.example/x",
        "https://b.example/y",
    ]
    # Duplicates collapse to one source.
    again = verify.gather_sources([("web_search", good), ("fetch_url", good)])
    assert len(again) == 1


def test_repair_rewrites_with_the_budget_and_falls_back_to_the_original():
    model = MockLLM([ScriptedTurn(text="Grounded rewrite [1].")])
    budget = Budget(max_llm_calls=3)
    rewritten = asyncio.run(
        verify.repair(
            model,
            answer="Bad [9].",
            sources=SOURCES,
            verification=verify.verify_answer("Bad [9].", SOURCES),
            budget=budget,
        )
    )
    assert rewritten == "Grounded rewrite [1]."
    assert budget.llm_calls == 1

    # Out of script the model returns empty: the original survives.
    exhausted = MockLLM([])
    original = asyncio.run(
        verify.repair(
            exhausted,
            answer="Original.",
            sources=SOURCES,
            verification=verify.verify_answer("Bad [9].", SOURCES),
            budget=Budget(max_llm_calls=3),
        )
    )
    assert original == "Original."


# --- the loop's verification pass ---------------------------------------------


def test_loop_verifies_a_grounded_answer_and_reports_on_done():
    registry = build_registry()
    model = MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {"name": "web_search", "args": {"query": "report"}, "id": "c1"},
                )
            ),
            # Cites a source that was never gathered: triggers repair.
            ScriptedTurn(text="The report says everything [7]."),
            ScriptedTurn(text="The report cites growth [1]."),
        ]
    )

    async def fake_search(query):
        return [{"title": "Annual report", "url": "https://example.com/report", "content": "growth"}]

    from unittest.mock import patch

    with patch("app.tools.web_search.search_web", fake_search):
        events = asyncio.run(_collect(registry, model, _request()))

    done = next(event for event in events if event.name == "done")
    verification = done.payload["verification"]
    # The repair pass replaced the answer and the re-check now passes.
    assert verification["ok"] is True
    assert verification["citations"] == [1]
    statuses = [event.payload["message"] for event in events if event.name == "status"]
    assert any("revised to match the sources" in message for message in statuses)


def test_loop_keeps_the_original_when_the_budget_cannot_pay_for_repair():
    registry = build_registry()
    model = MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {"name": "web_search", "args": {"query": "report"}, "id": "c1"},
                )
            ),
            ScriptedTurn(text="Unsourced claim without any citation."),
            # A third call exists but the budget of 2 forbids the repair.
            ScriptedTurn(text="should never be consumed"),
        ]
    )

    async def fake_search(query):
        return [{"title": "T", "url": "https://example.com/a", "content": "x"}]

    from unittest.mock import patch

    with patch("app.tools.web_search.search_web", fake_search):
        events = asyncio.run(
            _collect(
                registry,
                model,
                _request(),
                budget=Budget(max_llm_calls=2),
            )
        )

    done = next(event for event in events if event.name == "done")
    assert done.payload["verification"]["ok"] is False
    # The repair never ran, so the scripted third turn was not consumed.
    assert model.calls == 2


# --- capability-aware routing ----------------------------------------------------


def test_prompted_models_get_the_protocol_and_never_a_native_bind(monkeypatch):
    with SessionLocal() as db:
        db.add(ModelCapabilities(model_id="mock-model", native_tools=False, parallel_tools=False))
        db.commit()
    registry = build_registry()
    model = MockLLM(
        [
            ScriptedTurn(
                text='Plan: check the time.\n<tool_call>{"name": "get_current_time", "arguments": {}}</tool_call>'
            ),
            ScriptedTurn(text="Done, it is now."),
        ]
    )

    events = asyncio.run(
        _collect(registry, model, _request(model_id="mock-model"))
    )
    # No native tool descriptor was ever offered to this model.
    assert model.bound_tools == []
    # The system prompt carried the prompted protocol block.
    first_prompt = model.prompts[0]
    system_text = next(m.content for m in first_prompt if m.type == "system")
    assert "tool_call" in system_text
    assert "get_current_time:" in system_text
    # The parsed call executed and the turn finished in prose.
    results = [event for event in events if event.name == "tool_result"]
    assert len(results) == 1
    assert results[0].payload["tool"] == "get_current_time"


def test_a_malformed_prompted_block_gets_a_corrective_round(monkeypatch):
    with SessionLocal() as db:
        db.add(ModelCapabilities(model_id="mock-model", native_tools=False, parallel_tools=False))
        db.commit()
    registry = build_registry()
    model = MockLLM(
        [
            ScriptedTurn(
                text='<tool_call>{"name": "calculator", "arguments": {broken}</tool_call>'
            ),
            ScriptedTurn(
                text='<tool_call>{"name": "calculator", "arguments": {"expression": "2+2"}}</tool_call>'
            ),
            ScriptedTurn(text="The answer is 4."),
        ]
    )

    events = asyncio.run(
        _collect(registry, model, _request(model_id="mock-model"))
    )
    # The malformed reply produced no execution, one correction, then work.
    assert [e.payload["tool"] for e in events if e.name == "tool_result"] == ["calculator"]
    second_prompt = model.prompts[1]
    corrective = next(
        m.content for m in second_prompt if isinstance(m, ToolMessage)
    )
    assert "malformed" in corrective


def test_non_parallel_models_keep_only_the_first_call(monkeypatch):
    with SessionLocal() as db:
        db.add(ModelCapabilities(model_id="mock-model", native_tools=True, parallel_tools=False))
        db.commit()
    registry = build_registry()
    model = MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {"name": "get_current_time", "args": {}, "id": "a"},
                    {"name": "calculator", "args": {"expression": "2+2"}, "id": "b"},
                )
            ),
            ScriptedTurn(text="Done."),
        ]
    )

    events = asyncio.run(
        _collect(registry, model, _request(model_id="mock-model"))
    )
    executed = [e.payload["tool"] for e in events if e.name == "tool_result"]
    assert executed == ["get_current_time"]
    assert model.bound_tools  # native stays native when the probe says so


def test_an_unprobed_model_keeps_the_native_path():
    registry = build_registry()
    model = MockLLM([ScriptedTurn(text="Hello.")])
    asyncio.run(_collect(registry, model, _request()))
    assert len(model.bound_tools) == 1  # schemas bound, no probe, no prompt


def test_probe_failure_falls_back_to_native(monkeypatch):
    def _explode(model, model_id):
        raise RuntimeError("probe endpoint down")

    monkeypatch.setattr(capabilities, "ensure_probed", _explode)
    registry = build_registry()
    model = MockLLM([ScriptedTurn(text="Still answering.")])
    events = asyncio.run(_collect(registry, model, _request(model_id="whatever")))
    assert any(event.name == "done" for event in events)
    assert len(model.bound_tools) == 1


# --- the system prompt ------------------------------------------------------------


def test_the_default_system_prompt_is_the_file():
    text = system_prompt.default_system_prompt()
    assert "Pentagon" in text
    assert "Never invent results" in text
    assert "UNTRUSTED" in text
    assert len(text) > 1000


def test_turn_request_defaults_to_the_file_prompt():
    request = TurnRequest(
        user_id="loop-test",
        conversation_id="conv-test",
        turn_id="t-default",
        permission_level=2,
        user_message="hi",
    )
    assert request.system_prompt == system_prompt.default_system_prompt()
    explicit = _request(system_prompt="custom")
    assert explicit.system_prompt == "custom"


def test_prompted_block_lists_only_the_selected_tools():
    registry = build_registry()
    specs = [registry.get("calculator").spec]
    block = prompted_tools.prompt_for_tools(specs)
    assert "calculator" in block
    assert "web_search" not in block
    assert "Arguments schema" in block
