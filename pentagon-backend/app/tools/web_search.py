"""web_search: current public web information, grounded in fetched page text.

Wraps the app's grounded search service (DuckDuckGo with a Tavily fallback,
top pages fetched and extracted, SSRF-guarded). Results carry stable source
ids (S1, S2, ...) the model should cite, and the description pushes it to
fetch/read before trusting a snippet -- search results are leads, not
evidence.
"""

from __future__ import annotations

from typing import Any

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.services.web_search import search_web

TOOL_SPEC = ToolSpec(
    name="web_search",
    description=(
        "Search the public web for current information and read the top pages."
        " Use when the answer may have changed recently -- news, prices, releases,"
        " schedules, anything with a date -- or when you do not know the answer."
        " Do not use it for date/time (get_current_time), arithmetic (calculator),"
        " or questions about the user's uploaded files (search_documents). Returns"
        " up to 3 results, each with an id (S1, S2...), title, URL and the page's"
        " readable text. Cite the ids you rely on; the pages are the evidence."
        " Example: {\"query\": \"langgraph 1.0 release notes\"}."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query, phrased as you would type it into a search engine.",
            }
        },
        "required": ["query"],
    },
    tier="read",

    risk_category="read_only_info",    timeout_s=30,
    cacheable=True,
    cache_ttl_s=300,
    idempotent=True,
    parallel_safe=True,
    tags=("web", "internet", "search", "news", "current", "latest", "online"),
    untrusted=True,
)


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "query must be a non-empty string.",
            hint='Phrase the search, e.g. {"query": "pune weather today"}.',
        )
    try:
        results = await search_web(query.strip())
    except Exception as exc:
        return ToolResult.failure(
            "UPSTREAM",
            f"The web search failed: {type(exc).__name__}.",
            hint=(
                "Rephrase the query and try once more; if it still fails, answer"
                " from what you know and say the web was unreachable."
            ),
        )
    tagged = [
        {**row, "id": f"S{index + 1}"}
        for index, row in enumerate(results)
    ]
    return ToolResult.success(
        {"query": query.strip(), "results": tagged},
        source_ids=[row["id"] for row in tagged],
    )
