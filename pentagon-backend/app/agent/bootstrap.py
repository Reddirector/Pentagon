"""Wire the registry the agent runs with."""

from __future__ import annotations

from app.agent.registry import ToolRegistry
from app.services import browser, sandbox_runner
from app.tools import (
    ask_user,
    browse_page,
    calculator,
    create_artifact,
    fetch_url,
    get_current_time,
    python_exec,
    read_document,
    read_result,
    search_documents,
    update_plan,
    web_search,
)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(get_current_time.TOOL_SPEC, get_current_time.run)
    registry.register(calculator.TOOL_SPEC, calculator.run)
    registry.register(web_search.TOOL_SPEC, web_search.run)
    registry.register(fetch_url.TOOL_SPEC, fetch_url.run)
    registry.register(search_documents.TOOL_SPEC, search_documents.run)
    registry.register(read_document.TOOL_SPEC, read_document.run)
    registry.register(read_result.TOOL_SPEC, read_result.run)
    registry.register(update_plan.TOOL_SPEC, update_plan.run)
    registry.register(ask_user.TOOL_SPEC, ask_user.run)
    # T9: the JS-rendering browser needs Playwright plus its Chromium, so it
    # exists only when they do; fetch_url covers plain documents without them.
    if browser.browser_available():
        registry.register(browse_page.TOOL_SPEC, browse_page.run)
    # T8: code execution exists only when the Docker sandbox does. Without
    # Docker the tools are simply not registered -- there is no host-code
    # path to fall back to (python_exec would DENIED anyway if it raced a
    # daemon that died after startup).
    if sandbox_runner.sandbox_available():
        registry.register(python_exec.TOOL_SPEC, python_exec.run)
        registry.register(create_artifact.TOOL_SPEC, create_artifact.run)
    return registry
