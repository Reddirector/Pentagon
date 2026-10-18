from __future__ import annotations

import asyncio
import pytest
from langchain_core.messages import AIMessage

from app.services import chat_graph
from app.services.document_builder import (
    BuildError,
    build_document,
    verify_document_integrity,
)


# --- Document Formation & Refinements ----------------------------------------


def test_document_callouts_and_tables_build_across_formats():
    content = (
        "# Executive Performance Report\n\n"
        "> [!NOTE] This document was compiled with automated integrity verification.\n\n"
        "> [!TIP] Review the tabular breakdown for regional revenue velocity.\n\n"
        "> [!WARNING] Certain high-risk transactions require manual review.\n\n"
        "| ID | Region | Status | Growth Rate | Remarks |\n"
        "|---|---|---|---|---|\n"
        "| 1 | North America | Active | +14.2% | Consistent enterprise expansion |\n"
        "| 2 | Europe | Review | +2.1% | Regulatory adjustments pending |\n\n"
        "```python\n"
        "# Deployment verification metric\n"
        "status = 'verified'\n"
        "assert status == 'verified'\n"
        "```\n"
    )

    for fmt in ["pdf", "docx", "html"]:
        data = build_document(fmt, "Executive Summary", content)
        assert isinstance(data, bytes)
        assert len(data) > 500
        # Verification succeeds automatically on build_document
        integrity = verify_document_integrity(fmt, data, "Executive Summary")
        assert integrity["valid"] is True
        assert integrity["format"] == fmt

def test_html_website_generation_preserves_full_code():
    raw_html = (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <style>.hero { background-color: #f59e0b; font-size: 24px; }</style>\n"
        "</head>\n"
        "<body>\n"
        "  <div class=\"hero\">Golden Crust Bakery</div>\n"
        "  <script>window.__app = { ready: true };</script>\n"
        "</body>\n"
        "</html>"
    )
    data = build_document("html", "Artisanal Bakery Website", raw_html)
    assert isinstance(data, bytes)
    decoded = data.decode("utf-8")
    assert "<!DOCTYPE html>" in decoded
    assert "<script>window.__app = { ready: true };</script>" in decoded
    assert '<div class="hero">Golden Crust Bakery</div>' in decoded
    # Must NOT escape HTML tags to entities
    assert "&lt;div" not in decoded
    assert "&lt;html" not in decoded
    integrity = verify_document_integrity("html", data, "Artisanal Bakery Website")
    assert integrity["valid"] is True


def test_html_fragment_wrapping():
    fragment = (
        "<header><nav><a href=\"#home\">Golden Crust</a></nav></header>\n"
        "<main><section class=\"menu\"><h2>Sourdough</h2></section></main>"
    )
    data = build_document("html", "Bakery Menu", fragment)
    decoded = data.decode("utf-8")
    assert "<html" in decoded and "</html>" in decoded
    assert '<section class="menu"><h2>Sourdough</h2></section>' in decoded
    assert "&lt;section" not in decoded
    integrity = verify_document_integrity("html", data, "Bakery Menu")
    assert integrity["valid"] is True


def test_html_fenced_code_extracted():
    fenced = (
        "```html\n"
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<body><h1>Clean Website</h1></body>\n"
        "</html>\n"
        "```"
    )
    data = build_document("html", "Clean Site", fenced)
    decoded = data.decode("utf-8")
    assert "```" not in decoded
    assert "<h1>Clean Website</h1>" in decoded
    integrity = verify_document_integrity("html", data, "Clean Site")
    assert integrity["valid"] is True


def test_html_presentation_from_slides():
    slides_input = {
        "slides": [
            {"title": "Introduction to Robotics", "bullets": ["Perception models", "Tactile feedback"]},
            {"title": "Market Trends 2026", "bullets": ["Factory automation", "Commercial deployment"]},
        ]
    }
    data = build_document("html", "Robotics Overview", slides_input)
    decoded = data.decode("utf-8")
    assert "<html" in decoded and "</html>" in decoded
    assert "Introduction to Robotics" in decoded
    assert "Perception models" in decoded
    assert "slide-card" in decoded
    assert "prevSlide" in decoded and "nextSlide" in decoded
    integrity = verify_document_integrity("html", data, "Robotics Overview")
    assert integrity["valid"] is True

    # Also test python-dict string representation resilience
    str_input = str(slides_input)
    data_str = build_document("html", "Robotics Overview Str", str_input)
    decoded_str = data_str.decode("utf-8")
    assert "Introduction to Robotics" in decoded_str
    assert "slide-card" in decoded_str
    integrity_str = verify_document_integrity("html", data_str, "Robotics Overview Str")
    assert integrity_str["valid"] is True


def test_xlsx_formatting_and_gridlines():
    sheet_data = {
        "columns": ["Department", "Headcount", "Budget Q1", "Budget Q2"],
        "rows": [
            ["Engineering", 42, 1200000, 1350000],
            ["Product", 15, 450000, 500000],
            ["Design", 8, 220000, 240000],
        ],
    }
    data = build_document("xlsx", "Staffing Plan", sheet_data)
    assert isinstance(data, bytes)
    assert data.startswith(b"PK\x03\x04")
    integrity = verify_document_integrity("xlsx", data, "Staffing Plan")
    assert integrity["valid"] is True


# --- Document Integrity Verification Checks ---------------------------------


def test_verify_document_integrity_rejects_empty_data():
    with pytest.raises(BuildError, match="Generated pdf file is empty"):
        verify_document_integrity("pdf", b"", "Empty")


def test_verify_document_integrity_rejects_bad_magic():
    with pytest.raises(BuildError, match="PDF header validation failed"):
        verify_document_integrity("pdf", b"NOT_A_REAL_PDF_HEADER" + b"A" * 200, "Bad Header")

    with pytest.raises(BuildError, match="DOCX archive validation failed"):
        verify_document_integrity("docx", b"NOT_A_ZIP_HEADER" + b"A" * 600, "Bad Header")


def test_verify_document_integrity_rejects_corrupted_zip():
    # Header starts with PK but content is corrupt zip
    fake_zip = b"PK\x03\x04" + b"\x00" * 600
    with pytest.raises(BuildError, match="archive is not a valid zip"):
        verify_document_integrity("docx", fake_zip, "Corrupt Zip")


def test_verify_document_integrity_rejects_malformed_html():
    with pytest.raises(BuildError, match="HTML document is missing standard"):
        verify_document_integrity("html", b"<div>Hello world without html wrapper</div>", "Bad HTML")


# --- Chat Graph Pre-Final Result Checks --------------------------------------


class CustomFakeModel:
    def __init__(self, answer: str):
        self._answer = answer

    async def ainvoke(self, messages, config=None):
        return AIMessage(content=self._answer)


def test_chat_graph_sanitizes_leaked_untrusted_markers(monkeypatch):
    leaked_response = (
        "Here is the financial breakdown:\n\n"
        "<<<PENTAGON_UNTRUSTED_0123456789abcdef0123456789abcdef_BEGIN>>>\n"
        "Confidential Data\n"
        "<<<PENTAGON_UNTRUSTED_0123456789abcdef0123456789abcdef_END>>>\n"
        "Net income grew by 18%."
    )
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_args, **_kwargs: CustomFakeModel(leaked_response))
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: False)
    monkeypatch.setattr(chat_graph, "search_web", lambda _q: [])

    graph = chat_graph.build_chat_graph("key", "model", user_id="u1", use_web_search=False)
    state = chat_graph.initial_chat_state(
        user_id="u1",
        conversation_id="c1",
        message="What is the net income?",
        history=[],
        use_web_search=False,
    )
    result = asyncio.run(graph.ainvoke(state))

    assert "<<<PENTAGON_" not in result["answer"]
    assert "Net income grew by 18%." in result["answer"]
    assert result["execution_trace"]["verify_final_result"]["status"] == "ran"
    assert result["execution_trace"]["verify_final_result"]["leaks_cleaned"] == 2


