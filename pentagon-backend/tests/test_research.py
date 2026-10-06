"""T11: deep research is bounded, cited, and honest about every failure.

The orchestrator runs against a scripted model and a fake search: queries
are planned, sources deduped and numbered, a planner failure degrades to
searching the raw question, and dead search or empty synthesis surface as
typed errors instead of confident prose. The tool layer maps those onto the
envelope and resolves the key itself.
"""

import asyncio

import pytest

from app.agent import research
from app.agent.schemas import ToolContext
from app.evals.mock_llm import MockLLM, ScriptedTurn
from app.security.keys import NoKeyAvailableError
from app.tools import deep_research


def _ctx() -> ToolContext:
    return ToolContext(
        user_id="res-user", conversation_id="c", turn_id="t", permission_level=2
    )


def _page(url: str, content: str = "grounded page text") -> dict:
    return {"title": f"Title {url}", "url": url, "content": content}


def _install(monkeypatch, model: MockLLM, search) -> None:
    monkeypatch.setattr(research, "build_model", lambda _key, _name: model)
    monkeypatch.setattr(research, "run_search", search)


async def _find(query: str) -> list[dict]:
    """One grounded page per query, URL derived from the query itself."""
    return [_page(f"https://ex.com/{query.replace(' ', '-')}", "enough text")]


# --- pure helpers --------------------------------------------------------------


def test_parse_queries_prefers_json_then_lines_then_the_question():
    assert research._parse_queries('["a query", "b query"]', "q") == [
        "a query",
        "b query",
    ]
    assert research._parse_queries("1. first angle\n2. second angle", "q") == [
        "first angle",
        "second angle",
    ]
    assert research._parse_queries("", "how do routers work") == [
        "how do routers work"
    ]
    # A model echoing the question back collapses to the fallback, not a dup.
    assert research._parse_queries('["how do routers work"]', "how do routers work") == [
        "how do routers work"
    ]


def test_unique_sources_dedupes_by_url_and_caps():
    rows = [_page(f"https://ex.com/{i % 3}") for i in range(12)]
    sources = research._unique_sources(rows)
    assert len(sources) == 3
    capped = research._unique_sources(
        [_page(f"https://ex.com/{i}") for i in range(20)]
    )
    assert len(capped) == research.MAX_SOURCES


# --- the orchestrator ------------------------------------------------------------


def test_research_plans_gathers_and_synthesizes(monkeypatch):
    model = MockLLM(
        [
            ScriptedTurn(text='["rotor maintenance intervals", "17-stage valve"]'),
            ScriptedTurn(text="Synthesized answer with citations [1] and [2]."),
        ]
    )
    _install(
        monkeypatch,
        model,
        _find,
    )
    outcome = asyncio.run(
        research.research("what is the service interval?", api_key="k", model="m")
    )
    assert outcome["report"].startswith("Synthesized answer")
    assert outcome["queries"] == ["rotor maintenance intervals", "17-stage valve"]
    assert [s["n"] for s in outcome["sources"]] == [1, 2]
    assert outcome["llm_calls"] == 2
    assert model.calls == 2
    # The synthesis prompt carried the numbered sources verbatim.
    synthesis = model.prompts[1]
    last = synthesis[-1]["content"]
    assert "[1] Title" in last
    assert "https://ex.com/rotor-maintenance-intervals" in last


def test_a_failed_planner_degrades_to_searching_the_question(monkeypatch):
    model = MockLLM(
        [
            ScriptedTurn(error=RuntimeError("planner exploded")),
            ScriptedTurn(text="Recovered report [1]."),
        ]
    )
    _install(monkeypatch, model, _find)
    outcome = asyncio.run(
        research.research("What about bearings?", api_key="k", model="m")
    )
    assert outcome["report"] == "Recovered report [1]."
    assert outcome["queries"] == ["What about bearings?"]
    assert outcome["llm_calls"] == 2


def test_dead_search_raises_instead_of_answering_from_nothing(monkeypatch):
    model = MockLLM([ScriptedTurn(text='["anything"]')])

    async def _down(_query):
        raise RuntimeError("search is down")

    _install(monkeypatch, model, _down)
    with pytest.raises(research.ResearchError):
        asyncio.run(research.research("question", api_key="k", model="m"))


def test_empty_synthesis_is_an_error_not_an_answer(monkeypatch):
    model = MockLLM(
        [ScriptedTurn(text='["q"]'), ScriptedTurn(text="   ")]
    )
    _install(monkeypatch, model, _find)
    with pytest.raises(research.ResearchError):
        asyncio.run(research.research("question", api_key="k", model="m"))


# --- the tool's envelope ----------------------------------------------------------


def test_spec_is_read_untrusted_and_deliberately_serial():
    spec = deep_research.TOOL_SPEC
    assert spec.tier == "read"
    assert spec.untrusted is True
    assert spec.parallel_safe is False
    assert spec.timeout_s >= research.DEADLINE_SECONDS


def test_tool_validates_before_touching_any_key():
    for args in ({}, {"question": ""}, {"question": 42}):
        result = asyncio.run(deep_research.run(args, _ctx()))
        assert result.ok is False, args
        assert result.error.code == "INVALID_ARGS"
    big = "x" * (research._QUESTION_CHARS + 1)
    result = asyncio.run(deep_research.run({"question": big}, _ctx()))
    assert result.ok is False and result.error.code == "INVALID_ARGS"


def test_tool_without_a_key_is_an_honest_denial(monkeypatch):
    def _no_key(_db, _user_id):
        raise NoKeyAvailableError("no stored key")

    monkeypatch.setattr(deep_research, "resolve_api_key", _no_key)
    result = asyncio.run(deep_research.run({"question": "what is new?"}, _ctx()))
    assert result.ok is False
    assert result.error.code == "DENIED"
    assert "Settings" in result.error.hint


def test_tool_maps_timeout_and_research_failures(monkeypatch):
    monkeypatch.setattr(deep_research, "resolve_api_key", lambda _db, _u: "key")

    async def _timeout(question, *, api_key, model):
        raise research.ResearchTimeout("research hit its 90s deadline")

    monkeypatch.setattr(research, "research", _timeout)
    result = asyncio.run(deep_research.run({"question": "slow topic"}, _ctx()))
    assert result.ok is False and result.error.code == "TIMEOUT"

    async def _broken(question, *, api_key, model):
        raise research.ResearchError("web search returned no usable sources")

    monkeypatch.setattr(research, "research", _broken)
    result = asyncio.run(deep_research.run({"question": "dead search"}, _ctx()))
    assert result.ok is False and result.error.code == "UPSTREAM"


def test_tool_returns_the_report_on_success(monkeypatch):
    monkeypatch.setattr(deep_research, "resolve_api_key", lambda _db, _u: "key")
    seen = {}

    async def _ok(question, *, api_key, model):
        seen.update(question=question, api_key=api_key, model=model)
        return {"report": "cited [1]", "queries": ["q"], "sources": [], "llm_calls": 2}

    monkeypatch.setattr(research, "research", _ok)
    result = asyncio.run(deep_research.run({"question": "the thing?"}, _ctx()))
    assert result.ok is True
    assert result.data["report"] == "cited [1]"
    assert seen["question"] == "the thing?"
    assert seen["api_key"] == "key"  # resolved from the user, not the args
