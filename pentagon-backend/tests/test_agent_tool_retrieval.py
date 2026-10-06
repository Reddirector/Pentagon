"""Tool retrieval: the model sees few, relevant tools -- never the whole shelf."""

from app.agent.bootstrap import build_registry
from app.agent.retrieval import CORE_TOOLS, MAX_TOOLS, select_tools


def test_core_tools_are_always_selected():
    registry = build_registry()
    selected = select_tools(registry, "hello there")
    for name in CORE_TOOLS:
        if registry.has(name):
            assert name in selected


def test_cap_is_respected():
    registry = build_registry()
    selected = select_tools(registry, "search the web for the latest langgraph release")
    assert len(selected) <= MAX_TOOLS


def test_relevant_tool_outscores_irrelevant_ones():
    registry = build_registry()
    selected = select_tools(
        registry, "search the web for the latest news about fusion power"
    )
    assert "web_search" in selected
    # A plain greeting pulls in nothing beyond the core six.
    plain = select_tools(registry, "hello there, good morning")
    assert set(plain) == {
        name for name in CORE_TOOLS if registry.has(name)
    }


def test_documents_tool_exposed_when_docs_present():
    registry = build_registry()
    selected = select_tools(
        registry,
        "what does the contract say about termination",
        docs_present=True,
    )
    assert "read_document" in selected
    assert "search_documents" in selected


def test_sticky_tools_stay_available():
    registry = build_registry()
    selected = select_tools(
        registry, "now back to the weather", sticky={"web_search"}
    )
    assert "web_search" in selected


def test_selection_never_repeats():
    registry = build_registry()
    selected = select_tools(registry, "time and math and web search")
    assert len(selected) == len(set(selected))
