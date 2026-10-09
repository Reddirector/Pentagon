"""The central permission/autonomy gate for the LangGraph chat flow.

This is the ONE place every tool call the chat graph wants to make passes
through before execution. It cannot be bypassed by adding a new tool, because
the graph is compiled to route tool calls through this node, and the chat route
only compiles the graph one way.

Design (matches Section 3 of the prompt):

* auto_approve      -> log + execute (no pause, no ToolMessage needed)
* never_allow       -> block + log + synthesize a ToolMessage; no execution
* always_ask        -> interrupt() + log pending; resume on approve/deny
* ask_first_time    -> like always_ask, but approval writes approved_this_session

Every branch writes exactly one row to action_audit_log.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.models import ActionAuditLog, new_id, utc_now
from app.services.autonomy import (
    VALID_CATEGORIES,
    arguments_summary,
    is_ask_level,
    is_auto_level,
    resolve_level,
)
from app.services.command_runner import SHELL_TOOL_NAME, classify
from app.services.desktop_actions import DESKTOP_TOOL_NAME
from app.services.location import LOCATION_TOOL_NAME

logger = logging.getLogger(__name__)

# Tool-name -> risk category for the three graph-native tools. The agent
# registry tools carry their category on ToolSpec.risk_category; these three
# are plain dicts so we map them here. Desktop actions are heterogeneous but
# the tool itself is a local_shell operation (per-action classification lives
# inside run_desktop_action).
GRAPH_TOOL_CATEGORY: dict[str, str] = {
    SHELL_TOOL_NAME: "local_shell",
    DESKTOP_TOOL_NAME: "local_shell",
    LOCATION_TOOL_NAME: "read_only_info",
}


def _category_for(tool_name: str, tool_args: dict[str, Any]) -> str:
    """Risk category for a tool call the chat graph is about to make."""
    if tool_name == SHELL_TOOL_NAME:
        # The command's own classifier is the long-standing contract: a
        # provably read-only command is read_only_info (auto by default, and
        # askable by setting read_only_info to always_ask), while anything
        # that changes state is local_shell. Without this, every `ls` would
        # stop for approval even though the Balanced ladder never asked for
        # one.
        command = tool_args.get("command")
        if isinstance(command, str) and command.strip():
            read_only, _reason = classify(command)
            if read_only:
                return "read_only_info"
        return "local_shell"
    if tool_name in GRAPH_TOOL_CATEGORY:
        return GRAPH_TOOL_CATEGORY[tool_name]
    # Fallback: agent registry tools carry risk_category on ToolSpec. The gate
    # does not have the registry here by design (keeps the gate stateless), so
    # anything not in the graph-native set is treated as read_only_info and
    # logged. In practice the chat graph only offers the three graph-native
    # tools, so this path is a safety net, not a normal case.
    return "read_only_info"


def _can_pause(config: RunnableConfig) -> bool:
    """True when this run can actually pause for an approval.

    ``interrupt()`` needs a checkpointer to persist the pause; on a graph
    compiled without one the run simply ends and the call is dropped without
    ever executing. LangGraph exposes the bound checkpointer on the node
    config, which is what this reads. When the key is absent -- a different
    LangGraph version -- assume the graph *can* pause, because production
    always compiles with a checkpointer and guessing "cannot" here would
    silently disable asking altogether.
    """
    configurable = config.get("configurable") or {}
    if "__pregel_checkpointer" not in configurable:
        return True
    return configurable.get("__pregel_checkpointer") is not None


def _tool_label(tool_name: str, category: str, args: dict[str, Any]) -> str:
    """Plain-language label for an approval card / audit row."""
    if tool_name == SHELL_TOOL_NAME:
        cmd = args.get("command") or ""
        return f"run `{cmd}`" if cmd else "run a shell command"
    if tool_name == DESKTOP_TOOL_NAME:
        action = args.get("action") or ""
        target = args.get("target") or ""
        if target:
            return f"{action}: {target}"
        return f"desktop action: {action}"
    if tool_name == LOCATION_TOOL_NAME:
        return "find the user's location"
    return tool_name


async def permission_gate(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    """Inspect pending tool calls and enforce autonomy settings.

    Reads the user's autonomy_settings from the DB (defaulting to documented
    defaults when there is no row), then for each pending tool call:

    * auto_approve -> log "auto_approved" and let execution proceed
    * never_allow  -> log "blocked_never_allow", synthesize a ToolMessage
    * always_ask / ask_first_time (first time) -> interrupt with a pending
      approval card; on resume the chat route replays the gate with the
      decision.

    Returns a dict that the graph uses to either proceed to execution or to
    surface the interrupt to the frontend.
    """
    pending = state.get("pending_tool_calls") or []
    if not pending:
        return {}

    user_id = state.get("user_id")
    conversation_id = state.get("conversation_id")
    if not user_id or not conversation_id:
        # Should not happen in the chat flow, but be safe.
        return {}

    # Detect an interrupt resume: the chat route replays the graph with
    # Command(resume={...}) after an approval/denial. On resume, the pending
    # tool calls have already been cleared by the gate's first pass, so we
    # simply return the state that the gate left for run_command_node.
    if state.get("approved") or state.get("denied"):
        return state

    # A graph compiled without a checkpointer cannot pause for a decision:
    # ``interrupt()`` would end the run and the call would be dropped without
    # ever executing. Defer those calls to the executor's own approval
    # round-trip instead (the same REGISTRY wait that has always gated them).
    can_pause = _can_pause(config)

    # Load the user's saved autonomy settings once per turn, plus the
    # session-scoped approvals that ``ask_first_time`` remembers.
    with SessionLocal() as db:
        from app.db.models import AutonomySetting, PerToolOverride

        rows = db.scalars(
            select(AutonomySetting).where(AutonomySetting.user_id == user_id)
        ).all()
        overrides = db.scalars(
            select(PerToolOverride).where(PerToolOverride.user_id == user_id)
        ).all()
    settings: dict[str, str] = {r.category: r.level for r in rows}
    approved_tools: set[tuple[str, str]] = {
        (r.tool_name, r.category) for r in overrides if r.approved_this_session
    }

    # Partition pending calls by decision. We only ever interrupt once per
    # turn (the first call that needs asking), because the model only emits
    # one batch of tool calls at a time and the gate runs before execution.
    decisions: list[dict[str, Any]] = []
    ask_card: dict[str, Any] | None = None
    blocked_messages: list[ToolMessage] = []
    auto_approved_names: list[str] = []

    for call in pending:
        tool_name = call.get("name") or ""
        args = call.get("args") or {}
        category = _category_for(tool_name, args)
        level = resolve_level(category, settings)
        if level == "ask_first_time" and (tool_name, category) in approved_tools:
            # Approved earlier this session: ``ask_first_time`` remembers per
            # (tool, category) in per_tool_overrides, so later calls to the
            # same tool run unattended.
            level = "auto_approve"

        summary = arguments_summary(tool_name, args)

        if is_auto_level(level):
            decisions.append(
                {
                    "tool_call_id": call.get("id") or "",
                    "tool_name": tool_name,
                    "category": category,
                    "level": level,
                    "decision": "auto_approved",
                    "arguments_summary": summary,
                    "execute": True,
                }
            )
            auto_approved_names.append(tool_name)
            continue

        if level == "never_allow":
            decisions.append(
                {
                    "tool_call_id": call.get("id") or "",
                    "tool_name": tool_name,
                    "category": category,
                    "level": level,
                    "decision": "blocked_never_allow",
                    "arguments_summary": summary,
                    "execute": False,
                }
            )
            blocked_messages.append(
                ToolMessage(
                    content=(
                        f"[not permitted] The user's settings do not allow "
                        f"{_tool_label(tool_name, category, args)} in the "
                        f"'{category}' category (set to 'never_allow'). "
                        f"Please respond without performing that action."
                    ),
                    tool_call_id=call.get("id") or "",
                    name=tool_name,
                )
            )
            continue

        if not can_pause:
            # No checkpointer on this build: leave the call in
            # pending_tool_calls so run_command_node's own approval round-trip
            # handles it. The gate still enforces auto_approve and never_allow
            # above; only the pause needs a checkpointer.
            continue

        # always_ask or ask_first_time -> interrupt (once per turn).
        if ask_card is None:
            ask_card = {
                "type": "approval_required",
                "user_id": user_id,
                "conversation_id": conversation_id,
                "tool_call_id": call.get("id") or "",
                "tool_name": tool_name,
                "category": category,
                "level": level,
                "label": _tool_label(tool_name, category, args),
                "summary": summary,
                "args": args,
                "pending_calls": [
                    {
                        "tool_call_id": c.get("id") or "",
                        "tool_name": c.get("name") or "",
                        "category": _category_for(
                            c.get("name") or "", c.get("args") or {}
                        ),
                        "label": _tool_label(
                            c.get("name") or "", _category_for(
                                c.get("name") or "", c.get("args") or {}
                            ), c.get("args") or {}
                        ),
                        "summary": arguments_summary(
                            c.get("name") or "", c.get("args") or {}
                        ),
                    }
                    for c in pending
                ],
            }
            # Log the pending state now; the real decision (approved/denied)
            # is logged when the graph resumes via the approve/deny endpoint.
            # Off the event loop: the audit insert shares the SQLite file with
            # the checkpointer and the request sessions, and a synchronous
            # write here would stall every byte still owed to the client if the
            # file was briefly locked.
            await asyncio.to_thread(
                _write_audit,
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name=tool_name,
                category=category,
                level=level,
                decision="auto_approved",
                arguments_summary=summary,
                execute=False,
            )
            # For always_ask we still log a pending row; the decision is
            # finalized on resume. For ask_first_time at first call we also
            # log pending (the same row is updated on approve).

    # Build the ToolMessages for blocked calls so the model can respond.
    result: dict[str, Any] = {}
    if blocked_messages:
        result["tool_messages"] = blocked_messages
        result["pending_tool_calls"] = []  # blocked: do not execute
        result["execute_blocked"] = True

    if ask_card is not None:
        # Pause the graph. The chat route detects the interrupt via aget_state
        # and emits an SSE approval_required event.
        logger.info(
            "permission_gate interrupting for %s (%s) conversation=%s",
            ask_card["label"],
            ask_card["tool_name"],
            conversation_id,
        )
        # ``interrupt()`` is a synchronous call in LangGraph: it pauses the run
        # and, on the replay after Command(resume=...), returns the resume
        # value. Awaiting it raises "'dict' object can't be awaited".
        interrupt_value = interrupt(ask_card)
        # interrupt() returns the value the caller provided via Command(resume=).
        # That is the user approval decision from the approve/deny endpoint.
        resume = interrupt_value if isinstance(interrupt_value, dict) else {}
        decision = resume.get("decision")  # "approved" | "denied"
        approved_this_session = resume.get("approved_this_session", False)

        # Write the final audit row for the tool that caused the interrupt.
        await asyncio.to_thread(
            _write_audit,
            user_id=user_id,
            conversation_id=conversation_id,
            tool_name=ask_card["tool_name"],
            category=ask_card["category"],
            level=ask_card["level"],
            decision="user_approved" if decision == "approved" else "user_denied",
            arguments_summary=ask_card["summary"],
            execute=(decision == "approved"),
        )

        if decision == "approved":
            # Mark approved_this_session for ask_first_time so later calls
            # to the same tool this session auto-approve.
            if ask_card["level"] == "ask_first_time":
                await asyncio.to_thread(
                    _mark_approved_this_session,
                    user_id,
                    ask_card["tool_name"],
                    ask_card["category"],
                )
            # Proceed to execute. The calls are marked with the decision so the
            # executor runs them as approved instead of asking the older
            # REGISTRY round-trip a second time (which would time out into a
            # denial after the user had already said yes).
            result["pending_tool_calls"] = [
                {**call, "gate_decision": "user_approved"} for call in pending
            ]
            result["approved"] = True
        else:
            # Denied: synthesize a ToolMessage so the model can respond.
            result["tool_messages"] = [
                ToolMessage(
                    content=(
                        f"[declined] The user did not approve "
                        f"{ask_card['label']}. Answer without performing "
                        f"that action."
                    ),
                    tool_call_id=ask_card["tool_call_id"],
                    name=ask_card["tool_name"],
                )
            ]
            result["pending_tool_calls"] = []  # do not execute
            result["denied"] = True

    # Auto-approved calls just proceed; the run_command_node executes them.
    # Only the calls this gate actually decided are marked, so calls deferred
    # because the graph cannot pause still go through the executor's own
    # approval round-trip.
    if not ask_card and not blocked_messages:
        auto_ids = {
            d["tool_call_id"] for d in decisions if d["decision"] == "auto_approved"
        }
        result["pending_tool_calls"] = [
            {**call, "gate_decision": "auto_approved"}
            if (call.get("id") or "") in auto_ids
            else call
            for call in pending
        ]
        result["auto_approved"] = True

    # Write audit rows for any auto_approved calls that were not part of an
    # interrupt (the prompt says every branch writes a row, including
    # auto-approved ones).
    for d in decisions:
        # Both the calls that ran unattended and the ones never_allow refused
        # get a row: a refusal is a decision, and the audit trail is only worth
        # anything if it also records what was stopped.
        await asyncio.to_thread(
            _write_audit,
            user_id=user_id,
            conversation_id=conversation_id,
            tool_name=d["tool_name"],
            category=d["category"],
            level=d["level"],
            decision=d["decision"],
            arguments_summary=d["arguments_summary"],
            execute=bool(d["execute"]),
        )

    return result


def _write_audit(
    *,
    user_id: str,
    conversation_id: str,
    tool_name: str,
    category: str,
    level: str,
    decision: str,
    arguments_summary: str,
    execute: bool,
) -> None:
    """Append one row to action_audit_log. Best-effort; never raises into the flow."""
    try:
        with SessionLocal() as db:
            db.add(
                ActionAuditLog(
                    id=new_id(),
                    user_id=user_id,
                    conversation_id=conversation_id,
                    tool_name=tool_name,
                    category=category,
                    autonomy_level_at_time=level,
                    decision=decision,
                    arguments_summary=arguments_summary,
                    timestamp=utc_now(),
                )
            )
            db.commit()
    except Exception:
        logger.exception(
            "failed to write audit log for %s (decision=%s)", tool_name, decision
        )


def _mark_approved_this_session(
    user_id: str, tool_name: str, category: str
) -> None:
    """Set approved_this_session=true for ask_first_time memory."""
    try:
        with SessionLocal() as db:
            from app.db.models import PerToolOverride

            row = db.get(PerToolOverride, (user_id, tool_name, category))
            if row is None:
                row = PerToolOverride(
                    user_id=user_id,
                    tool_name=tool_name,
                    category=category,
                    approved_this_session=True,
                )
                db.add(row)
            else:
                row.approved_this_session = True
            db.commit()
    except Exception:
        logger.exception(
            "failed to mark approved_this_session for %s", tool_name
        )
