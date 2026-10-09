"""Typed vocabulary for the agent layer.

Everything the agent loop, the executor and the tools pass between each other
is defined here once: the tool spec and its permission tier, the result
envelope every tool returns, the per-turn budget, and the event the loop
yields toward the SSE route. One module owning the shapes is what lets the
mock LLM, the eval harness and the production loop agree on a single contract.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.autonomy import RiskCategory, VALID_CATEGORIES

Tier = Literal["read", "write", "destructive", "external_send"]

ErrorCode = Literal[
    "TIMEOUT",
    "INVALID_ARGS",
    "NOT_FOUND",
    "DENIED",
    "RATE_LIMITED",
    "UPSTREAM",
]

EventName = Literal[
    "conversation",
    "metadata",
    "token",
    "status",
    "plan",
    "tool_start",
    "tool_result",
    "approval_required",
    "artifact",
    "ask_user",
    "done",
    "error",
]

_VALID_TIERS = {"read", "write", "destructive", "external_send"}


class BudgetExceeded(RuntimeError):
    """A turn tried to spend past its budget.

    Carries *what* ran out so the loop can make its one final answer call
    with a truthful reason instead of ending silently.
    """

    def __init__(self, what: str) -> None:
        self.what = what
        super().__init__(f"turn budget exhausted: {what}")


@dataclass(frozen=True)
class ToolSpec:
    """The full contract of one tool: schema, permission tier, cost, safety.

    ``tier`` decides whether the executor runs it unattended or raises an
    approval card (read auto-runs; destructive and external_send always ask).
    ``parameters`` is a JSON-schema object -- it goes verbatim into the
    OpenAI-style tool descriptor the model sees.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    tier: Tier = "read"
    timeout_s: int = 30
    cacheable: bool = False
    cache_ttl_s: int = 300
    max_result_chars: int = 20_000
    parallel_safe: bool = True
    idempotent: bool = True
    needs_connection: str | None = None
    tags: tuple[str, ...] = ()
    # True when this tool's results carry third-party text (web pages,
    # uploads, search snippets): the loop spotlights those results and runs
    # the injection detector over them before they enter the model's context.
    # It is presentation policy only and never affects the permission tier.
    untrusted: bool = False
    # One of the six fixed Pentagon risk categories. Every tool MUST declare
    # one so the permission_gate can classify it. An invalid or missing value
    # fails registration (and therefore startup) with a message naming the tool.
    risk_category: RiskCategory = "read_only_info"

    def validation_errors(self) -> list[str]:
        """Structural problems a registration must not ship with."""
        problems: list[str] = []
        if (
            not self.name
            or self.name != self.name.lower()
            or not self.name.replace("_", "").isalnum()
        ):
            problems.append(f"name {self.name!r} must be lower snake_case")
        if not self.description.strip():
            problems.append("description must not be empty")
        if not isinstance(self.parameters, dict) or self.parameters.get("type") != "object":
            problems.append("parameters must be a JSON schema object with type=object")
        if self.tier not in _VALID_TIERS:
            problems.append(f"tier {self.tier!r} is not one of {sorted(_VALID_TIERS)}")
        if self.timeout_s <= 0:
            problems.append("timeout_s must be positive")

            if self.risk_category not in VALID_CATEGORIES:
                problems.append(f"risk_category {self.risk_category!r} is not one of {sorted(VALID_CATEGORIES)} (tool {self.name!r} needs exactly one)")
        if self.risk_category not in VALID_CATEGORIES:
            problems.append(
                f"risk_category {self.risk_category!r} is not one of "
                f"{sorted(VALID_CATEGORIES)} (tool {self.name!r} needs exactly one)"
            )
        return problems


@dataclass(frozen=True)
class ToolContext:
    """What a tool invocation knows about the turn it runs inside.

    ``scratch`` is the turn's store for oversized tool results (see
    ``app.agent.context``); read_result pages through it. ``shared`` is the
    loop's per-turn dict where update_plan publishes the checklist and
    ask_user records its question. ``pause_gate`` is how ask_user stops the
    turn until the user answers.
    """

    user_id: str
    conversation_id: str
    turn_id: str
    permission_level: int
    cancel: asyncio.Event | None = None
    scratch: Any = None
    shared: Any = None
    pause_gate: Any = None


