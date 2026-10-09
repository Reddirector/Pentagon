"""update_plan: publish and keep current the visible task checklist.

For multi-step work the model states its plan instead of hiding it. The plan
streams to the UI as a collapsible checklist; the model updates it after each
major result and when something fails. It carries no side effect outside the
turn, so it is a read-tier tool that runs unattended.
"""

from __future__ import annotations

from typing import Any

from app.agent.planner import PlanError, normalize_plan, plan_summary
from app.agent.schemas import ToolContext, ToolResult, ToolSpec

TOOL_SPEC = ToolSpec(
    name="update_plan",
    description=(
        "Show or update the task plan the user sees as a checklist. Use for"
        " multi-step work -- research, comparisons, anything with 3 or more"
        " steps -- and after each major result; do not use it for simple"
        " questions. Send the full step list every time with each step's status:"
        " pending, in_progress (exactly one), done, or blocked. Maximum 7 steps."
        " Example: {\"steps\": [{\"text\": \"Find the sources\", \"status\": \"done\"},"
        " {\"text\": \"Compare the prices\", \"status\": \"in_progress\"}]}."
    ),
    parameters={
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "description": "The full plan, 1-7 steps, each {text, status}.",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "done", "blocked"],
                        },
                    },
                    "required": ["text"],
                },
            }
        },
        "required": ["steps"],
    },
    tier="read",

    risk_category="read_only_info",    timeout_s=5,
    cacheable=False,
    idempotent=True,
    parallel_safe=False,
    tags=("plan", "steps", "task", "checklist", "progress"),
)


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    try:
        steps = normalize_plan(args.get("steps"))
    except PlanError as exc:
        return ToolResult.failure(
            "INVALID_ARGS",
            str(exc),
            hint=(
                "Send the full list, 1-7 steps of {text, status}, with exactly one"
                " step marked in_progress."
            ),
        )
    shared = getattr(ctx, "shared", None)
    if isinstance(shared, dict):
        shared["plan"] = steps
    return ToolResult.success({"plan": steps, "summary": plan_summary(steps)})
