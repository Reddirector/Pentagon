"""fetch_url: read one specific web page's text, SSRF-guarded.

Search results are leads; this is how the agent actually reads one. The fetch
reuses the app's guarded page reader -- public http(s) only, private and
loopback addresses refused, redirects re-validated -- so a model-supplied URL
can never be used to reach internal services.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.services.web_search import _ensure_public_url, _fetch_page

TOOL_SPEC = ToolSpec(
    name="fetch_url",
    description=(
        "Fetch one web page by URL and return its readable text. Use to read a"
        " specific page: one you found with web_search, or one the user gave"
        " you. Do not use it for private or internal addresses (they are"
        " refused), for PDFs or images, or as a substitute for search when you"
        " do not know the address. Returns the page's extracted text, truncated"
        " with a note if it is very long. Example:"
        ' {"url": "https://example.com/release-notes"}.'
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "A public http(s) URL to read."}
        },
        "required": ["url"],
    },
    tier="read",
    timeout_s=30,
    cacheable=True,
    cache_ttl_s=300,
    idempotent=True,
    parallel_safe=True,
    tags=("web", "url", "fetch", "read", "page", "link"),
    untrusted=True,
)

_MAX_RESULT_CHARS = 30_000


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    url = args.get("url")
    if not isinstance(url, str) or not url.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "url must be a non-empty http(s) URL.",
            hint='Pass the page address, e.g. {"url": "https://example.com/article"}.',
        )
    url = url.strip()
    async with httpx.AsyncClient(
        timeout=12.0,
        headers={"User-Agent": "Pentagon/1.0 (+https://github.com/Reddirector/Pentagon)"},
        follow_redirects=False,
    ) as client:
        try:
            await _ensure_public_url(client, url)
            text = await _fetch_page(client, url)
        except ValueError as exc:
            return ToolResult.failure(
                "INVALID_ARGS",
                f"That URL cannot be fetched: {exc}",
                hint="Use a public http(s) URL.",
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult.failure(
                "UPSTREAM",
                f"The URL returned {exc.response.status_code}.",
                hint=(
                    "Try a different source from the search results, or search"
                    " again for the same information."
                ),
            )
        except httpx.RequestError:
            return ToolResult.failure(
                "UPSTREAM",
                "The page could not be reached (network error or timeout).",
                hint="Try once more; if it still fails, use another source.",
            )
    if not text.strip():
        return ToolResult.failure(
            "UPSTREAM",
            "The page was fetched but contained no readable text (it may be"
            " JavaScript-only, a PDF, or an image).",
            hint="Try the page's print or AMP version, or find a text source.",
        )
    truncated = len(text) > _MAX_RESULT_CHARS
    return ToolResult.success(
        {"url": url, "text": text[:_MAX_RESULT_CHARS]},
        truncated=truncated,
    )
