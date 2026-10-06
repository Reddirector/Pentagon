"""Tool execution: timeouts, duplicate guarding, envelope normalization.

T1 runs calls sequentially, in the order the model asked for them, and every
failure comes back as a result envelope rather than an exception -- the loop
must keep the transcript well-formed (every tool call gets a tool message).
T3 layers parallel gather for ``parallel_safe`` tools, caching and retries on
top of the same guard logic.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from app.agent.registry import ToolRegistry, UnknownToolError
from app.agent.schemas import Budget, BudgetExceeded, ToolContext, ToolResult


@dataclass(frozen=True)
class ExecutedCall:
    """One tool call and everything that happened to it."""

    tool: str
    args: dict[str, Any]
    tool_call_id: str
    result: ToolResult
    # ok | error | denied | timeout | reused (T3 adds cached)
    status: str
    elapsed_ms: float


def canonical_key(tool: str, args: dict[str, Any]) -> str:
    """A stable identity for "the same call": name plus order-independent args."""
    return tool + ":" + json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


class Executor:
    """Runs validated tool calls under the turn's budget and duplicate guard."""

    def __init__(self, registry: ToolRegistry, budget: Budget) -> None:
        self.registry = registry
        self.budget = budget
        self._seen: dict[str, ToolResult] = {}

    async def run_one(self, call: dict[str, Any], ctx: ToolContext) -> ExecutedCall:
        """Execute a single call and return its outcome; never raises tool errors."""
        name = str(call.get("name") or "")
        raw_args = call.get("args")
        args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
        call_id = str(call.get("id") or "")
        started = time.perf_counter()

        if raw_args is not None and not isinstance(raw_args, dict):
            result = ToolResult.failure(
                "INVALID_ARGS",
                f"Arguments for {name!r} were not a JSON object.",
                hint="Re-send the call with a JSON object of arguments.",
            )
            return ExecutedCall(name, args, call_id, result, "error", _ms(started))

        key = canonical_key(name, args)
        if key in self._seen:
            earlier = self._seen[key]
            result = ToolResult.success(
                {
                    "note": "already called this turn; reuse this result instead of calling again",
                    "result": earlier.data,
                },
                source_ids=earlier.meta.source_ids,
            )
            return ExecutedCall(name, args, call_id, result, "reused", _ms(started))

        try:
            registered = self.registry.get(name)
        except UnknownToolError as exc:
            result = ToolResult.failure(
                "NOT_FOUND",
                str(exc),
                hint="Pick one of the valid tool names and try again.",
            )
            return ExecutedCall(name, args, call_id, result, "error", _ms(started))

        try:
            self.budget.spend_tool_call()
        except BudgetExceeded as exc:
            result = ToolResult.failure(
                "DENIED",
                f"This call was not run: the turn's tool budget ran out ({exc.what}).",
                hint="Answer the user with what has already been gathered.",
            )
            return ExecutedCall(name, args, call_id, result, "denied", _ms(started))

        try:
            result = await asyncio.wait_for(
                registered.handler(args, ctx), timeout=registered.spec.timeout_s
            )
        except asyncio.TimeoutError:
            result = ToolResult.failure(
                "TIMEOUT",
                f"{name} did not finish within {registered.spec.timeout_s}s.",
                hint="Try a narrower version of the call, or answer without it.",
            )
            return ExecutedCall(name, args, call_id, result, "timeout", _ms(started))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a broken tool must not break the turn
            result = ToolResult.failure(
                "UPSTREAM",
                f"{name} failed: {type(exc).__name__}: {exc}",
                hint="Read the error, change the approach, or answer without this tool.",
            )
            return ExecutedCall(name, args, call_id, result, "error", _ms(started))

        status = "ok" if result.ok else "error"
        if result.ok:
            self._seen[key] = result
        return ExecutedCall(name, args, call_id, result, status, _ms(started))
