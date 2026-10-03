import httpx
import pytest

from app.services import web_search
from app.services.web_search import WebSearchNotConfigured, search_web


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1:8000/docs",
        "http://localhost/admin",
        "http://10.0.0.5/internal",
        "http://169.254.169.254/latest/meta-data/",
        "ftp://example.com/file",
    ],
)
def test_private_and_non_http_urls_are_refused(url: str):
    async def check():
        async with httpx.AsyncClient() as client:
            with pytest.raises(ValueError):
                await web_search._ensure_public_url(client, url)

    import asyncio

    asyncio.run(check())


def test_search_returns_grounded_page_text_not_snippets(monkeypatch):
    async def fake_ddgs(query: str):
        return [
            {"title": "First result", "url": "https://example.com/one", "content": "snippet one"},
            {"title": "Second result", "url": "https://example.com/two", "content": "snippet two"},
        ]

    async def fake_fetch(client, url: str):
        return f"full page text for {url}"

    monkeypatch.setattr(web_search, "_search_ddgs", fake_ddgs)
    monkeypatch.setattr(web_search, "_fetch_page", fake_fetch)

    import asyncio

    results = asyncio.run(search_web("latest news"))

    assert [row["url"] for row in results] == [
        "https://example.com/one",
        "https://example.com/two",
    ]
    assert results[0]["content"] == "full page text for https://example.com/one"
    assert "snippet" not in results[0]["content"]


def test_search_raises_when_nothing_usable_is_returned(monkeypatch):
    async def empty_ddgs(query: str):
        return []

    async def empty_tavily(query: str):
        return []

    monkeypatch.setattr(web_search, "_search_ddgs", empty_ddgs)
    monkeypatch.setattr(web_search, "_search_tavily", empty_tavily)

    import asyncio

    with pytest.raises(WebSearchNotConfigured):
        asyncio.run(search_web("anything"))