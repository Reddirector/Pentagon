import asyncio
import time

from langchain_core.messages import AIMessage

from app.services import chat_graph


class FakeChatModel:
    async def ainvoke(self, messages, config=None):
        return AIMessage(content="mock response")


def _patch_model(monkeypatch):
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_args, **_kwargs: FakeChatModel())


def _state(message="Tell me about the latest local news", use_web_search=None):
    return chat_graph.initial_chat_state(
        user_id="test-user",
        conversation_id="test-conversation",
        message=message,
        history=[],
        use_web_search=use_web_search,
    )


def test_web_and_document_branches_run_concurrently(monkeypatch):
    _patch_model(monkeypatch)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: True)
    both_started = asyncio.Event()
    entered = 0

    async def wait_for_other_branch():
        nonlocal entered
        entered += 1
        if entered == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.5)
        await asyncio.sleep(0.12)

    async def fake_search(_query):
        await wait_for_other_branch()
        return [{"title": "News", "url": "https://example.test/news", "content": "A result."}]

    async def fake_retrieval(**_kwargs):
        await wait_for_other_branch()
        return [{"chunk_id": "chunk-1", "document_id": "doc-1", "filename": "notes.txt", "content": "A passage."}]

    monkeypatch.setattr(chat_graph, "search_web", fake_search)
    monkeypatch.setattr(chat_graph, "retrieve_chunks", fake_retrieval)
    graph = chat_graph.build_chat_graph(
        "unused-test-key", "test-model", user_id="test-user", use_web_search=None
    )

    async def run_graph():
        started = time.perf_counter()
        result = await graph.ainvoke(_state())
        return result, time.perf_counter() - started

    result, elapsed = asyncio.run(run_graph())

    assert elapsed < 0.35
    assert result["execution_trace"]["web_search"]["status"] == "ran"
    assert result["execution_trace"]["retrieve_documents"]["status"] == "ran"
    assert len(result["web_results"]) == 1
    assert len(result["retrieved_chunks"]) == 1
    sources = chat_graph.public_sources(result)
    assert sources["web"] == [
        {"title": "News", "url": "https://example.test/news"}
    ]
    assert sources["documents"][0]["chunk_ids"] == ["chunk-1"]


def test_router_short_circuits_when_search_and_retrieval_are_not_needed(monkeypatch):
    _patch_model(monkeypatch)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: False)

    async def should_not_search(_query):
        raise AssertionError("web search should have been skipped")

    async def should_not_retrieve(**_kwargs):
        raise AssertionError("retrieval should have been skipped")

    monkeypatch.setattr(chat_graph, "search_web", should_not_search)
    monkeypatch.setattr(chat_graph, "retrieve_chunks", should_not_retrieve)
    graph = chat_graph.build_chat_graph(
        "unused-test-key", "test-model", user_id="test-user", use_web_search=False
    )
    result = asyncio.run(graph.ainvoke(_state("Explain how a bicycle works.", False)))

    assert result["answer"] == "mock response"
    assert result["execution_trace"]["web_search"]["status"] == "skipped"
    assert result["execution_trace"]["retrieve_documents"]["status"] == "skipped"
    assert result["execution_trace"]["context_assembler"]["document_count"] == 0
    assert result["execution_trace"]["context_assembler"]["web_result_count"] == 0


def test_failed_web_search_does_not_fail_chat(monkeypatch):
    _patch_model(monkeypatch)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: False)

    async def failed_search(_query):
        raise RuntimeError("mock search outage")

    monkeypatch.setattr(chat_graph, "search_web", failed_search)
    graph = chat_graph.build_chat_graph(
        "unused-test-key", "test-model", user_id="test-user", use_web_search=True
    )
    result = asyncio.run(graph.ainvoke(_state("Tell me about this topic.", True)))

    assert result["answer"] == "mock response"
    assert result["execution_trace"]["web_search"]["status"] == "failed"
    assert result["execution_trace"]["generate_response"]["status"] == "ran"
