"""The tool registry: every tool the agent can call, with its full metadata.

Registration is the single gate a tool passes through, so structural mistakes
(a malformed schema, a missing description, a name the model cannot say) fail
at import time with a message that names the problem, not deep inside a turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.agent.schemas import ToolContext, ToolResult, ToolSpec


class ToolHandler(Protocol):
    """What a tool implementation must look like: args in, envelope out."""

    async def __call__(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


class DuplicateToolError(ValueError):
    """Two tools claimed the same name."""


class UnknownToolError(KeyError):
    """The model named a tool that does not exist.

    Carries the valid names so the validation layer can answer with a
    corrective tool message instead of a bare failure.
    """

    def __init__(self, name: str, valid: list[str]) -> None:
        self.valid = valid
        shown = ", ".join(sorted(valid)) if valid else "(none registered)"
        super().__init__(f"Unknown tool {name!r}. Valid tools: {shown}")


@dataclass(frozen=True)
class RegisteredTool:
    spec: ToolSpec
    handler: ToolHandler


class ToolRegistry:
    """Name -> spec + handler. The app holds one; tools register at import."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        problems = spec.validation_errors()
        if problems:
            raise ValueError(f"tool {spec.name!r} spec is invalid: {'; '.join(problems)}")
        if spec.name in self._tools:
            raise DuplicateToolError(f"a tool named {spec.name!r} is already registered")
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def get(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownToolError(name, list(self._tools)) from None

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [registered.spec for registered in self._tools.values()]

    def openai_schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        """OpenAI-compatible tool descriptors, ready for ``bind_tools``.

        ``names`` selects a subset (tool retrieval, Section 5.4); the default
        is every registered tool.
        """
        chosen = names if names is not None else self.names()
        return [
            {
                "type": "function",
                "function": {
                    "name": self.get(name).spec.name,
                    "description": self.get(name).spec.description,
                    "parameters": self.get(name).spec.parameters,
                },
            }
            for name in chosen
        ]