def test_chat_graph_repairs_unclosed_markdown_fences(monkeypatch):
    broken_fence_response = (
        "Here is the implementation script:\n\n"
        "```python\n"
        "def compute():\n"
        "    return 42\n"
    )
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_args, **_kwargs: CustomFakeModel(broken_fence_response))
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: False)
    monkeypatch.setattr(chat_graph, "search_web", lambda _q: [])

    graph = chat_graph.build_chat_graph("key", "model", user_id="u1", use_web_search=False)
    state = chat_graph.initial_chat_state(
        user_id="u1",
        conversation_id="c1",
        message="Show me the script",
        history=[],
        use_web_search=False,
    )
    result = asyncio.run(graph.ainvoke(state))

    # Should end with closed triple backticks
    assert result["answer"].rstrip().endswith("```")
    assert result["execution_trace"]["verify_final_result"]["fences_repaired"] is True


def test_chat_graph_strips_conversational_filler_preamble(monkeypatch):
    fluffy_response = "Certainly! I'd be happy to help with that. The quarterly revenue reached $4.2M."
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_args, **_kwargs: CustomFakeModel(fluffy_response))
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: False)
    monkeypatch.setattr(chat_graph, "search_web", lambda _q: [])

    graph = chat_graph.build_chat_graph("key", "model", user_id="u1", use_web_search=False)
    state = chat_graph.initial_chat_state(
        user_id="u1",
        conversation_id="c1",
        message="Revenue figures please",
        history=[],
        use_web_search=False,
    )
    result = asyncio.run(graph.ainvoke(state))

    # Preamble stripped, begins with direct substantive statement
    assert not result["answer"].startswith("Certainly")
    assert "The quarterly revenue reached $4.2M." in result["answer"]
    assert result["execution_trace"]["verify_final_result"]["filler_stripped"] is True
