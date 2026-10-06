"""deep_research: a bounded research loop that runs inside one tool call.

The agent loop keeps its own LLM budget; this orchestrator keeps a tighter
internal one so a single research request can never become an unbounded
spend: at most ``MAX_QUERIES`` searches (each through the existing grounded
web search, which already fetches pages behind the SSRF guard), at most
``MAX_SOURCES`` cited pages, exactly two model calls (query planning and
synthesis), and a wall-clock deadline that bounds every await. It sees only the user's research question -- never the
conversation, never the system prompt -- and writes nothing: the report
travels back through the tool envelope, and the loop spotlights its
third-party text like any other web content because the spec is untrusted.

Steps:

1. Plan search queries (LLM call 1). A planning failure degrades to using
   the question itself as a single query instead of aborting the whole
   request -- search with a mediocre query beats answering nothing.
2. Run each query through ``search_web``, dedupe sources by URL, cap them.
3. Synthesize a cited answer (LLM call 2) over capped evidence excerpts,
   with numbered sources the model must reference as [n].
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

MAX_QUERIES = 4
MAX_SOURCES = 8
DEADLINE_SECONDS = 90.0
# Per-source and whole-evidence caps: the synthesis prompt must stay well
# under any model's context, and one huge page must not crowd out the rest.
_SOURCE_CHARS = 1_200
_EVIDENCE_CHARS = 14_000
_QUESTION_CHARS = 1_500

# Used when no default model is configured (Settings.default_chat_model).
# Overridable per deployment; service modules pin their model ids the same
# way (see vision.VISION_MODEL_ID).
RESEARCH_MODEL_ID = "meta/llama-3.3-70b-instruct"

_QUERY_INSTRUCTIONS = (
    "You plan web searches. Reply with ONLY a JSON array of 2 to 4 short"
    " search queries for the research question, no prose."
)
_SYNTHESIS_INSTRUCTIONS = (
    "You are a research assistant. Answer the question using ONLY the"
    " numbered sources below. Cite sources inline as [1], [2]. If the"
    " sources do not settle something, say so plainly instead of guessing."
    " Write a direct, well-organized report."
)


class ResearchError(RuntimeError):
    """Research could not produce a report (model or search failure)."""


class ResearchTimeout(ResearchError):
    """The wall-clock deadline passed before synthesis."""


def build_model(api_key: str, model: str) -> Any:
    """The one place research constructs a chat model (tests swap this)."""
    from app.services.nvidia_client import make_chat_model

    return make_chat_model(api_key, model)


async def run_search(query: str) -> list[dict[str, Any]]:
    """The existing grounded search: real page text, SSRF-guarded fetches."""
    from app.services.web_search import search_web

    return await search_web(query)


def _parse_queries(raw: str, question: str) -> list[str]:
    """Model output -> queries. JSON array first, then lines, then fallback."""
    candidates: list[str] = []
    text = raw.strip()
    try:
        start, end = text.index("["), text.rindex("]") + 1
        parsed = json.loads(text[start:end])
        if isinstance(parsed, list):
            candidates = [str(item).strip() for item in parsed]
    except (ValueError, json.JSONDecodeError):
        pass
    if not candidates:
        candidates = [re.sub(r"^[\s\-*\d.)]+", "", line).strip() for line in text.splitlines()]
    queries = []
    for candidate in candidates:
        candidate = " ".join(candidate.split())
        if candidate and candidate.lower() != question.lower().strip():
            queries.append(candidate[:200])
        if len(queries) >= MAX_QUERIES:
            break
    return queries or [" ".join(question.split())[:200]]


def _unique_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe by URL, keep order, cap the count."""
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    for row in rows:
        url = str(row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append(
            {
                "title": str(row.get("title") or "Untitled source"),
                "url": url,
                "content": str(row.get("content") or ""),
            }
        )
        if len(sources) >= MAX_SOURCES:
            break
    return sources


def _evidence_block(sources: list[dict[str, Any]]) -> str:
    """Capped, numbered excerpts for the synthesis prompt."""
    blocks: list[str] = []
    used = 0
    for number, source in enumerate(sources, start=1):
        excerpt = " ".join(source["content"].split())[:_SOURCE_CHARS]
        block = f"[{number}] {source['title']} ({source['url']})\n{excerpt}"
        if used + len(block) > _EVIDENCE_CHARS and blocks:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


async def research(question: str, *, api_key: str, model: str) -> dict[str, Any]:
    """Plan queries, gather sources, synthesize a cited report."""
    started = time.monotonic()
    llm_calls = 0

    def _await_budget() -> float:
        """Seconds one model call may take: until the deadline, capped."""
        return max(1.0, min(DEADLINE_SECONDS - (time.monotonic() - started), 60.0))

    queries = [" ".join(question.split())[:200]]
    planner = build_model(api_key, model)
    llm_calls += 1
    try:
        reply = await asyncio.wait_for(
            planner.ainvoke(
                [{"role": "system", "content": _QUERY_INSTRUCTIONS},
                 {"role": "user", "content": question[:_QUESTION_CHARS]}]
            ),
            _await_budget(),
        )
        planned = _parse_queries(str(reply.content or ""), question)
        if planned:
            queries = planned
    except Exception:
        # Planning is a convenience, not the deliverable: search anyway.
        pass

    rows: list[dict[str, Any]] = []
    for query in queries[:MAX_QUERIES]:
        if time.monotonic() - started > DEADLINE_SECONDS:
            break
        try:
            rows.extend(await run_search(query))
        except Exception:
            # One dead search engine must not sink the others.
            continue
    sources = _unique_sources(rows)
    if not sources:
        raise ResearchError(
            "web search returned no usable sources for any planned query"
        )
    if time.monotonic() - started > DEADLINE_SECONDS:
        raise ResearchTimeout(
            f"research hit its {DEADLINE_SECONDS:.0f}s deadline before synthesis"
        )

    synthesizer = build_model(api_key, model)
    llm_calls += 1
    try:
        reply = await asyncio.wait_for(
            synthesizer.ainvoke(
                [{"role": "system", "content": _SYNTHESIS_INSTRUCTIONS},
                 {"role": "user",
                  "content": f"Research question: {question[:_QUESTION_CHARS]}\n\n"
                             f"Sources:\n\n{_evidence_block(sources)}"}]
            ),
            _await_budget(),
        )
    except asyncio.TimeoutError as exc:
        raise ResearchTimeout(
            f"research hit its {DEADLINE_SECONDS:.0f}s deadline during synthesis"
        ) from exc
    report = str(reply.content or "").strip()
    if not report:
        raise ResearchError("the model returned an empty report")

    return {
        "report": report,
        "queries": queries[:MAX_QUERIES],
        "sources": [
            {"n": number, "title": source["title"], "url": source["url"]}
            for number, source in enumerate(sources, start=1)
        ],
        "llm_calls": llm_calls,
        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
    }
