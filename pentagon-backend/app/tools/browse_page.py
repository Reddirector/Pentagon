"""browse_page: render a public page in headless Chromium and read it.

The JS-capable sibling of fetch_url: same tier (read), same SSRF refusals,
one addition -- results are marked ``untrusted`` so the loop spotlights and
scan-flags the third-party text exactly like every other web content tool.
The description is where the model learns when to prefer this over
fetch_url: JavaScript-heavy pages need a browser, plain documents do not.
"""

from __future__ import annotations

from typing import Any

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.services import browser

TOOL_SPEC = ToolSpec(
    name="browse_page",
    description=(
        "Open a public web page in a headless browser and return its"
        " rendered text. Use when fetch_url is not enough because the page"
        " needs JavaScript: single-page apps, content injected by scripts,"
        " pages that refuse plain HTTP clients. The page is rendered with no"
        " cookies, no stored login and no history from earlier visits, so a"
        " page behind a sign-in shows its logged-out view -- tell the user"
        " rather than pretending otherwise. Private, loopback and link-local"
        " addresses are refused, as is every non-http scheme. Returns the"
        " final URL after redirects, the page title, the HTTP status and the"
        " visible text. One page per call; it cannot click, type or scroll."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "A public http(s) URL to render and read.",
            }
        },
        "required": ["url"],
    },
    tier="read",
    timeout_s=45,
    cacheable=True,
    cache_ttl_s=300,
    idempotent=True,
    # One call starts one Chromium; a batch runs them one after another
    # instead of four browsers at once.
    parallel_safe=False,
    untrusted=True,
    tags=(
        "browse",
        "browser",
        "render",
        "javascript",
        "spa",
        "website",
        "webpage",
        "page",
        "url",
        "read",
    ),
)


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if not browser.browser_available():
        return ToolResult.failure(
            "DENIED",
            "browse_page is disabled: no headless browser is installed here.",
            hint=(
                "fetch_url can still read pages that do not need"
                " JavaScript; installing Playwright's Chromium enables"
                " browse_page."
            ),
        )
    url = args.get("url")
    if not isinstance(url, str) or not url.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "url must be a non-empty http(s) address.",
            hint='Pass the address like {"url": "https://example.com/page"}.',
        )
    try:
        page = await browser.browse(url.strip())
    except ValueError as exc:
        # Scheme and SSRF refusals travel as ValueError; say why plainly.
        return ToolResult.failure(
            "DENIED",
            str(exc),
            hint="Only public http(s) pages can be browsed.",
        )
    except browser.BrowserUnavailable as exc:
        return ToolResult.failure(
            "DENIED",
            f"The browser could not be started: {exc}.",
            hint="browse_page never falls back to fetching without rendering.",
        )
    except TimeoutError as exc:
        return ToolResult.failure(
            "TIMEOUT",
            str(exc),
            hint="The page may be heavy with scripts; fetch_url may suffice.",
        )
    if page.status is not None and page.status >= 400:
        return ToolResult.failure(
            "UPSTREAM",
            f"The page returned HTTP {page.status}.",
            hint=f"The final address was {page.url}.",
        )
    return ToolResult.success(
        {
            "url": page.url,
            "title": page.title,
            "status": page.status,
            "text": page.text,
            "rendered": True,
        }
    )
