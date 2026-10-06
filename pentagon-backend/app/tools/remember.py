"""remember: keep one durable fact about the user past this conversation.

Persistence is a state change, so the tool sits at ``write`` -- the T7
ladder means Restricted and Balanced ask the user first and only Trusted
stores cold. The description keeps the model honest about *what* belongs
here: standing facts, not transient task state (update_plan owns that) and
nothing the user asked to forget.
"""

from __future__ import annotations

from typing import Any

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.db.session import SessionLocal
from app.services import memory_service

TOOL_SPEC = ToolSpec(
    name="remember",
    description=(
        "Store one durable fact about the user or their work so it outlives"
        " this conversation: a preference, a standing constraint, a project"
        " or identity detail they state. Use for things worth keeping beyond"
        " today; use update_plan for transient task state, and store nothing"
        " the user asked you to forget. Storing the identical text twice is a"
        " no-op -- call recall first if you are unsure it is already kept."
        " Saving changes persistent state, so it is approval-gated. The user"
        " reviews and deletes memories in Settings. Returns the stored id."
        ' Example: {"text": "Prefers metric units in all answers",'
        ' "label": "preference"}.'
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "The fact to remember, written complete enough to make"
                    " sense on its own in a later conversation."
                ),
            },
            "label": {
                "type": "string",
                "description": (
                    "Optional short tag grouping the memory, e.g."
                    " 'preference', 'project', 'contact'."
                ),
            },
        },
        "required": ["text"],
    },
    tier="write",
    timeout_s=10,
    cacheable=False,
    idempotent=True,
    parallel_safe=False,
    tags=(
        "remember",
        "memory",
        "save",
        "store",
        "persistent",
        "preference",
        "fact",
        "recall",
    ),
)


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "text must be a non-empty description of the fact to keep.",
            hint='Example: {"text": "Works in UTC+5:30, answers in metric"}.',
        )
    if len(text) > memory_service.MAX_MEMORY_CHARS:
        return ToolResult.failure(
            "INVALID_ARGS",
            f"text is {len(text)} chars; a memory holds"
            f" {memory_service.MAX_MEMORY_CHARS}.",
            hint="Keep the fact short and self-contained; split it if needed.",
        )
    label = args.get("label") or ""
    if not isinstance(label, str):
        return ToolResult.failure(
            "INVALID_ARGS",
            "label must be a short string when given.",
            hint="Omit it, or pass e.g. 'preference'.",
        )
    try:
        with SessionLocal() as db:
            memory, created = memory_service.store_memory(
                db, user_id=ctx.user_id, text=text, label=label
            )
            payload = memory_service.serialize(memory)
    except memory_service.MemoryLimitError as exc:
        return ToolResult.failure(
            "UPSTREAM",
            f"Cannot store this memory: {exc}.",
            hint="Delete old memories in Settings to make room.",
        )
    except Exception as exc:
        return ToolResult.failure(
            "UPSTREAM",
            f"The memory store is unavailable ({type(exc).__name__}).",
            hint="Nothing was saved; try again once the database responds.",
        )
    payload["stored"] = created
    if not created:
        payload["note"] = "an identical memory already existed"
    return ToolResult.success(payload)
