"""The web and document tools: envelopes, source ids, SSRF refusal, ordering."""

import asyncio
from unittest.mock import patch

import httpx
import pytest

from app.agent.schemas import ToolContext
from app.tools import fetch_url, search_documents, web_search
from app.tools.read_document import run as read_document_run


def _ctx() -> ToolContext:
    return ToolContext(user_id="u", conversation_id="conv-docs", turn_id="t", permission_level=2)


def _run(tool, args):
    handler = tool.run if hasattr(tool, "run") else tool
    return asyncio.run(handler(args, _ctx()))


# --- web_search ----------------------------------------------------------------

def test_web_search_wraps_results_with_source_ids():
    async def fake_search(query):
        return [
            {"title": "A", "url": "https://a.example/x", "content": "alpha text"},
            {"title": "B", "url": "https://b.example/y", "content": "beta text"},
        ]

    with patch("app.tools.web_search.search_web", fake_search):
        result = _run(web_search, {"query": "anything"})

    assert result.ok is True
    assert [row["id"] for row in result.data["results"]] == ["S1", "S2"]
    assert result.meta.source_ids == ["S1", "S2"]


def test_web_search_failure_is_an_upstream_envelope():
    async def boom(query):
        raise RuntimeError("no network")

    with patch("app.tools.web_search.search_web", boom):
        result = _run(web_search, {"query": "anything"})

    assert result.ok is False
    assert result.error.code == "UPSTREAM"
    assert "Rephrase" in result.error.hint


def test_web_search_rejects_an_empty_query():
    result = _run(web_search, {"query": "   "})
    assert result.ok is False and result.error.code == "INVALID_ARGS"


# --- fetch_url -----------------------------------------------------------------

def test_fetch_url_reads_a_page():
    async def fake_ensure(client, url):
        return None

    async def fake_fetch(client, url):
        return "Pentagon release notes, the full page text."

    with patch("app.tools.fetch_url._ensure_public_url", fake_ensure), patch(
        "app.tools.fetch_url._fetch_page", fake_fetch
    ):
        result = _run(fetch_url, {"url": "https://example.com/notes"})

    assert result.ok is True
    assert "release notes" in result.data["text"]
    assert result.meta.truncated is False


def test_fetch_url_refuses_private_addresses_before_any_request():
    result = _run(fetch_url, {"url": "http://127.0.0.1:8000/admin"})
    assert result.ok is False
    assert result.error.code == "INVALID_ARGS"
    assert "private" in result.error.message.lower() or "cannot" in result.error.message.lower()


def test_fetch_url_handles_a_403():
    async def fake_ensure(client, url):
        return None

    async def fake_fetch(client, url):
        raise httpx.HTTPStatusError(
            "403", request=httpx.Request("GET", url), response=httpx.Response(403)
        )

    with patch("app.tools.fetch_url._ensure_public_url", fake_ensure), patch(
        "app.tools.fetch_url._fetch_page", fake_fetch
    ):
        result = _run(fetch_url, {"url": "https://example.com/paywalled"})

    assert result.ok is False
    assert result.error.code == "UPSTREAM"
    assert "403" in result.error.message
    assert "different source" in result.error.hint


# --- search_documents / read_document ------------------------------------------

@pytest.fixture()
def _docs_collection(monkeypatch):
    """A fake Chroma collection standing in for the conversation's uploads."""
    rows = {
        "documents": [
            "Chunk zero of the contract.",
            "Chunk one: termination needs 30 days notice.",
            "Chunk two: the fee is 500 rupees.",
        ],
        "metadatas": [
            {"filename": "contract.pdf", "document_id": "d1"},
            {"filename": "contract.pdf", "document_id": "d1"},
            {"filename": "notes.txt", "document_id": "d2"},
        ],
    }

    class FakeCollection:
        def count(self):
            return len(rows["documents"])

        def get(self, include=None):
            return dict(rows)

    # The tool imports these names into its own namespace, so patch there.
    monkeypatch.setattr(
        "app.tools.search_documents.has_documents", lambda conversation_id: True
    )

    async def fake_retrieve(*, conversation_id, query, api_key, limit=4):
        # A cosine-ish fake: just return everything, the tool shapes it.
        return [
            {
                "chunk_id": f"chunk-{i}",
                "document_id": rows["metadatas"][i].get("document_id"),
                "filename": rows["metadatas"][i].get("filename", "document"),
                "content": rows["documents"][i],
                "distance": 0.2,
            }
            for i in range(min(limit, len(rows["documents"])))
        ]

    monkeypatch.setattr("app.tools.search_documents.retrieve_chunks", fake_retrieve)

    class FakeClient:
        def get_collection(self, name):
            return FakeCollection()

    monkeypatch.setattr("app.tools.read_document._client", lambda: FakeClient())
    monkeypatch.setattr(
        "app.tools.read_document.collection_name_for_conversation",
        lambda conversation_id: "fake-collection",
    )
    return rows


def test_search_documents_returns_located_chunks(_docs_collection):
    result = _run(search_documents, {"query": "termination notice"})
    assert result.ok is True
    assert result.data["chunks"][0]["filename"] in ("contract.pdf", "notes.txt")
    assert all("content" in chunk for chunk in result.data["chunks"])


def test_search_documents_reports_an_empty_collection_gently(_docs_collection, monkeypatch):
    monkeypatch.setattr(
        "app.tools.search_documents.has_documents", lambda conversation_id: False
    )
    result = _run(search_documents, {"query": "anything"})
    assert result.ok is True
    assert result.data["chunks"] == []
    assert "No documents" in result.data["note"]


def test_read_document_pages_in_order(_docs_collection):
    result = _run(read_document_run, {"filename": "contract.pdf", "offset": 0, "limit": 2})
    assert result.ok is True
    assert [chunk["position"] for chunk in result.data["chunks"]] == [0, 1]
    assert all(chunk["filename"] == "contract.pdf" for chunk in result.data["chunks"])


def test_read_document_offset_beyond_the_end_is_a_clean_miss(_docs_collection):
    result = asyncio.run(read_document_run({"filename": "contract.pdf", "offset": 9, "limit": 2}, _ctx()))
    assert result.ok is False
    assert result.error.code == "NOT_FOUND"
