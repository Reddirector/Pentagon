"""document_generation: produce a real, downloadable file from structured content.

The model hands over a target format (docx / pdf / xlsx / csv / md), a title,
and content in the matching intermediate representation. The tool renders the
bytes with the real library for that format (see
``app.services.document_builder``), stores them in the private file bucket,
records a ``generated_files`` row, and publishes the file record on the turn's
shared state so the client can render an inline file card with a preview.

The write is a local filesystem/bucket write, so the tool declares
``risk_category="local_filesystem_write"`` and runs through the same
permission gate as every other tool: a user whose category is set to
``always_ask`` sees an approval card before a byte is written, and
``never_allow`` blocks it outright. It never bypasses the autonomy system to
"be helpful".
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.db import session as db_session
from app.db.models import GeneratedFile
from app.services.document_builder import (
    CONTENT_TYPES,
    EXTENSIONS,
    BuildError,
    build_document,
    safe_filename,
    verify_document_integrity,
)
from app.services.file_storage import StorageError, build_key, get_storage

MAX_FILENAME_STEM = 120

TOOL_SPEC = ToolSpec(
    name="document_generation",
    description=(
        "Generate a real file the user can preview in the chat and download:"
        " a Word document (docx), a PDF, an Excel workbook (xlsx), a CSV, a"
        " Markdown file (md), a plain text file (txt), an interactive website or styled HTML document (html),"
        " or a PowerPoint presentation (pptx). Supports multi-page documents and"
        " arbitrarily large content. When the user asks to create/build a website, landing page, or web app,"
        " ALWAYS use format='html' with complete HTML5/CSS/JS (never use image_generation)."
        " IMPORTANT: When the user prompt requests web research, factual data, real photos, or AI images along with the document,"
        " you MUST call web_search (and image_generation if requested) FIRST before calling document_generation,"
        " so the document is built with real gathered data. Provide the target 'format',"
        " a 'title' (used for the file name), and 'content': for html write complete working HTML/CSS/JS code (never write descriptions or placeholder text);"
        " for docx/pdf/md a markdown-like document (# headings, paragraphs, - bullets, 1. numbered, | pipe tables |,"
        " ``` code fences ```, '---' or '[PAGE_BREAK]' for explicit page breaks); for pptx either markdown"
        " (each heading or '---' becomes a slide) or {slides: [{title, bullets}]};"
        " for xlsx/csv an object with 'columns' and 'rows' (rows as arrays or objects),"
        " or an xlsx 'sheets' array of {name, columns, rows}. Returns the file record; the client shows an interactive"
        " live preview and a download button. One file per call."
    ),
    parameters={
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "enum": ["docx", "pdf", "xlsx", "csv", "md", "txt", "html", "pptx"],
                "description": "The target file format: 'docx', 'pdf', 'xlsx', 'csv', 'md', 'txt', 'html' (for websites, landing pages, web apps, or styled HTML docs), 'pptx'.",
            },
            "title": {
                "type": "string",
                "description": (
                    "Document title; also the file name (extension is added)."
                    " e.g. 'Q3 Sales Report' or 'Artisanal Bakery Landing Page'."
                ),
            },
            "content": {
                "type": ["string", "object"],
                "description": (
                    "The complete, exhaustive, full-length document body. NEVER write placeholders, stubs, outlines, or '(Content to be added)'. "
                    "You MUST write out the ENTIRE full text of every page and section in markdown format: rich multi-sentence paragraphs, "
                    "# headings, ## subheadings, - bullet points, | pipe tables |, and '---' or '[PAGE_BREAK]' between pages. "
                    "For html: complete, working HTML5/CSS/JS code. For pptx: markdown with '---' between slides. For xlsx/csv: complete {columns, rows}."
                ),
            },
        },
        "required": ["format", "title", "content"],
    },
    # It writes a file, so the ladder treats it like any other write.
    tier="write",
    risk_category="local_filesystem_write",
    timeout_s=60,
    cacheable=False,
    idempotent=False,
    parallel_safe=True,
    tags=(
        "file",
        "document",
        "export",
        "report",
        "website",
        "webpage",
        "landing_page",
        "download",
        "docx",
        "pdf",
        "xlsx",
        "csv",
        "markdown",
        "txt",
        "html",
        "pptx",
        "presentation",
        "slides",
        "generate",
        "save",
        "deliverable",
    ),
)

# The chat graph binds graph-native tools from plain dicts, not from the agent
# registry, so it needs this shape. The ``_risk_category`` tag mirrors what
# SHELL_TOOL_SCHEMA carries; the gate's name map keys off the tool name.
GRAPH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "document_generation",
        "description": TOOL_SPEC.description,
        "parameters": TOOL_SPEC.parameters,
    },
    "_risk_category": "local_filesystem_write",
}


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    format = args.get("format")
    if not isinstance(format, str) or format not in CONTENT_TYPES:
        return ToolResult.failure(
            "INVALID_ARGS",
            f"format must be one of: {', '.join(sorted(CONTENT_TYPES))}.",
            hint="Pick the format the user asked for, e.g. 'pdf'.",
        )
    title = args.get("title")
    if not isinstance(title, str) or not title.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "title must be a non-empty string.",
            hint="Give the document a short descriptive title.",
        )
    title = title.strip()[:200]
    content = args.get("content")

    try:
        # Rendering can take a second for a large sheet; keep it off the
        # event loop so one big export cannot stall the chat stream.
        data = await asyncio.to_thread(build_document, format, title, content)
    except BuildError as exc:
        return ToolResult.failure("INVALID_ARGS", str(exc), hint="Adjust the content and call again.")
    except Exception as exc:  # library-level failure: tell the model, not the user
        return ToolResult.failure(
            "UPSTREAM",
            f"The {format} file could not be generated ({exc.__class__.__name__}).",
            hint="Simplify the content (shorter tables, fewer rows) and retry.",
        )
    if not data:
        return ToolResult.failure("UPSTREAM", "Generation produced an empty file.")

    try:
        verify_document_integrity(format, data, title)
    except BuildError as exc:
        return ToolResult.failure("UPSTREAM", f"Document integrity check failed: {exc}")

    filename = safe_filename(title, format)
    storage = get_storage()
    key = build_key(ctx.user_id, ctx.conversation_id, str(uuid4()), EXTENSIONS[format])
    try:
        await storage.put(key, data, CONTENT_TYPES[format])
    except StorageError as exc:
        return ToolResult.failure("UPSTREAM", str(exc), hint="The file store is unavailable; try again later.")

    record = GeneratedFile(
        id=key.split("/")[-1].rsplit(".", 1)[0],
        user_id=ctx.user_id,
        conversation_id=ctx.conversation_id,
        filename=filename,
        format=format,
        media_type=CONTENT_TYPES[format],
        size_bytes=len(data),
        storage_path=key,
    )
    try:
        with db_session.SessionLocal() as db:
            from app.db.models import User, Conversation
            if not db.get(User, ctx.user_id):
                db.add(User(id=ctx.user_id))
                db.flush()
            if not db.get(Conversation, ctx.conversation_id):
                db.add(Conversation(id=ctx.conversation_id, user_id=ctx.user_id, title=title or "Generated Deliverables"))
                db.flush()
            db.add(record)
            db.commit()
            payload = _serialize(record)
    except Exception as exc:
        logger.warning("Failed to save GeneratedFile record (%s): %s", type(exc).__name__, exc)
        # The row and the object must appear together or not at all: an
        # orphaned object would be invisible (no row to list) yet still occupy
        # the bucket, and an orphaned row would 404 on download.
        try:
            await storage.delete(key)
        except StorageError:
            pass
        return ToolResult.failure("UPSTREAM", "The file record could not be saved.")

    if isinstance(ctx.shared, dict):
        ctx.shared["generated_file"] = payload
    res_payload = dict(payload)
    res_payload["title"] = title
    res_payload["content"] = content if isinstance(content, str) else json.dumps(content, indent=2)
    res_payload["message"] = (
        f"The {format.upper()} deliverable '{filename}' was successfully compiled and delivered to the user with an interactive preview. "
        "Only if the user prompt explicitly requested an additional distinct deliverable format (such as both a spreadsheet AND a presentation deck), invoke document_generation for that format. Otherwise, STOP calling tools and proceed immediately to present your comprehensive executive briefing in chat now with comparison tables, callouts, and key takeaways."
    )
    return ToolResult.success(res_payload)


def _serialize(record: GeneratedFile) -> dict[str, Any]:
    return {
        "id": record.id,
        "filename": record.filename,
        "format": record.format,
        "size": record.size_bytes,
        "conversation_id": record.conversation_id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "storage_path": record.storage_path,
        "media_type": record.media_type,
    }
