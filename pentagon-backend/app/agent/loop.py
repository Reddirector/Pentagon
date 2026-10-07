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
from dataclasses import dataclass, field, replace
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent import capabilities, prompted_tools, verify
from app.agent.executor import ExecutedCall, Executor
from app.agent.injection import detector_note, detect_injection, spotlight
from app.agent.llm import ModelReply, assemble_tool_calls, content_as_text
from app.agent.registry import ToolRegistry
from app.agent.context import ScratchStore, ToolScratchNote
from app.agent.schemas import AgentEvent, Budget, BudgetExceeded, ToolContext, ToolResult
from app.agent.system_prompt import default_system_prompt
from app.agent.traces import TraceRecorder
from app.agent.validate import RepairTracker, validate_call
from app.services.permissions import requires_tool_approval

_FALLBACK_RESULT_CHARS = 20_000

# How long a batch waits on the approval card before silence counts as "no".
# Module-level so tests can shrink it, mirroring ask_user's timeout.
_APPROVAL_TIMEOUT_SECONDS = 300.0


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
    # The default is app/agent/prompts/system.md; callers with a specialized
    # prompt (tests, focused routes) still pass their own.
    system_prompt: str = field(default_factory=default_system_prompt)
    history: list[BaseMessage] = field(default_factory=list)
    # Tool retrieval (T4) passes an explicit selection; None means every tool.
    tool_names: list[str] | None = None
    # T12 routing: when the caller names the model, its cached capability
    # probe decides native vs prompted tool calling. None keeps the native
    # path -- an unprobed model is never punished with the prompted protocol.
    model_id: str | None = None


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
    pause_gate: Any | None = None,
    approval_gate: Any | None = None,
) -> AsyncIterator[AgentEvent]:
    """Run one agent turn; yields the SSE-facing event stream.

    ``approval_gate`` (an :class:`ApprovalGate`) pauses the turn when the
    model asks for a tool that must not run unattended at the user's
    permission level; without a gate those calls are denied outright.
    """
    budget = budget or Budget()
    scratch = ScratchStore()
    shared: dict[str, Any] = {}
    ctx = ToolContext(
        user_id=request.user_id,
        conversation_id=request.conversation_id,
        turn_id=request.turn_id,
        permission_level=request.permission_level,
        cancel=cancel,
        scratch=scratch,
        shared=shared,
        pause_gate=pause_gate,
    )
    recorder = trace or TraceRecorder(request.user_id, request.conversation_id, request.turn_id)
    executor = Executor(registry, budget)
    tracker = RepairTracker()

    schemas = registry.openai_schemas(request.tool_names) if request.tool_names is not None else registry.openai_schemas()
    # T12 capability-aware routing: a cached probe (probed on first use of
    # this model id) picks the tool-calling protocol. A failed probe falls
    # back to native -- the status quo -- and surfaces as the turn's own
    # model errors, never as a silently degraded prompt.
    caps = None
    if request.model_id is not None:
        try:
            caps = capabilities.ensure_probed(model, request.model_id)
        except Exception:
            caps = None
    prompted = caps is not None and not caps.get("native_tools")
    sequential = caps is not None and not caps.get("parallel_tools")
    messages: list[BaseMessage] = [
        SystemMessage(content=request.system_prompt),
        *request.history,
        HumanMessage(content=request.user_message),
    ]
    if prompted:
        selected = (
            request.tool_names if request.tool_names is not None else registry.names()
        )
        specs = [registry.get(name).spec for name in selected]
        messages[0] = SystemMessage(
            content=f"{request.system_prompt}\n\n{prompted_tools.prompt_for_tools(specs)}"
        )
    # Evidence gathered this turn, fed to the grounding verification at the
    # end (T12). Raw ToolResult data, not the compacted text the model saw.
    gathered: list[tuple[str, ToolResult]] = []

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

        # Prompted-capable routing: a model the probe flagged as unable to
        # call tools natively never receives native tool descriptors -- its
        # protocol lives entirely in the system prompt.
        bound = model.bind_tools(schemas) if schemas and not prompted else model
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
        if prompted and reply.text:
            parsed, problems = prompted_tools.parse_tool_calls(reply.text)
            if not parsed and problems:
                # A broken block gets a corrective round, like the native
                # path's INVALID_ARGS repair -- it never becomes prose.
                messages.append(_assistant_message(reply))
                messages.append(
                    ToolMessage(
                        content=(
                            "Your tool_call blocks were malformed: "
                            + "; ".join(problems[:2])
                            + " Reply with exactly one well-formed block: "
                            '<tool_call>{"name": "web_search", "arguments": {"query": "..."}}</tool_call>'
                        ),
                        tool_call_id="prompted_malformed",
                    )
                )
                continue
            if parsed:
                reply = ModelReply(text=reply.text, tool_calls=parsed)
        if sequential and len(reply.tool_calls) > 1:
            # The probe says this model cannot weigh several calls at once.
            # Keep the first: the transcript then honestly contains only the
            # call that was actually made, with a real result. The cap lands
            # after parsing too -- it is about the model, not the transport.
            reply = ModelReply(text=reply.text, tool_calls=reply.tool_calls[:1])

        if not reply.tool_calls:
            break

        messages.append(_assistant_message(reply))
        checked_calls = [
            validate_call(call, _lookup(registry), tracker, registry.names())
            for call in reply.tool_calls
        ]

        # T7 batch approval: one card for every call in this batch that the
        # ladder says must not run unattended. The decision reads only the
        # tool's tier and the user's permission level -- never any content.
        pending_approval = [
            checked
            for checked in checked_calls
            if checked.executable
            and requires_tool_approval(
                registry.get(checked.tool).spec.tier, request.permission_level
            )
        ]
        if pending_approval:
            yield AgentEvent(
                "approval_required",
                {
                    "turn_id": request.turn_id,
                    "calls": [
                        {
                            "id": checked.tool_call_id,
                            "tool": checked.tool,
                            "tier": registry.get(checked.tool).spec.tier,
                            "args": checked.args,
                        }
                        for checked in pending_approval
                    ],
                },
            )
            decision: list[str] | None = None
            if approval_gate is not None:
                decision = await approval_gate.wait_for_decision(
                    _APPROVAL_TIMEOUT_SECONDS
                )
            approved_ids = set(decision) if decision is not None else set()

            def _denial(checked) -> ToolResult:
                if approval_gate is None:
                    return ToolResult.failure(
                        "DENIED",
                        f"{checked.tool} was not run: there is no interactive "
                        "user to approve it right now.",
                        hint=(
                            "This action changes something and needs approval; "
                            "ask the user to approve it before trying again."
                        ),
                    )
                if decision is None:
                    return ToolResult.failure(
                        "DENIED",
                        f"{checked.tool} was not run: the approval request was "
                        "not answered in time.",
                        hint="Treat silence as a no; ask the user again if this is still needed.",
                    )
                return ToolResult.failure(
                    "DENIED",
                    f"{checked.tool} was not run because the user did not approve it.",
                    hint="Do not retry the same call without the user's approval.",
                )

            pending_ids = {checked.tool_call_id for checked in pending_approval}
            checked_calls = [
                replace(
                    checked,
                    executable=False,
                    refusal=_denial(checked),
                )
                if checked.tool_call_id in pending_ids
                and checked.tool_call_id not in approved_ids
                else checked
                for checked in checked_calls
            ]

        for checked in checked_calls:
            if checked.executable:
                yield AgentEvent(
                    "tool_start",
                    {"tool": checked.tool, "id": checked.tool_call_id},
                )
        batch = [
            {"name": checked.tool, "args": checked.args, "id": checked.tool_call_id}
            for checked in checked_calls
            if checked.executable
        ]
        if not batch:
            executed_calls = []
        else:
            # ask_user blocks until an answer arrives, so the question has to
            # reach the wire while the batch is still running: waiting for
            # the tool to finish would hide the question from the only channel
            # that could answer it. The batch runs as its own task and the
            # shared dict is watched while it does; a batch without an ask in
            # flight simply completes on the first wait.
            run_batch = asyncio.ensure_future(executor.run_many(batch, ctx))
            announced = False
            try:
                while not run_batch.done():
                    question = shared.get("ask_user")
                    if (
                        isinstance(question, dict)
                        and not announced
                        and not question.get("answered")
                        and not question.get("announced")
                    ):
                        question["announced"] = True
                        announced = True
                        yield AgentEvent(
                            "ask_user",
                            {
                                "question": question.get("question", ""),
                                "options": list(question.get("options") or []),
                                "answered": False,
                            },
                        )
                    await asyncio.wait({run_batch}, timeout=0.1)
                executed_calls = run_batch.result()
            except BaseException:
                run_batch.cancel()
                raise
        executed_by_id = {
            executed.tool_call_id: executed for executed in executed_calls
        }
        for checked in checked_calls:
            executed = executed_by_id.get(checked.tool_call_id)
            if executed is not None:
                gathered.append((checked.tool, executed.result))
                spec = registry.get(executed.tool).spec if registry.has(executed.tool) else None
                max_chars = spec.max_result_chars if spec else _FALLBACK_RESULT_CHARS
                content = executed.result.compact(max_chars)
                untrusted = spec is not None and spec.untrusted
                # Scan before wrapping so a hit is found even when the text
                # is about to be truncated or parked in the scratch store.
                flags = detect_injection(content) if untrusted else []
                # Oversized results go to the scratch store whole; the model
                # sees a head excerpt plus a handle it can read_result().
                stored = scratch.store(executed.tool, content)
                if stored is not None:
                    head = content[:ScratchStore.head_chars()]
                    if untrusted:
                        # Spotlight the excerpt only: the note's paging
                        # instruction is ours and stays outside the markers.
                        head = spotlight(executed.tool, head)
                    content = ToolScratchNote(
                        executed.tool, head, stored
                    ).as_content()
                elif untrusted:
                    # T7 provenance: third-party text arrives spotlighted so
                    # its boundaries are explicit.
                    content = spotlight(executed.tool, content)
                if flags:
                    content = detector_note(flags) + "\n" + content
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
            if checked.tool == "update_plan" and isinstance(shared.get("plan"), list):
                yield AgentEvent("plan", {"steps": shared["plan"]})
            if (
                checked.tool == "ask_user"
                and isinstance(shared.get("ask_user"), dict)
                and not shared["ask_user"].get("answered")
                and not shared["ask_user"].get("announced")
            ):
                # Only reached when the question never got announced live
                # (the tool failed before the first watch tick, e.g. no gate):
                # one announcement per question, never a duplicate.
                yield AgentEvent("ask_user", shared["ask_user"])
            if checked.tool == "create_artifact" and isinstance(
                shared.get("artifact"), dict
            ):
                yield AgentEvent("artifact", shared["artifact"])

    # T12 grounding verification: only meaningful when this turn actually
    # gathered sources, and never allowed to break the turn it observes.
    verification = None
    if reply is not None and reply.text.strip() and gathered:
        sources = verify.gather_sources(gathered)
        if sources:
            verification = verify.verify_answer(reply.text, sources)
            if not verification.ok:
                try:
                    rewritten = await verify.repair(
                        model,
                        answer=reply.text,
                        sources=sources,
                        verification=verification,
                        budget=budget,
                    )
                    if rewritten.strip() and rewritten != reply.text:
                        reply = ModelReply(text=rewritten, tool_calls=[])
                        verification = verify.verify_answer(reply.text, sources)
                        yield AgentEvent(
                            "status",
                            {
                                "message": "The answer was revised to match the sources it cites.",
                                # The tokens already streamed the old text;
                                # this is the answer of record now, and the
                                # route/UI replace the bubble with it.
                                "answer": rewritten,
                            },
                        )
                except BudgetExceeded:
                    # No budget for a rewrite: keep the answer and let the
                    # verdict on the done event carry the finding.
                    pass
                except Exception:
                    # Verification is an observer: a model or parse failure
                    # leaves the original answer untouched.
                    pass
            recorder.record_tool_call(
                budget.tool_calls,
                "verify",
                {
                    "sources": verification.sources,
                    "problems": verification.problems[:3],
                },
                "ok" if verification.ok else "error",
            )

    if reply is not None and not reply.text.strip() and not budget.out_of_time():
        # The final answer must be prose for the user, never nothing.
        yield AgentEvent(
            "error",
            {"message": "The model stopped without answering. Please try again."},
        )
    recorder.flush()
    done_payload: dict[str, Any] = {
        "turn_id": request.turn_id,
        "llm_calls": budget.llm_calls,
        "tool_calls": budget.tool_calls,
    }
    if verification is not None:
        done_payload["verification"] = verification.as_dict()
    yield AgentEvent("done", done_payload)
