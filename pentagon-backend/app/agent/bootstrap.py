"""Wire the core tools into a registry.

One function builds the registry the agent loop runs with. Tools register
here -- never at their own import time -- so importing a tool module has no
side effects and tests can build a registry with any subset.
"""

from __future__ import annotations

from app.agent.registry import ToolRegistry
from app.tools import calculator, get_current_time


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(get_current_time.TOOL_SPEC, get_current_time.run)
    registry.register(calculator.TOOL_SPEC, calculator.run)
    return registry
