"""The agent layer: a tool-using loop above the single-shot chat graph.

Built across phases T0-T13 of the tool-calling upgrade. T0 owns the shared
vocabulary (schemas), the tool registry and tracing; T1 adds the loop and the
native tool-calling LLM layer.
"""

from app.agent.registry import (
    DuplicateToolError,
    RegisteredTool,
    ToolHandler,
    ToolRegistry,
    UnknownToolError,
)
from app.agent.schemas import (
    AgentEvent,
    Budget,
    BudgetExceeded,
    ResultMeta,
    ToolContext,
    ToolError,
    ToolResult,
    ToolSpec,
)
from app.agent.traces import TraceRecorder, redact_args

__all__ = [
    "AgentEvent",
    "Budget",
    "BudgetExceeded",
    "DuplicateToolError",
    "RegisteredTool",
    "ResultMeta",
    "ToolContext",
    "ToolError",
    "ToolHandler",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "TraceRecorder",
    "UnknownToolError",
    "redact_args",
]
