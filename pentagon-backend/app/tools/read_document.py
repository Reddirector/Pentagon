"""read_document: page through one uploaded file's chunks in order.

Search returns the closest chunks wherever they sit; sometimes the model needs
a contiguous stretch -- a table that spans chunks, a clause building over
pages. Chunk ids are ordered as stored, so offset+limit walks the document.
"""

from __future__ import annotations

from typing import Any

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.services.document_store import (
    _client,
    collection_name_for_conversation,
)

TOOL_SPEC = ToolSpec(
    name="read_document",
    description=(
        "Read one uploaded document from the beginning, in order, by chunk"
        " offset. Use after search_documents when the matched chunk is clearly"
        " the middle of something longer -- a table, a clause, a list -- and you"
        " need the surrounding text. Do not use it to find where a topic is:"
        " search first, then read around the hit. Returns the requested chunks"
        " with their 0-based positions. Example:"
        ' {"filename": "contract.pdf", "offset": 4, "limit": 3}.'
    ),
    parameters={
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "The uploaded file's name, as search_documents reported it.",
            },
            "offset": {
                "type": "integer",
                "description": "0-based chunk position to start from. Defaults to 0.",
            },
            "limit": {
                "type": "integer",
                "description": "How many chunks to read (1-10). Defaults to 5.",
            },
        },
        "required": ["filename"],
    },
    tier="read",

    risk_category="read_only_info",    timeout_s=20,
    cacheable=True,
    cache_ttl_s=120,
    idempotent=True,
    parallel_safe=True,
    tags=("documents", "files", "read", "page", "pdf"),
    untrusted=True,
)


def _list_document_chunks(collection, filename: str, offset: int, limit: int) -> list[dict[str, Any]]:
    """Chunk texts for one file, in stored order, as a page window."""
    got = collection.get(include=["documents", "metadatas"])
    documents = got.get("documents") or []
    metadatas = got.get("metadatas") or []
    rows = [
        {
            "position": position,
            "content": documents[position] if position < len(documents) else "",
            "filename": (metadatas[position] or {}).get("filename", "document"),
        }
        for position in range(len(documents))
    ]
    matching = [row for row in rows if row["filename"] == filename]
    return matching[offset : offset + limit]


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    filename = args.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "filename must be the name of an uploaded document.",
            hint="Use the filename search_documents reported.",
        )
    filename = filename.strip()
    offset, limit = args.get("offset", 0), args.get("limit", 5)
    if isinstance(offset, str) and offset.strip().isdigit():
        offset = int(offset)
    if isinstance(limit, str) and limit.strip().isdigit():
        limit = int(limit)
    if not isinstance(offset, int) or offset < 0:
        return ToolResult.failure(
            "INVALID_ARGS", "offset must be a non-negative integer.", hint="Start at 0."
        )
    if not isinstance(limit, int) or not 1 <= limit <= 10:
        return ToolResult.failure(
            "INVALID_ARGS", "limit must be an integer between 1 and 10.", hint="5 is a good page size."
        )
    try:
        import asyncio

        collection = await asyncio.to_thread(
            _client().get_collection,
            collection_name_for_conversation(ctx.conversation_id),
        )
        page = await asyncio.to_thread(
            _list_document_chunks, collection, filename, offset, limit
        )
    except Exception:
        return ToolResult.failure(
            "NOT_FOUND",
            f"No uploaded document named {filename!r} was found in this conversation.",
            hint="Check the spelling against the filenames search_documents reported.",
        )
    if not page:
        return ToolResult.failure(
            "NOT_FOUND",
            f"{filename!r} has no chunks at offset {offset}.",
            hint=f"Offsets run 0..{max(0, len(page) + offset - 1)}; use a smaller offset.",
        )
    return ToolResult.success({"filename": filename, "chunks": page})
