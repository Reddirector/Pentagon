"""Headless Chromium for pages that need JavaScript -- under fetch_url's rules.

``fetch_url`` reads plain HTML over httpx; ``browse_page`` (the tool in
``app/tools``) renders a page the way a browser would, for SPAs and
JS-injected content. Three rules govern this module:

- **Public http(s) only.** The URL is validated before the browser even
  launches, and every request the browser then makes -- the navigation, each
  redirect hop, every subresource -- passes a route handler that reuses
  ``web_search._is_blocked_address``, so a redirect or embedded resource
  aimed at a private, loopback or link-local address is aborted before it is
  fetched (including ``file://`` and any other non-http scheme).
- **Nothing identity-shaped.** A fresh incognito context per call: no cookies
  in, no storage, no service workers, downloads off, and everything closed
  again in a ``finally``. There is no session to steal and nothing survives
  the call -- there is no login to carry in the first place.
- **Bounded.** A navigation timeout, a short settle window, and a cap on the
  text that leaves this module.

The browser is launched per call rather than kept warm: an occasional agent
page-read does not justify a resident Chromium, and per-call launch is the
simplest possible lifetime -- all of it inside one function, so a cancelled
or crashed call still closes everything it opened.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.services.web_search import _is_blocked_address

_ALLOWED_SCHEMES = ("http", "https")
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TEXT_CHARS = 100_000
# After DOMContentLoaded, give scripts a moment to fill in content, but do
# not wait for "networkidle" outright: long-polling pages never go idle.
_SETTLE_TIMEOUT_MS = 3_000
_USER_AGENT = None  # default Chromium UA; no spoofing


class BrowserUnavailable(RuntimeError):
    """Playwright or its Chromium download is missing on this server."""


@dataclass
class PageResult:
    """Rendered text plus the provenance the model needs to cite it."""

    url: str  # final URL after redirects
    title: str
    text: str
    status: int | None


def _browsers_root() -> Path:
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override == "0":
        import playwright

        package = Path(playwright.__file__).resolve().parent
        return package / "driver" / "package" / ".local-browsers"
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        return (Path(local) if local else Path.home() / "AppData" / "Local") / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def browser_available() -> bool:
    """True when the playwright package and a Chromium are both present.

    Cheap (import spec + directory glob, no subprocess), so bootstrap calls
    it directly to decide whether browse_page exists at all -- without a
    browser the tool is not registered, the same honest-disable rule the
    Docker sandbox follows.
    """
    if importlib.util.find_spec("playwright") is None:
        return False
    try:
        root = _browsers_root()
        return root.is_dir() and any(root.glob("chromium*"))
    except OSError:
        return False


def _ensure_public(url: str) -> None:
    """The pre-launch gate: same refusals ``_fetch_page`` enforces."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise ValueError("Only http(s) URLs can be fetched.")
    if _is_blocked_address(parsed.hostname):
        raise ValueError("Refusing to fetch a private or loopback address.")


def request_allowed(url: str) -> bool:
    """Would this request URL pass the guard? Pure, so tests can pin it.

    Used by the route handler for every request the browser makes; DNS is
    resolved per call, so an address that resolves privately is refused
    even when the hostname itself looks harmless.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        return False
    return not _is_blocked_address(parsed.hostname)


async def browse(
    url: str, *, timeout_s: float = DEFAULT_TIMEOUT_SECONDS, max_chars: int = MAX_TEXT_CHARS
) -> PageResult:
    """Render ``url`` in a fresh headless Chromium and return its text.

    Raises ``ValueError`` for scheme/SSRF refusals (the tool maps these to a
    DENIED envelope), ``BrowserUnavailable`` when the browser cannot start,
    and the caller's ``TimeoutError`` when navigation blows the budget.
    """
    _ensure_public(url)

    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - gated by browser_available
        raise BrowserUnavailable(f"playwright is not installed: {exc}") from exc

    verdicts: dict[str, bool] = {}
    # Recorded only when the *main* frame is aborted by the guard, so a
    # blocked subresource never masquerades as a refused navigation.
    blocked = {"reason": ""}

    async def _guard(route: Any) -> None:
        request = route.request
        host = urlparse(request.url).hostname or ""
        allowed = verdicts.get(host)
        if allowed is None:
            # getaddrinfo blocks; resolve off-loop so one slow resolver never
            # stalls the server, and only once per host per call.
            allowed = verdicts[host] = await asyncio.to_thread(
                request_allowed, request.url
            )
        if allowed:
            await route.continue_()
            return
        if not blocked["reason"]:
            parsed = urlparse(request.url)
            blocked["reason"] = (
                "private or loopback address"
                if parsed.scheme in _ALLOWED_SCHEMES and parsed.hostname
                else "non-http scheme"
            )
        await route.abort()

    try:
        playwright = await async_playwright().start()
    except Exception as exc:
        raise BrowserUnavailable(f"could not start playwright: {exc}") from exc
    browser = None
    context = None
    try:
        try:
            # Chromium's own sandbox stays on; no --no-sandbox.
            browser = await playwright.chromium.launch(headless=True)
        except Exception as exc:
            raise BrowserUnavailable(f"could not launch chromium: {exc}") from exc
        context = await browser.new_context(
            accept_downloads=False,
            service_workers="block",
            user_agent=_USER_AGENT,
        )
        await context.route("**/*", _guard)
        page = await context.new_page()
        status: int | None = None
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=int(timeout_s * 1000),
            )
            if response is not None:
                status = response.status
        except PlaywrightTimeoutError as exc:
            raise TimeoutError(
                f"The page did not finish loading within {timeout_s:.0f}s."
            ) from exc
        except PlaywrightError as exc:
            if blocked["reason"]:
                raise ValueError(f"Refusing to fetch a {blocked['reason']}.") from exc
            raise ValueError(f"The page failed to load: {exc.message[:200]}") from exc
        try:
            await page.wait_for_load_state("networkidle", timeout=_SETTLE_TIMEOUT_MS)
        except PlaywrightError:
            pass  # never-idle pages: the DOMContentLoaded content is enough
        title = await page.title()
        text = await page.evaluate(
            "() => document.body ? document.body.innerText : ''"
        ) or ""
        if not isinstance(text, str):
            text = str(text)
        return PageResult(
            url=page.url,
            title=title or "",
            text=text[:max_chars],
            status=status,
        )
    finally:
        # Cancelled, timed out or crashed: everything still closes.
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        try:
            await playwright.stop()
        except Exception:
            pass
