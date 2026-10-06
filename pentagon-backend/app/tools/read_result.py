"""read_result: page or search a tool result that was too big for the context.

When a fetch or search returns more text than the context should hold, the
result is stored whole and the model sees a head excerpt plus a handle. This
tool is the scroll: ``offset``/``limit`` to page forward, ``search`` to find
the lines that matter without reading everything.
"""

from __future__ import annotations

from typing import Any

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.agent.context import ScratchStore

TOOL_SPEC = ToolSpec(
    name="read_result",
    description=(
        "Read more of a large tool result that came back with a handle"
        " (res_...). Use when a web_search or fetch_url result was truncated:"
        " page forward with offset, or jump straight to the relevant lines with"
        " search. Do not use it for results that were shown in full. Returns the"
        " requested text window and whether more remains. Example:"
        ' {"handle": "res_0001_12345", "offset": 6000, "limit": 4000}.'
    ),
    parameters={
        "type": "object",
        "properties": {
            "handle": {"type": "string", "description": "The res_... handle from a truncated result."},
            "offset": {"type": "integer", "description": "Character offset to read from. Defaults to 0."},
            "limit": {"type": "integer", "description": "Characters to read, up to 8000. Defaults to 4000."},
            "search": {"type": "string", "description": "Instead of paging, return matching lines."},
        },
        "required": ["handle"],
    },
    tier="read",
    timeout_s=5,
    cacheable=False,
    idempotent=True,
    parallel_safe=True,
    tags=("read", "result", "handle", "page", "truncated", "large"),
    # The stored text a handle pages back is recycled third-party content.
    untrusted=True,
)


def _store_for(ctx: ToolContext) -> ScratchStore:
    """The turn-scope scratch store; the loop installs it on the context."""
    store = getattr(ctx, "scratch", None)
    if store is None:
        raise RuntimeError("read_result used outside an agent turn with a scratch store")
    return store


async def run(args: dict[str, Any], ctx) -> ToolResult:
    handle = args.get("handle")
    if not isinstance(handle, str) or not handle.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "handle must be the res_... identifier from a truncated result.",
            hint="Copy the handle exactly as the earlier tool result showed it.",
        )
    store = _store_for(ctx)
    query = args.get("search")
    if isinstance(query, str) and query.strip():
        found = store.search(handle.strip(), query)
        if found is None:
            return ToolResult.failure(
                "NOT_FOUND",
                f"No stored result with handle {handle!r}.",
                hint="The handle may have expired; re-run the original tool call.",
            )
        return ToolResult.success(found)
    offset, limit = args.get("offset", 0), args.get("limit", 4_000)
    for raw, name in ((offset, "offset"), (limit, "limit")):
        if isinstance(raw, str) and raw.strip().isdigit():
            if name == "offset":
                offset = int(offset)
            else:
                limit = int(limit)
    if not isinstance(offset, int) or offset < 0:
        return ToolResult.failure(
            "INVALID_ARGS", "offset must be a non-negative integer.", hint="Start at 0."
        )
    if not isinstance(limit, int) or not 1 <= limit <= 8_000:
        return ToolResult.failure(
            "INVALID_ARGS", "limit must be between 1 and 8000 characters.", hint="4000 is a good page."
        )
    page = store.page(handle.strip(), offset, limit)
    if page is None:
        return ToolResult.failure(
            "NOT_FOUND",
            f"No stored result with handle {handle!r}.",
            hint="The handle may have expired; re-run the original tool call.",
        )
    return ToolResult.success(page)
