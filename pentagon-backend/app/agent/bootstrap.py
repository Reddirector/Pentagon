"""Wire the registry the agent runs with."""

from __future__ import annotations

from app.agent.registry import ToolRegistry
from app.tools import (
    calculator,
    fetch_url,
    get_current_time,
    read_document,
    search_documents,
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
    return registry
