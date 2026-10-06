"""search_documents: semantic search over the user's uploaded files.

The conversation's Chroma collection already holds chunked uploads; this
exposes retrieval as a tool so the model reaches for it when a question is
about the user's own documents, instead of the pipeline guessing. Chunks come
back with locators (filename) the model can cite.
"""

from __future__ import annotations

from typing import Any

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.services.document_store import has_documents, retrieve_chunks

TOOL_SPEC = ToolSpec(
    name="search_documents",
    description=(
        "Search the user's uploaded documents in this conversation by meaning."
        " Use when the question is about what the files say -- contract terms,"
        " figures, definitions, anything the user uploaded. Do not use it for"
        " general knowledge or current web information. Returns the closest"
        " chunks, each with the filename it came from; quote the filename when"
        " you rely on a chunk. Example: {\"query\": \"termination notice period\"}."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look for in the documents, phrased naturally.",
            },
            "limit": {
                "type": "integer",
                "description": "How many chunks to return (1-8). Defaults to 4.",
            },
        },
        "required": ["query"],
    },
    tier="read",
    timeout_s=30,
    cacheable=True,
    cache_ttl_s=120,
    idempotent=True,
    parallel_safe=True,
    tags=("documents", "files", "upload", "pdf", "contract", "rag", "search"),
)


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "query must be a non-empty string.",
            hint='Describe what to find, e.g. {"query": "total contract value"}.',
        )
    limit = args.get("limit", 4)
    if isinstance(limit, str) and limit.strip().isdigit():
        limit = int(limit)
    if not isinstance(limit, int) or not 1 <= limit <= 8:
        return ToolResult.failure(
            "INVALID_ARGS",
            "limit must be an integer between 1 and 8.",
            hint="Leave limit out to get 4 chunks.",
        )
    try:
        if not has_documents(ctx.conversation_id):
            return ToolResult.success(
                {
                    "query": query.strip(),
                    "chunks": [],
                    "note": "No documents have been uploaded in this conversation.",
                }
            )
        chunks = await retrieve_chunks(
            conversation_id=ctx.conversation_id,
            query=query.strip(),
            api_key=None,
            limit=limit,
        )
    except Exception as exc:
        return ToolResult.failure(
            "UPSTREAM",
            f"Document search failed: {type(exc).__name__}.",
            hint="Try a differently worded query once; then answer with what you have.",
        )
    return ToolResult.success(
        {
            "query": query.strip(),
            "chunks": [
                {
                    "filename": chunk.get("filename") or "document",
                    "content": chunk.get("content") or "",
                }
                for chunk in chunks
            ],
        }
    )
