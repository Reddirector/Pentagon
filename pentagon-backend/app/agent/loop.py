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
import hashlib
import json
import logging
import re
import uuid

logger = logging.getLogger(__name__)
from dataclasses import dataclass, field, replace
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent import capabilities, prompted_tools, verify
from app.agent.executor import ExecutedCall, Executor
from app.agent.injection import detector_note, detect_injection, spotlight
from app.agent.llm import ModelReply, assemble_tool_calls, content_as_text
from app.agent.policy import audit_decision, load_policy
from app.agent.registry import ToolRegistry
from app.agent.context import ContextBudget, ScratchStore, ToolScratchNote, compact_history
from app.agent.schemas import AgentEvent, Budget, BudgetExceeded, ToolContext, ToolResult
from app.agent.system_prompt import default_system_prompt
from app.agent.traces import TraceRecorder
from app.agent.validate import RepairTracker, validate_call
from app.services.autonomy import is_ask_level
from app.services.rate_limiter import RateLimitTimeout

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


def _action_fingerprint(tool_name: str, args: dict[str, Any]) -> str:
    serialized = json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{tool_name}\0{serialized}".encode()).hexdigest()


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
    policy = load_policy(request.user_id, request.permission_level)
    denied_actions: set[str] = set()

    schemas = registry.openai_schemas(request.tool_names) if request.tool_names is not None else registry.openai_schemas()
    # T12 capability-aware routing: a cached probe (probed on first use of
    # this model id) picks the tool-calling protocol. A failed probe falls
    # back to native -- the status quo -- and surfaces as the turn's own
    # model errors, never as a silently degraded prompt.
    caps = None
    if request.model_id is not None:
        try:
            caps = await capabilities.ensure_probed_async(model, request.model_id)
        except RateLimitTimeout:
            raise
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
    context_limit = 32_000
    if caps is not None and isinstance(caps.get("max_context"), int):
        context_limit = max(4_096, caps["max_context"])
    context_budget = ContextBudget(max_context=context_limit)
    # Evidence gathered this turn, fed to the grounding verification at the
    # end (T12). Raw ToolResult data, not the compacted text the model saw.
    gathered: list[tuple[str, ToolResult]] = []

    reply: ModelReply | None = None
    while True:
        _DOC_PATTERNS = (
            re.compile(r"\b(?:compile|generate|create|build|make|draft|write|export|produce)\b.*\b(?:pdf|docx|word|document|report|sheet|spreadsheet|excel|xlsx|slides|presentation|pptx|file)\b", re.I),
            re.compile(r"\b(?:into|as|in)\s+(?:a\s+)?(?:pdf|docx|word(?:\s+doc)?|spreadsheet|excel|xlsx|slides|presentation|pptx|html)\b", re.I),
            re.compile(r"\b(?:give\s+me|send\s+me|provide)\s+(?:a\s+)?(?:pdf|spreadsheet|presentation|slide\s+deck)\b", re.I),
        )
        is_doc_requested = any(p.search(request.user_message) for p in _DOC_PATTERNS)
        doc_already_generated = any(tool == "document_generation" for tool, _ in gathered)

        if (
            schemas
            and is_doc_requested
            and not doc_already_generated
            and budget.max_llm_calls > 4
            and (budget.llm_calls == budget.max_llm_calls - 2 or budget.tool_calls >= budget.max_tool_calls - 1)
        ):
            doc_schema = [s for s in schemas if s.get("function", {}).get("name") == "document_generation"]
            if doc_schema:
                schemas = doc_schema
                messages.append(
                    SystemMessage(
                        content="Budget nearing limit: You must now invoke document_generation to generate the requested file deliverable."
                    )
                )
                yield AgentEvent(
                    "status",
                    {"message": "Budget nearing limit; prioritizing generation of the requested document deliverable."},
                )

        has_briefing_prompt = any(
            isinstance(m, HumanMessage) and "All requested file deliverables and research are compiled" in getattr(m, "content", "")
            for m in messages
        )

        if schemas and (
            has_briefing_prompt
            or budget.llm_calls >= budget.max_llm_calls - 1
            or budget.tool_calls >= budget.max_tool_calls
            or budget.out_of_time()
        ):
            # Reserve the final LLM call for a tools-disabled wrap-up: the
            # model answers from what was gathered instead of looping on.
            schemas = []
            if prompted:
                messages.append(
                    SystemMessage(
                        content="All tools are now disabled. Provide your final response directly from what was gathered."
                    )
                )
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
        messages = compact_history(
            messages,
            keep_recent=6,
            max_history_tokens=int(context_budget.max_context * 0.35),
        )
        logger.info("[AGENT-LOOP] Model call %d/%d (tools: %d, msgs: %d)", budget.llm_calls, budget.max_llm_calls, len(schemas) if schemas else 0, len(messages))
        bound = model.bind_tools(schemas) if schemas and not prompted else model
        chunks: list[Any] = []
        parts: list[str] = []

        async def _consume_stream():
            async for chunk in bound.astream(messages):
                text = content_as_text(chunk.content)
                if text:
                    parts.append(text)
                chunks.append(chunk)

        try:
            await asyncio.wait_for(_consume_stream(), timeout=40.0)
            reply = ModelReply(
                text="".join(parts),
                tool_calls=assemble_tool_calls(chunks) if chunks else [],
            )
        except Exception as stream_err:
            logger.warning("[AGENT-LOOP] Streaming failed (%s); falling back to non-streaming ainvoke", stream_err)
            try:
                full_res = await asyncio.wait_for(bound.ainvoke(messages), timeout=35.0)
                text = content_as_text(full_res.content)
                tc = getattr(full_res, "tool_calls", None) or assemble_tool_calls([full_res])
                reply = ModelReply(
                    text=text or "",
                    tool_calls=tc if tc else [],
                )
            except Exception as ainvoke_err:
                logger.warning("[AGENT-LOOP] ainvoke failed (%s); retrying with compacted messages", ainvoke_err)
                lean_msgs = compact_history(messages, keep_recent=4, max_history_tokens=1800)
                try:
                    full_res = await asyncio.wait_for(bound.ainvoke(lean_msgs), timeout=30.0)
                    text = content_as_text(full_res.content)
                    tc = getattr(full_res, "tool_calls", None) or assemble_tool_calls([full_res])
                    reply = ModelReply(text=text or "", tool_calls=tc if tc else [])
                except Exception as final_err:
                    logger.error("[AGENT-LOOP] Model execution failed after retry: %s", final_err)
                    if gathered:
                        reply = ModelReply(
                            text=(
                                "I have compiled and delivered your requested documents and data models. "
                                "You can review the interactive previews and download the deliverable files above."
                            ),
                            tool_calls=[],
                        )
                    else:
                        raise
        logger.info("[AGENT-LOOP] Reply: tool_calls=%s text_len=%d", [c.get("name") for c in reply.tool_calls], len(reply.text))
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

        if not reply.tool_calls and reply.text:
            # Fallback: check if model emitted a function call in text completion (e.g. Llama 3.2 text function call)
            raw_t = reply.text.strip()
            call_match = re.search(r'\{\s*"name"\s*:\s*"([a-zA-Z0-9_-]+)"\s*,\s*"(?:parameters|arguments|args)"\s*:\s*', raw_t)
            if call_match:
                tool_name = call_match.group(1)
                if tool_name in registry.names():
                    start_brace = call_match.start()
                    end_brace = raw_t.rfind("}") + 1
                    if end_brace > start_brace:
                        candidate_json = raw_t[start_brace:end_brace]
                        try:
                            parsed_payload = json.loads(candidate_json)
                        except Exception:
                            try:
                                import ast
                                parsed_payload = ast.literal_eval(candidate_json)
                            except Exception:
                                parsed_payload = None
                        if isinstance(parsed_payload, dict):
                            args_obj = (
                                parsed_payload.get("parameters")
                                or parsed_payload.get("arguments")
                                or parsed_payload.get("args")
                                or {}
                            )
                            if isinstance(args_obj, dict):
                                reply = ModelReply(
                                    text="",
                                    tool_calls=[{
                                        "name": tool_name,
                                        "args": args_obj,
                                        "id": f"call_{uuid.uuid4().hex[:8]}",
                                    }],
                                )

        # Deduplicate multiple document_generation calls in the same turn by keeping the most complete one per format
        doc_calls = [c for c in reply.tool_calls if c.get("name") == "document_generation"]
        if len(doc_calls) > 1:
            by_format: dict[str, Any] = {}
            for call in doc_calls:
                fmt = str((call.get("args") or {}).get("format") or "").lower()
                content_len = len(str((call.get("args") or {}).get("content") or ""))
                if fmt not in by_format or content_len > len(str((by_format[fmt].get("args") or {}).get("content") or "")):
                    by_format[fmt] = call
            deduped_doc_calls = list(by_format.values())
            non_doc_calls = [c for c in reply.tool_calls if c.get("name") != "document_generation"]
            reply = ModelReply(text=reply.text, tool_calls=[*non_doc_calls, *deduped_doc_calls])

        # If document_generation already succeeded this turn for a format, do not rerun duplicate document generations for that format
        succeeded_doc_formats = set()
        for tool, res in gathered:
            if tool == "document_generation" and res.ok:
                fmt = (res.data or {}).get("format") if isinstance(res.data, dict) else None
                if fmt:
                    succeeded_doc_formats.add(str(fmt).lower())
                else:
                    succeeded_doc_formats.add("__generic__")

        if succeeded_doc_formats:
            user_msg_lower = request.user_message.lower()
            filtered_calls = []
            for c in reply.tool_calls:
                if c.get("name") == "document_generation":
                    c_fmt = str((c.get("args") or {}).get("format") or "").lower()
                    if c_fmt in succeeded_doc_formats:
                        continue
                    fmt_aliases = {
                        "xlsx": ["xlsx", "excel", "spreadsheet", "workbook", "sheets"],
                        "pptx": ["pptx", "powerpoint", "presentation", "slide deck", "slides"],
                        "docx": ["docx", "word", "document"],
                        "pdf": ["pdf"],
                        "html": ["html", "website", "web page", "webpage"],
                        "md": ["markdown file", ".md", "md file"],
                    }
                    aliases = fmt_aliases.get(c_fmt, [c_fmt])
                    if not any(alias in user_msg_lower for alias in aliases):
                        continue
                elif c.get("name") == "create_artifact":
                    continue
                filtered_calls.append(c)
            reply = ModelReply(text=reply.text, tool_calls=filtered_calls)

        # If image_generation already succeeded this turn, do not rerun duplicate image generations
        already_has_img = any(tool == "image_generation" and res.ok for tool, res in gathered)
        if already_has_img:
            reply = ModelReply(
                text=reply.text,
                tool_calls=[c for c in reply.tool_calls if c.get("name") != "image_generation"],
            )

        # If update_plan already succeeded this turn, do not rerun duplicate plan updates
        has_update_plan = any(tool == "update_plan" and res.ok for tool, res in gathered)
        if has_update_plan:
            reply = ModelReply(
                text=reply.text,
                tool_calls=[c for c in reply.tool_calls if c.get("name") != "update_plan"],
            )

        if sequential and len(reply.tool_calls) > 1:
            # The probe says this model cannot weigh several calls at once.
            # Keep the first: the transcript then honestly contains only the
            # call that was actually made, with a real result. The cap lands
            # after parsing too -- it is about the model, not the transport.
            reply = ModelReply(text=reply.text, tool_calls=reply.tool_calls[:1])

        if not reply.tool_calls:
            # This is the final answer prose. Sanitize any tool meta-commentary leaks and prompt echoes.
            clean_text = reply.text.strip()
            clean_text = re.sub(
                r"^(?:(?:output\s+)?clean\s+markdown\s+directly\s+without\s+calling\s+any\s+tools\.?|markdown\s+directly\s+without\s+calling\s+any\s+tools\.?)\s*",
                "",
                clean_text,
                flags=re.IGNORECASE,
            ).strip()
            # Normalize callout blocks and model artifact syntax
            clean_text = re.sub(
                r"(?:Callout(?:\s+Blocks?)?|Callouts?)\s*[-=>:]+\s*(\[!?(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\])",
                r"\n\n> \g<1>",
                clean_text,
                flags=re.IGNORECASE,
            )
            clean_text = re.sub(r">\s*\\\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\\\]", r"> [!\g<1>]", clean_text)
            clean_text = re.sub(r"(> \[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\])\s*:\s*", r"\g<1>\n> ", clean_text)
            clean_text = re.sub(r"\n:\s*", r"\n> ", clean_text)
            clean_text = re.sub(r"\s+Conclusion\s*\n", r"\n\n### Conclusion\n", clean_text)
            is_leak = bool(re.search(
                r"(?:the functions?|the tools?)\s+(?:call\s+)?(?:that|was|can|is|are|\"[a-zA-Z0-9_-]+\")|we need to call the functions|to answer the user's prompt, we need to call|we can use the function|function call is not possible|user has declined",
                clean_text,
                re.IGNORECASE,
            )) or "function call is not possible" in clean_text.lower() or "user has declined" in clean_text.lower()
            if is_leak and not gathered and budget.llm_calls < budget.max_llm_calls - 2:
                # The model hallucinated meta-commentary about tools without invoking any!
                # Trigger an immediate corrective repair turn to force native tool invocation.
                messages.append(_assistant_message(reply))
                messages.append(
                    ToolMessage(
                        content=(
                            "Do NOT explain or list functions in prose. "
                            "You must invoke the required tool (such as web_search, document_generation, or image_generation) directly using native function calling right now."
                        ),
                        tool_call_id="call_repair",
                    )
                )
                continue

            if is_leak:
                clean_text = ""

            # Check what deliverables were requested vs what has been gathered
            user_msg_lower = request.user_message.lower()
            generated_doc_formats: set[str] = set()
            for tool, res in gathered:
                if tool == "document_generation" and res.ok and isinstance(res.data, dict):
                    fmt = (res.data.get("format") or "").lower()
                    if fmt:
                        generated_doc_formats.add(fmt)

            has_generated_img = any(tool == "image_generation" and res.ok for tool, res in gathered)

            pending_deliverables: list[str] = []
            if any(w in user_msg_lower for w in ["pdf", ".pdf"]) and "pdf" not in generated_doc_formats:
                pending_deliverables.append("document_generation(format='pdf', title='...')")
            if any(w in user_msg_lower for w in ["pptx", ".pptx", "presentation", "slide deck", "slides"]) and "pptx" not in generated_doc_formats:
                pending_deliverables.append("document_generation(format='pptx', title='...')")
            if any(w in user_msg_lower for w in ["xlsx", ".xlsx", "spreadsheet", "workbook", "excel"]) and "xlsx" not in generated_doc_formats:
                pending_deliverables.append("document_generation(format='xlsx', title='...')")
            if any(w in user_msg_lower for w in ["docx", ".docx", "word document"]) and "docx" not in generated_doc_formats:
                pending_deliverables.append("document_generation(format='docx', title='...')")
            if any(w in user_msg_lower for w in ["html", ".html", "website", "web page", "web app", "landing page", "portal"]) and "html" not in generated_doc_formats:
                pending_deliverables.append("document_generation(format='html', title='...')")
            if any(w in user_msg_lower for w in ["image", "picture", "visual", "illustration", "diagram"]) and not has_generated_img:
                pending_deliverables.append("image_generation(prompt='...')")

            has_pending_prompt = any(
                isinstance(m, HumanMessage) and "You still need to produce the following requested deliverables" in getattr(m, "content", "")
                for m in messages
            )

            if pending_deliverables and budget.llm_calls < budget.max_llm_calls - 2 and not has_pending_prompt:
                messages.append(_assistant_message(reply))
                messages.append(
                    HumanMessage(
                        content=(
                            f"Progress update: You still need to produce the following requested deliverables: "
                            f"{', '.join(pending_deliverables)}. "
                            "Invoke the appropriate tools now to generate them before writing your final briefing."
                        )
                    )
                )
                continue

            has_briefing_prompt = any(
                isinstance(m, HumanMessage) and "All requested file deliverables and research are compiled" in getattr(m, "content", "")
                for m in messages
            )
            if not clean_text and gathered and not has_briefing_prompt and budget.llm_calls < budget.max_llm_calls - 1:
                # Tools were executed, but the model has not written its comprehensive executive briefing yet.
                # Prompt the model to produce its full markdown briefing with tables, embedded images, and callouts.
                messages.append(_assistant_message(reply))
                messages.append(
                    HumanMessage(
                        content=(
                            "All requested file deliverables and research are compiled. "
                            "Now write your comprehensive executive briefing for the user in chat. "
                            "Write fully realized, professional content with concrete data and analysis. "
                            "Do not include any placeholders such as '[insert ...]' or 'TODO'. "
                            "Include any requested comparison matrix tables, embed gathered web photos and AI concept images using `![Caption](url)`, "
                            "and summarize key takeaways with callout blocks. Output clean markdown directly without calling any tools."
                        )
                    )
                )
                continue

            if not clean_text:
                has_doc = any(tool == "document_generation" and res.ok for tool, res in gathered) or any(
                    isinstance(m, ToolMessage) and ("format" in getattr(m, "content", "") or "filename" in getattr(m, "content", ""))
                    for m in messages
                )
                if has_doc:
                    doc_formats: set[str] = set()
                    for tool, res in gathered:
                        if tool == "document_generation" and res.ok and isinstance(res.data, dict):
                            fmt = (res.data.get("format") or "").lower()
                            if fmt:
                                doc_formats.add(fmt)
                    if not doc_formats:
                        for m in messages:
                            if isinstance(m, ToolMessage):
                                content_str = getattr(m, "content", "")
                                if isinstance(content_str, str) and '"format":' in content_str:
                                    m_fmt = re.search(r'"format"\s*:\s*"([a-zA-Z0-9]+)"', content_str)
                                    if m_fmt:
                                        doc_formats.add(m_fmt.group(1).lower())

                    labels = []
                    if "html" in doc_formats:
                        labels.append("interactive web application (.html)")
                    if "docx" in doc_formats:
                        labels.append("formal Word document specification (.docx)")
                    if "pdf" in doc_formats:
                        labels.append("comprehensive research report (.pdf)")
                    if "pptx" in doc_formats:
                        labels.append("executive presentation deck (.pptx)")
                    if "xlsx" in doc_formats:
                        labels.append("financial model spreadsheet (.xlsx)")

                    if labels:
                        clean_text = (
                            f"I have compiled and generated your requested deliverables: {', '.join(labels)}. "
                            "You can review the interactive previews, slide carousel, and structured document tables above, and download all files directly."
                        )
                    else:
                        clean_text = (
                            "I have compiled and generated your requested document deliverables. "
                            "You can preview and download the files above."
                        )
                elif is_leak:
                    clean_text = "I have completed processing your request."
                else:
                    clean_text = reply.text.strip()

            if clean_text:
                yield AgentEvent("token", {"content": clean_text})
                reply = ModelReply(text=clean_text, tool_calls=[])
            break

        messages.append(_assistant_message(reply))
        checked_calls = [
            validate_call(call, _lookup(registry), tracker, registry.names())
            for call in reply.tool_calls
        ]

        # Use the same per-category policy as the chat graph. A tool's tier is
        # metadata for the approval card; it cannot override `never_allow`.
        policy_levels: dict[str, str] = {}
        decisions: dict[str, str] = {}
        pending_approval = []
        adjusted_calls = []
        for checked in checked_calls:
            if not checked.executable:
                adjusted_calls.append(checked)
                continue
            spec = registry.get(checked.tool).spec
            configured_level, effective_level = policy.level_for(spec)
            policy_levels[checked.tool_call_id] = configured_level
            fingerprint = _action_fingerprint(checked.tool, checked.args)
            if fingerprint in denied_actions:
                decisions[checked.tool_call_id] = "user_denied"
                adjusted_calls.append(
                    replace(
                        checked,
                        executable=False,
                        refusal=ToolResult.failure(
                            "DENIED",
                            f"{checked.tool} was already denied in this turn and was not run again.",
                            hint="Do not retry an action the user declined during this turn.",
                        ),
                    )
                )
            elif effective_level == "never_allow":
                decisions[checked.tool_call_id] = "blocked_never_allow"
                adjusted_calls.append(
                    replace(
                        checked,
                        executable=False,
                        refusal=ToolResult.failure(
                            "DENIED",
                            f"{checked.tool} is blocked by the user's {spec.risk_category} setting.",
                            hint="Answer without this action; the user has disabled this category.",
                        ),
                    )
                )
            elif is_ask_level(effective_level):
                pending_approval.append(checked)
                adjusted_calls.append(checked)
            elif effective_level == "auto_approve":
                decisions[checked.tool_call_id] = "auto_approved"
                adjusted_calls.append(checked)
            else:
                decisions[checked.tool_call_id] = "blocked_never_allow"
                adjusted_calls.append(
                    replace(
                        checked,
                        executable=False,
                        refusal=ToolResult.failure("DENIED", "The tool's autonomy setting is invalid."),
                    )
                )
        checked_calls = adjusted_calls

        first_time_approved: list[Any] = []
        if pending_approval:
            if approval_gate is not None:
                approval_gate.begin([checked.tool_call_id for checked in pending_approval])
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
            for checked in pending_approval:
                approved = decision is not None and checked.tool_call_id in approved_ids
                decisions[checked.tool_call_id] = "user_approved" if approved else "user_denied"
                if approved and policy_levels.get(checked.tool_call_id) == "ask_first_time":
                    first_time_approved.append(registry.get(checked.tool).spec)
                elif not approved:
                    denied_actions.add(_action_fingerprint(checked.tool, checked.args))

        # Write the decision before execution. A DB failure must stop the tool
        # rather than produce an unrecorded external or local side effect.
        for checked in checked_calls:
            decision_name = decisions.get(checked.tool_call_id)
            if decision_name is None:
                continue
            audit_decision(
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                spec=registry.get(checked.tool).spec,
                args=checked.args,
                level=policy_levels[checked.tool_call_id],
                decision=decision_name,
            )
        for spec in first_time_approved:
            policy.remember(spec)

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
                    "ok": status in ("ok", "cached", "reused"),
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
            if checked.tool in {"document_generation", "image_generation"} and isinstance(
                shared.get("generated_file"), dict
            ):
                # Announced once, like the artifact above: the record travels
                # without its bytes, so the client renders a file card whose
                # preview and download are fetched on demand.
                file_info = shared.pop("generated_file")
                yield AgentEvent("generated_file", file_info)
                yield AgentEvent("file", file_info)

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
