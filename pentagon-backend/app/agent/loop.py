"""The agent loop: model -> tools -> model ... -> final prose.

Streaming goes straight from the model to the caller -- unlike the older
chat-graph path, tool results never enter the token stream, because the loop
appends them to the transcript between model calls instead of surfacing graph
state. The loop stops when the model answers in prose, or when the budget
forces a wrap-up: one final call with tools disabled that answers from what
was gathered. A turn never ends silently.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.executor import ExecutedCall, Executor
from app.agent.llm import ModelReply, assemble_tool_calls, content_as_text
from app.agent.registry import ToolRegistry
from app.agent.schemas import AgentEvent, Budget, BudgetExceeded, ToolContext
from app.agent.traces import TraceRecorder
from app.agent.validate import RepairTracker, validate_call

_FALLBACK_RESULT_CHARS = 20_000


def _lookup(registry: ToolRegistry):
    """Name -> spec or None: the shape validate_call's unknown-name check wants."""

    def lookup(name: str):
        try:
            return registry.get(name).spec
        except Exception:
            return None

    return lookup


@dataclass(frozen=True)
class TurnRequest:
    """Everything one turn needs besides the model and the registry."""

    user_id: str
    conversation_id: str
    turn_id: str
    permission_level: int
    user_message: str
    system_prompt: str
    history: list[BaseMessage] = field(default_factory=list)
    # Tool retrieval (T4) passes an explicit selection; None means every tool.
    tool_names: list[str] | None = None


def _assistant_message(reply: ModelReply) -> AIMessage:
    """The assistant turn as the transcript must store it.

    A call whose arguments did not parse into a dict is stored with empty
    args -- the transcript must stay serializable for the next request -- and
    the tool message the validator produces is what tells the model why.
    """
    calls = [
        {
            "name": call["name"],
            "args": call["args"] if isinstance(call["args"], dict) else {},
            "id": call["id"],
        }
        for call in reply.tool_calls
    ]
    return AIMessage(content=reply.text, tool_calls=calls)


def _summary_of(executed: ExecutedCall) -> str:
    """A short, human-readable line for the timeline event."""
    if executed.result.ok:
        text = executed.result.data if isinstance(executed.result.data, str) else ""
        return text[:200] or "done"
    if executed.result.error is not None:
        return executed.result.error.message[:200]
    return "done"


async def run_turn(
    registry: ToolRegistry,
    model: Any,
    request: TurnRequest,
    *,
    budget: Budget | None = None,
    trace: TraceRecorder | None = None,
    cancel: asyncio.Event | None = None,
) -> AsyncIterator[AgentEvent]:
    """Run one agent turn; yields the SSE-facing event stream."""
    budget = budget or Budget()
    ctx = ToolContext(
        user_id=request.user_id,
        conversation_id=request.conversation_id,
        turn_id=request.turn_id,
        permission_level=request.permission_level,
        cancel=cancel,
    )
    recorder = trace or TraceRecorder(request.user_id, request.conversation_id, request.turn_id)
    executor = Executor(registry, budget)
    tracker = RepairTracker()

    schemas = registry.openai_schemas(request.tool_names) if request.tool_names is not None else registry.openai_schemas()
    messages: list[BaseMessage] = [
        SystemMessage(content=request.system_prompt),
        *request.history,
        HumanMessage(content=request.user_message),
    ]

    reply: ModelReply | None = None
    while True:
        if schemas and (
            budget.llm_calls >= budget.max_llm_calls - 1
            or budget.tool_calls >= budget.max_tool_calls
            or budget.out_of_time()
        ):
            # Reserve the final LLM call for a tools-disabled wrap-up: the
            # model answers from what was gathered instead of looping on.
            schemas = []
            yield AgentEvent(
                "status",
                {"message": "The turn's budget is nearly spent; wrapping up with what was gathered."},
            )
        try:
            budget.spend_llm_call()
        except BudgetExceeded as exc:
            yield AgentEvent(
                "error",
                {
                    "message": (
                        "This turn used its whole model budget before producing "
                        f"an answer ({exc.what}). Please try again or narrow the request."
                    )
                },
            )
            break

        bound = model.bind_tools(schemas) if schemas else model
        chunks: list[Any] = []
        parts: list[str] = []
        async for chunk in bound.astream(messages):
            text = content_as_text(chunk.content)
            if text:
                parts.append(text)
                yield AgentEvent("token", {"content": text})
            chunks.append(chunk)
        reply = ModelReply(
            text="".join(parts),
            tool_calls=assemble_tool_calls(chunks) if chunks else [],
        )

        if not reply.tool_calls:
            break

        messages.append(_assistant_message(reply))
        for call in reply.tool_calls:
            checked = validate_call(call, _lookup(registry), tracker, registry.names())
            if checked.executable:
                yield AgentEvent(
                    "tool_start",
                    {"tool": checked.tool, "id": checked.tool_call_id},
                )
                executed = await executor.run_one(
                    {"name": checked.tool, "args": checked.args, "id": checked.tool_call_id}, ctx
                )
                spec = registry.get(executed.tool).spec if registry.has(executed.tool) else None
                max_chars = spec.max_result_chars if spec else _FALLBACK_RESULT_CHARS
                content = executed.result.compact(max_chars)
                status = executed.status
                elapsed = executed.elapsed_ms
            else:
                assert checked.refusal is not None
                content = checked.refusal.compact(4_000)
                status = "error"
                elapsed = 0.0
            messages.append(
                ToolMessage(
                    content=content,
                    tool_call_id=checked.tool_call_id,
                )
            )
            recorder.record_tool_call(
                budget.tool_calls - 1,
                checked.tool,
                checked.args,
                status,
                duration_ms=elapsed,
            )
            yield AgentEvent(
                "tool_result",
                {
                    "tool": checked.tool,
                    "id": checked.tool_call_id,
                    "status": status,
                    "ok": status == "ok",
                    "summary": content[:200],
                    "elapsed_ms": elapsed,
                },
            )

    if reply is not None and not reply.text.strip() and not budget.out_of_time():
        # The final answer must be prose for the user, never nothing.
        yield AgentEvent(
            "error",
            {"message": "The model stopped without answering. Please try again."},
        )
    recorder.flush()
    yield AgentEvent(
        "done",
        {
            "turn_id": request.turn_id,
            "llm_calls": budget.llm_calls,
            "tool_calls": budget.tool_calls,
        },
    )
