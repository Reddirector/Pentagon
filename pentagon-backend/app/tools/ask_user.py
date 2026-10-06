"""ask_user: the agent stops and asks instead of guessing.

Called when a request is genuinely ambiguous or a needed value is missing and
a wrong guess would waste real effort or cause side effects. The handler
awaits the turn's pause gate; the UI shows the question with quick-reply
chips, and the user's answer resolves the same turn. It is a read-tier tool
(it has no external effect) but not parallel-safe: nothing else should run
while the user is being asked.
"""

from __future__ import annotations

from typing import Any

from app.agent.schemas import AskUserGate, ToolContext, ToolResult, ToolSpec

_ASK_TIMEOUT_SECONDS = 300.0

TOOL_SPEC = ToolSpec(
    name="ask_user",
    description=(
        "Ask the user one clarifying question and pause for their answer. Use"
        " only when a request is genuinely ambiguous or a needed value is"
        " missing and a wrong guess would waste real effort or cause side"
        " effects -- which calendar, which repository, which of two named"
        " options. Do not use it when a reasonable assumption would work: state"
        " the assumption and continue instead. The turn resumes with the"
        " user's answer. Example: a question naming the two repos, with"
        " options ['frontend', 'backend']."
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "One concrete question, under 500 characters."},
            "options": {
                "type": "array",
                "description": "Up to 6 short quick-reply choices, or omit for free text.",
                "items": {"type": "string"},
            },
        },
        "required": ["question"],
    },
    tier="read",
    timeout_s=310,
    cacheable=False,
    idempotent=False,
    parallel_safe=False,
    tags=("ask", "clarify", "question", "missing", "ambiguous"),
)


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    question = args.get("question")
    if not isinstance(question, str) or not question.strip() or len(question) > 500:
        return ToolResult.failure(
            "INVALID_ARGS",
            "question must be a non-empty string of at most 500 characters.",
            hint="Ask one concrete question, e.g. 'Which calendar should I use?'",
        )
    question = question.strip()
    options = args.get("options")
    if options is not None:
        if (
            not isinstance(options, list)
            or len(options) > 6
            or not all(isinstance(option, str) and option.strip() for option in options)
        ):
            return ToolResult.failure(
                "INVALID_ARGS",
                "options must be a list of up to 6 short strings.",
                hint="Leave options out for a free-form answer.",
            )
        options = [option.strip() for option in options]

    shared = getattr(ctx, "shared", None)
    if isinstance(shared, dict):
        shared["ask_user"] = {"question": question, "options": options or [], "answered": False}

    gate: AskUserGate | None = getattr(ctx, "pause_gate", None)
    if gate is None:
        # No interactive channel (evals, probes): fail honestly and fast, the
        # model is told to state an assumption and continue instead of hanging.
        return ToolResult.failure(
            "UPSTREAM",
            "There is no interactive user to answer right now.",
            hint="State your best assumption in one line and continue.",
        )

    answer = await gate.wait_for_answer(_ASK_TIMEOUT_SECONDS)
    if answer is None:
        return ToolResult.failure(
            "UPSTREAM",
            "The user did not answer in time.",
            hint="Continue with your best assumption, stated in one line.",
        )
    if isinstance(shared, dict):
        shared["ask_user"]["answered"] = True
    return ToolResult.success(
        {"question": question, "options": options or [], "answer": answer}
    )
