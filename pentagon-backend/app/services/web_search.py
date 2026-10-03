from __future__ import annotations

from typing import Any

from app.config import settings


class WebSearchNotConfigured(RuntimeError):
    pass


async def search_web(query: str) -> list[dict[str, Any]]:
    if settings.tavily_api_key is None:
        raise WebSearchNotConfigured("TAVILY_API_KEY is not configured.")

    from langchain_tavily import TavilySearch

    search = TavilySearch(
        api_key=settings.tavily_api_key.get_secret_value(),
        max_results=6,
        topic="news" if any(term in query.lower() for term in ("news", "latest", "today")) else "general",
        include_answer=False,
        include_raw_content=False,
        search_depth="basic",
    )
    result = await search.ainvoke({"query": query})
    rows = result.get("results", []) if isinstance(result, dict) else []
    return [
        {
            "title": str(row.get("title") or "Untitled source"),
            "url": str(row.get("url") or ""),
            "content": str(row.get("content") or ""),
        }
        for row in rows
        if isinstance(row, dict)
    ]