class AskUserGate:
    """The pause/answer channel between ask_user and the answering HTTP route.

    The tool handler awaits ``wait_for_answer``; the route resolves it with
    ``provide`` when the user answers. A timeout returns ``None`` so the tool
    can fail with a hint instead of hanging the turn forever; user Stop cancels
    the awaiting task from outside (executor-level cancellation).
    """

    def __init__(self) -> None:
        self._future: asyncio.Future | None = None

    async def wait_for_answer(self, timeout: float) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        self._future = loop.create_future()
        try:
            return await asyncio.wait_for(self._future, timeout)
        except asyncio.TimeoutError:
            return None

    def provide(self, answer: dict[str, Any]) -> bool:
        if self._future is not None and not self._future.done():
            self._future.set_result(answer)
            return True
        return False


class ApprovalGate:
    """The pause between "the model wants to act" and "the user allows it".

    The loop emits one ``approval_required`` event for the whole batch and
    awaits ``wait_for_decision``; the answering route resolves it with
    ``provide`` listing the approved call ids. An unanswered wait returns
    ``None`` (a timeout is a "no" -- silence never runs an action), an
    explicit empty list means the user declined everything, and a missing
    gate means there is nobody to ask at all.
    """

    def __init__(self) -> None:
        self._future: asyncio.Future | None = None
        self._early: list[str] | None = None

    async def wait_for_decision(self, timeout: float) -> list[str] | None:
        # A route reacting to the approval_required event may answer before
        # the loop has resumed into this wait; accept that answer instead of
        # losing it to the race.
        if self._early is not None:
            ids, self._early = self._early, None
            return ids
        loop = asyncio.get_running_loop()
        self._future = loop.create_future()
        try:
            return await asyncio.wait_for(self._future, timeout)
        except asyncio.TimeoutError:
            return None

    def provide(self, approved_ids: list[str]) -> bool:
        if self._future is None:
            self._early = list(approved_ids)
            return True
        if not self._future.done():
            self._future.set_result(list(approved_ids))
            return True
        return False


class ResultMeta(BaseModel):
    source_ids: list[str] = Field(default_factory=list)
    truncated: bool = False
    handle: str | None = None
    elapsed_ms: float | None = None


class ToolError(BaseModel):
    code: ErrorCode
    message: str
    hint: str | None = None


class ToolResult(BaseModel):
    """The envelope every tool returns (upgrade prompt Section 5.5).

    The model never sees a bare string. Successes carry data plus metadata
    (source ids, truncation, a paging handle); failures carry a code, a
    message written *for the model* saying what happened, and a hint at what
    to try instead.
    """

    ok: bool
    data: Any = None
    meta: ResultMeta = Field(default_factory=ResultMeta)
    error: ToolError | None = None

    @classmethod
    def success(cls, data: Any = None, **meta: Any) -> "ToolResult":
        return cls(ok=True, data=data, meta=ResultMeta(**meta))

    @classmethod
    def failure(
        cls, code: ErrorCode, message: str, hint: str | None = None
    ) -> "ToolResult":
        return cls(ok=False, error=ToolError(code=code, message=message, hint=hint))

    def compact(self, max_chars: int) -> str:
        """The JSON actually handed to the model: compact, and capped.

        When the payload would exceed ``max_chars``, the serialized data is
        cut and ``meta.truncated`` flips true, so the model knows to page for
        the rest (read_result, T5) instead of assuming it saw everything.
        """
        payload = self.model_dump(exclude_none=True)
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(text) <= max_chars:
            return text
        cut = text[: max(max_chars - 80, 0)]
        payload["data"] = cut
        payload["meta"] = {**payload.get("meta", {}), "truncated": True}
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


@dataclass
class Budget:
    """Per-turn spend caps. All configurable; the loop checks before each call.

    When a cap is hit the loop stops calling tools and makes one final
    answer call with tools disabled -- it never ends a turn silently.
    """

    max_llm_calls: int = 8
    max_tool_calls: int = 16
    max_seconds: float = 120.0
    llm_calls: int = 0
    tool_calls: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def spend_llm_call(self) -> None:
        if self.llm_calls >= self.max_llm_calls:
            raise BudgetExceeded(f"llm_calls >= {self.max_llm_calls}")
        self.llm_calls += 1

    def spend_tool_call(self) -> None:
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded(f"tool_calls >= {self.max_tool_calls}")
        self.tool_calls += 1

    def time_left(self) -> float:
        return self.max_seconds - (time.monotonic() - self.started_at)

    def out_of_time(self) -> bool:
        return self.time_left() <= 0


@dataclass(frozen=True)
class AgentEvent:
    """One element of the turn's SSE stream (upgrade prompt Section 19)."""

    name: EventName
    payload: dict[str, Any] = field(default_factory=dict)
