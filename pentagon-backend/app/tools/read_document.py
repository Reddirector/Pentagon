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
        " offset or page number. Use after search_documents when the matched chunk is clearly"
        " the middle of something longer -- a table, a clause, a list -- and you"
        " need the surrounding text. Do not use it to find where a topic is:"
        " search first, then read around the hit. Returns the requested chunks"
        " with their 0-based positions and total_chunks count. Example:"
        ' {"filename": "contract.pdf", "offset": 4, "limit": 3} or'
        ' {"filename": "presentation.pptx", "page": 3}.'
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
                "description": "How many chunks to read (1-100). Defaults to 5.",
            },
            "page": {
                "type": "integer",
                "description": "Optional 1-based page or slide number to jump to directly.",
            },
        },
        "required": ["filename"],
    },
    tier="read",
    risk_category="read_only_info",
    timeout_s=20,
    cacheable=True,
    cache_ttl_s=120,
    idempotent=True,
    parallel_safe=True,
    tags=("documents", "files", "read", "page", "pdf"),
    untrusted=True,
)


def _list_document_chunks(
    collection,
    filename: str,
    offset: int,
    limit: int,
    page: int | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """Chunk texts for one file, in stored order, returning (chunks_slice, total_chunks, effective_offset)."""
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
    total_chunks = len(matching)
    if not matching:
        return [], 0, offset

    effective_offset = offset
    if page is not None and page >= 1:
        markers = [
            f"--- Page {page} ---",
            f"--- Page {page}:",
            f"--- Slide {page} ---",
            f"--- Slide {page}:",
        ]
        found_idx = None
        for idx, row in enumerate(matching):
            text = row.get("content", "")
            if any(m in text for m in markers):
                found_idx = idx
                break
        if found_idx is not None:
            effective_offset = found_idx

    return matching[effective_offset : effective_offset + limit], total_chunks, effective_offset


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
    page_param = args.get("page")
    page_num: int | None = None
    if page_param is not None:
        if isinstance(page_param, str) and page_param.strip().isdigit():
            page_num = int(page_param)
        elif isinstance(page_param, int) and page_param >= 1:
            page_num = page_param
    if isinstance(offset, str) and offset.strip().isdigit():
        offset = int(offset)
    if isinstance(limit, str) and limit.strip().isdigit():
        limit = int(limit)
    if not isinstance(offset, int) or offset < 0:
        return ToolResult.failure(
            "INVALID_ARGS", "offset must be a non-negative integer.", hint="Start at 0."
        )
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        return ToolResult.failure(
            "INVALID_ARGS", "limit must be an integer between 1 and 100.", hint="5 to 20 is a good page size."
        )
    try:
        import asyncio

        collection = await asyncio.to_thread(
            _client().get_collection,
            collection_name_for_conversation(ctx.conversation_id),
        )
        chunks, total_chunks, effective_offset = await asyncio.to_thread(
            _list_document_chunks, collection, filename, offset, limit, page_num
        )
    except Exception:
        return ToolResult.failure(
            "NOT_FOUND",
            f"No uploaded document named {filename!r} was found in this conversation.",
            hint="Check the spelling against the filenames search_documents reported.",
        )
    if not chunks:
        return ToolResult.failure(
            "NOT_FOUND",
            f"{filename!r} has no chunks at offset {offset if page_num is None else effective_offset}.",
            hint=f"Total chunks: {total_chunks}; offsets run 0..{max(0, total_chunks - 1)}; use a smaller offset.",
        )
    return ToolResult.success({
        "filename": filename,
        "total_chunks": total_chunks,
        "offset": effective_offset,
        "limit": limit,
        "has_more": (effective_offset + len(chunks)) < total_chunks,
        "chunks": chunks,
    })
