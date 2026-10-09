"""recall: search the user's own memories when a question may depend on them.

Retrieval is keyword overlap over the user's rows (see memory_service) --
deterministic, no embedding call. The description tells the model when to
reach for it: preferences, standing constraints, previously established
facts, before assuming a blank slate.
"""

from __future__ import annotations

from typing import Any

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.db.session import SessionLocal
from app.services import memory_service

TOOL_SPEC = ToolSpec(
    name="recall",
    description=(
        "Search the user's stored memories (facts previously kept with"
        " remember). Reach for it when the answer may depend on who they are"
        " or how they like things done: preferences, standing constraints,"
        " project or contact details, decisions made in earlier conversations."
        " Not for current events, documents, or this conversation's own"
        " history. Returns matching memories with ids and dates, best match"
        " first; if nothing matches, the store has nothing on the topic."
        ' Example: {"query": "units preference"}.'
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look for, in a few natural words.",
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"Most memories to return (1-{memory_service.MAX_RECALL_LIMIT});"
                    f" default {memory_service.DEFAULT_RECALL_LIMIT}."
                ),
            },
        },
        "required": ["query"],
    },
    tier="read",

    risk_category="read_only_info",    timeout_s=10,
    cacheable=True,
    cache_ttl_s=60,
    idempotent=True,
    parallel_safe=True,
    tags=(
        "recall",
        "memory",
        "memories",
        "remember",
        "preference",
        "profile",
        "fact",
        "saved",
        "past",
    ),
)


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "query must be a non-empty string.",
            hint='Describe the topic, e.g. {"query": "meeting times"}.',
        )
    limit = args.get("limit", memory_service.DEFAULT_RECALL_LIMIT)
    if (
        isinstance(limit, bool)
        or not isinstance(limit, (int, float))
        or not 1 <= limit <= memory_service.MAX_RECALL_LIMIT
    ):
        return ToolResult.failure(
            "INVALID_ARGS",
            f"limit must be a number between 1 and"
            f" {memory_service.MAX_RECALL_LIMIT}.",
            hint="Drop it for the default.",
        )
    try:
        with SessionLocal() as db:
            rows = memory_service.search_memories(
                db, user_id=ctx.user_id, query=query, limit=int(limit)
            )
            memories = [memory_service.serialize(row) for row in rows]
    except Exception as exc:
        return ToolResult.failure(
            "UPSTREAM",
            f"The memory store is unavailable ({type(exc).__name__}).",
            hint="Nothing was lost; try again shortly.",
        )
    return ToolResult.success(
        {"query": query.strip(), "count": len(memories), "memories": memories}
    )
