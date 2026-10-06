"""T9: browse_page renders public pages and refuses everything else.

Unit tests pin the rules that must hold without a browser: every private,
loopback, link-local, metadata or non-http URL is refused by the same guard
that protects fetch_url, the refusal surfaces as an honest DENIED envelope,
and without Playwright/Chromium the tool is not registered at all. One live
test renders a real page end to end; it skips when the browser is missing.
"""

import asyncio

import pytest

from app.agent.bootstrap import build_registry
from app.agent.schemas import ToolContext
from app.services import browser
from app.tools import browse_page

_BROWSABLE = browser.browser_available()
live = pytest.mark.skipif(not _BROWSABLE, reason="playwright/chromium not installed")


def _ctx() -> ToolContext:
    return ToolContext(
        user_id="u", conversation_id="c", turn_id="t", permission_level=2
    )


def _run(args: dict) -> object:
    return asyncio.run(browse_page.run(args, _ctx()))


# --- the guard, pinned as pure rules ----------------------------------------


def test_request_allowed_pins_the_public_http_rules():
    assert browser.request_allowed("https://example.com/path?q=1")
    for blocked in (
        "file:///etc/passwd",
        "javascript:alert(1)",
        "ftp://example.com/file",
        "http://127.0.0.1:8080/admin",
        "http://localhost:3000/",
        "http://10.0.0.5/",
        "http://192.168.1.1/router",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://0.0.0.0/",
        "https://2130706433/",  # decimal-encoded 127.0.0.1
    ):
        assert not browser.request_allowed(blocked), blocked


def test_ensure_public_refuses_before_anything_starts():
    for url in (
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
    ):
        with pytest.raises(ValueError):
            browser._ensure_public(url)
    browser._ensure_public("https://example.com/")  # does not raise


# --- the tool's contract ------------------------------------------------------


def test_spec_is_read_tier_and_marked_untrusted():
    spec = browse_page.TOOL_SPEC
    assert spec.tier == "read"
    assert spec.untrusted is True
    assert spec.cacheable is True
    assert "javascript" in spec.tags


def test_registry_hides_browse_page_without_a_browser(monkeypatch):
    monkeypatch.setattr(browser, "browser_available", lambda: False)
    assert "browse_page" not in build_registry().names()
    monkeypatch.setattr(browser, "browser_available", lambda: True)
    assert "browse_page" in build_registry().names()


def test_run_fails_honestly_without_a_browser(monkeypatch):
    monkeypatch.setattr(browser, "browser_available", lambda: False)

    async def _boom(*_a, **_k):
        raise AssertionError("must not launch a browser it does not have")

    monkeypatch.setattr(browser, "browse", _boom)
    result = _run({"url": "https://example.com"})
    assert result.ok is False
    assert result.error.code == "DENIED"
    assert "fetch_url" in result.error.hint


def test_run_validates_the_url_argument(monkeypatch):
    monkeypatch.setattr(browser, "browser_available", lambda: True)

    async def _boom(*_a, **_k):
        raise AssertionError("validation must finish before any launch")

    monkeypatch.setattr(browser, "browse", _boom)
    for args in ({}, {"url": ""}, {"url": "   "}, {"url": 123}):
        result = _run(args)
        assert result.ok is False, args
        assert result.error.code == "INVALID_ARGS"


def test_run_maps_an_ssrf_refusal_to_denied(monkeypatch):
    async def _refuse(url, **_kw):
        raise ValueError("Refusing to fetch a private or loopback address.")

    monkeypatch.setattr(browser, "browse", _refuse)
    result = _run({"url": "http://10.1.2.3/"})
    assert result.ok is False
    assert result.error.code == "DENIED"
    assert "private" in result.error.message


def test_run_maps_timeout_unavailable_and_http_errors(monkeypatch):
    async def _slow(url, **_kw):
        raise TimeoutError("The page did not finish loading within 30s.")

    monkeypatch.setattr(browser, "browse", _slow)
    result = _run({"url": "https://example.com/"})
    assert result.ok is False and result.error.code == "TIMEOUT"

    async def _down(url, **_kw):
        raise browser.BrowserUnavailable("could not launch chromium: boom")

    monkeypatch.setattr(browser, "browse", _down)
    result = _run({"url": "https://example.com/"})
    assert result.ok is False and result.error.code == "DENIED"

    async def _missing(url, **_kw):
        return browser.PageResult(
            url="https://example.com/gone", title="", text="", status=404
        )

    monkeypatch.setattr(browser, "browse", _missing)
    result = _run({"url": "https://example.com/gone"})
    assert result.ok is False and result.error.code == "UPSTREAM"
    assert "404" in result.error.message
    assert "gone" in result.error.hint


# --- live rendering -------------------------------------------------------------


@live
def test_live_browse_renders_a_public_page():
    result = _run({"url": "https://example.com"})
    assert result.ok is True
    assert result.data["status"] == 200
    assert result.data["title"] == "Example Domain"
    assert "documentation examples" in result.data["text"]
    assert result.data["rendered"] is True
    assert result.data["url"].startswith("https://example.com")
