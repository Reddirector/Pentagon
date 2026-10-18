"""web_search: current public web information, grounded in fetched page text.

Wraps the app's grounded search service (DuckDuckGo with a Tavily fallback,
top pages fetched and extracted, SSRF-guarded). Results carry stable source
ids (S1, S2, ...) the model should cite, and the description pushes it to
fetch/read before trusting a snippet -- search results are leads, not
evidence.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.services.web_search import search_images, search_web

TOOL_SPEC = ToolSpec(
    name="web_search",
    description=(
        "Search the public web for current information, read the top pages, and find real images."
        " Use when the answer may have changed recently -- news, prices, releases,"
        " schedules, anything with a date -- or when you do not know the answer."
        " Do not use it for date/time (get_current_time), arithmetic (calculator),"
        " or questions about the user's uploaded files (search_documents). Returns"
        " up to 3 grounded text results with ids (S1, S2...) to cite as [1], [2], AND"
        " verified real web images with 'title', 'image_url', and ready-to-use 'markdown' (e.g. `![Title](url)`)."
        " Embed these real images directly in your markdown response and documents when figures/photos are needed."
        " Example: {\"query\": \"Tesla Optimus robot 2026 specs\"}."
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
    risk_category="read_only_info",
    timeout_s=30,
    cacheable=True,
    cache_ttl_s=300,
    idempotent=True,
    parallel_safe=True,
    max_result_chars=16000,
    tags=("web", "internet", "search", "news", "current", "latest", "online", "image"),
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
    clean_query = query.strip()
    try:
        web_task = asyncio.create_task(search_web(clean_query))
        img_task = asyncio.create_task(search_images(clean_query, max_results=4))
        web_res, img_res = await asyncio.gather(web_task, img_task, return_exceptions=True)
    except Exception as exc:
        return ToolResult.failure(
            "UPSTREAM",
            f"The web search failed: {type(exc).__name__}.",
            hint=(
                "Rephrase the query and try once more; if it still fails, answer"
                " from what you know and say the web was unreachable."
            ),
        )

    if isinstance(web_res, BaseException):
        return ToolResult.failure(
            "UPSTREAM",
            f"The web search failed: {type(web_res).__name__}.",
            hint=(
                "Rephrase the query and try once more; if it still fails, answer"
                " from what you know and say the web was unreachable."
            ),
        )

    valid_images: list[dict[str, Any]] = []
    if isinstance(img_res, list) and img_res:
        valid_images = [
            {
                "title": img.get("title") or "Web image",
                "image_url": img.get("image_url"),
                "source_url": img.get("source_url") or "",
                "markdown": f"![{img.get('title') or 'Image'}]({img.get('image_url')})",
            }
            for img in img_res
            if isinstance(img, dict) and img.get("image_url")
        ]

    tagged = [
        {
            "id": f"S{index + 1}",
            "title": row.get("title", "Untitled source"),
            "url": row.get("url", ""),
            "content": str(row.get("content") or "").strip()[:2200],
        }
        for index, row in enumerate(web_res)
    ]
    payload: dict[str, Any] = {
        "query": clean_query,
        "images": valid_images,
        "results": tagged,
    }

    return ToolResult.success(
        payload,
        source_ids=[row["id"] for row in tagged],
    )
