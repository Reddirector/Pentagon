from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings


class WebSearchNotConfigured(RuntimeError):
    pass


_MAX_FETCH_BYTES = 2_000_000
_MAX_FETCH_PAGES = 3
_FETCH_TIMEOUT_SECONDS = 12.0
_ALLOWED_SCHEMES = {"http", "https"}
_TEXTUAL_CONTENT_TYPES = ("text/", "application/xhtml", "application/xml")


def _is_blocked_address(host: str) -> bool:
    """True when the host resolves to a private/loopback/link-local address."""
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return True
        addresses = set()
        for info in infos:
            try:
                addresses.add(ipaddress.ip_address(info[4][0]))
            except ValueError:
                return True
    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            return True
    return False


async def _ensure_public_url(client: httpx.AsyncClient, url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise ValueError("Only http(s) URLs can be fetched.")
    if _is_blocked_address(parsed.hostname):
        raise ValueError("Refusing to fetch a private or loopback address.")


async def _fetch_page(client: httpx.AsyncClient, url: str) -> str:
    """Fetch a page and extract its readable text. Redirects are re-checked."""
    await _ensure_public_url(client, url)

    async def _get(current: str) -> httpx.Response:
        response = await client.get(current, follow_redirects=False)
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                raise ValueError("Redirect without a target.")
            absolute = str(httpx.URL(current).join(location))
            # Re-validate: a redirect must not smuggle us onto a private host.
            await _ensure_public_url(client, absolute)
            return await _get(absolute)
        return response

    response = await _get(url)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if content_type and not any(kind in content_type for kind in _TEXTUAL_CONTENT_TYPES):
        return ""
    body = response.content[:_MAX_FETCH_BYTES]
    html = body.decode(response.encoding or "utf-8", errors="replace")
    try:
        import trafilatura

        extracted = await asyncio.to_thread(
            trafilatura.extract,
            html,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
    except Exception:
        extracted = None
    if extracted and extracted.strip():
        return extracted.strip()
    # Extraction can legitimately return nothing; fall back to stripped markup
    # rather than answering from a search snippet alone.
    import re

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:20_000]


async def _search_ddgs(query: str) -> list[dict[str, Any]]:
    from ddgs import DDGS

    def _run() -> list[dict[str, Any]]:
        with DDGS(timeout=10) as client:
            rows = list(client.text(query, max_results=5))
        return [row for row in rows if isinstance(row, dict)]

    try:
        rows = await asyncio.to_thread(_run)
    except Exception:
        return []
    return [
        {
            "title": str(row.get("title") or "Untitled source"),
            "url": str(row.get("href") or row.get("url") or ""),
            "content": str(row.get("body") or ""),
        }
        for row in rows
        if row.get("href") or row.get("url")
    ]


async def _search_tavily(query: str) -> list[dict[str, Any]]:
    if settings.tavily_api_key is None:
        return []
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


async def search_web(query: str) -> list[dict[str, Any]]:
    """Search the web and return grounded page text, never snippets alone.

    Uses keyless DuckDuckGo search first and falls back to Tavily when a key is
    configured. The top results are fetched concurrently and their readable
    text replaces the search snippet, so answers can cite real page content.
    """
    results = await _search_ddgs(query)
    if not results:
        results = await _search_tavily(query)
    if not results:
        raise WebSearchNotConfigured(
            "Web search returned no results and Tavily is not configured."
        )

    results = [row for row in results if row.get("url")][:_MAX_FETCH_PAGES]
    if not results:
        raise WebSearchNotConfigured("Web search returned no usable URLs.")

    async with httpx.AsyncClient(
        timeout=_FETCH_TIMEOUT_SECONDS,
        headers={"User-Agent": "Pentagon/1.0 (+https://github.com/Reddirector/Pentagon)"},
        follow_redirects=False,
    ) as client:
        pages = await asyncio.gather(
            *(_fetch_page(client, row["url"]) for row in results),
            return_exceptions=True,
        )

    grounded: list[dict[str, Any]] = []
    for row, page in zip(results, pages):
        if isinstance(page, BaseException) or not page.strip():
            continue
        grounded.append({**row, "content": page})
    if not grounded:
        raise WebSearchNotConfigured("Could not read the text of any search result.")
    return grounded