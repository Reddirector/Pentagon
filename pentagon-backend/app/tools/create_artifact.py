"""create_artifact: let the agent hand the user an actual file.

Artifacts are the model's way of delivering work that is not chat prose --
a report, a CSV, a converted document. The file lands under the configured
artifact directory (one folder per turn), the payload is published on the
loop's shared state, and the loop emits the ``artifact`` event so the client
can show and open it. Names are sanitized: the model picks a file name, never
a path.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.config import settings

# A plain file name: no separators, no leading dot, bounded length. Because
# there is no path separator, ".." can appear only inside a name and never
# escapes the turn's folder.
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_MEDIA_TYPE = re.compile(r"^[a-z0-9][a-z0-9.+-]*/[A-Za-z0-9][A-Za-z0-9.+-]*$")
# Generous for a text artifact, still small enough that one call cannot fill
# the disk or the client's download.
_MAX_CONTENT_BYTES = 1_000_000

TOOL_SPEC = ToolSpec(
    name="create_artifact",
    description=(
        "Save a finished deliverable as a file the user can open: a report,"
        " a CSV of results, a cleaned dataset, a generated document. Use when"
        " the answer is better read as a file than as chat prose, or when it"
        " exceeds what should be pasted into the conversation. Provide a"
        " short file name with an extension (e.g. 'quarterly-summary.md')"
        " and the complete file content; the tool stores it and tells the"
        " client an artifact is ready. One file per call -- call again for"
        " more. Do not use it for intermediate scratch notes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "File name with an extension, e.g. 'report.md'. Letters,"
                    " digits, dot, dash and underscore only -- not a path."
                ),
            },
            "content": {
                "type": "string",
                "description": "The complete text of the file.",
            },
            "media_type": {
                "type": "string",
                "description": (
                    "MIME type of the file, default 'text/plain'; e.g."
                    " 'text/markdown', 'text/csv', 'application/json'."
                ),
            },
        },
        "required": ["name", "content"],
    },
    # It writes a file to disk, so the ladder treats it like any write.
    tier="write",

    risk_category="local_filesystem_write",    timeout_s=10,
    cacheable=False,
    idempotent=False,
    parallel_safe=True,
    tags=(
        "artifact",
        "file",
        "export",
        "save",
        "download",
        "report",
        "output",
        "deliverable",
        "attachment",
    ),
)


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    name = args.get("name")
    if not isinstance(name, str) or not _NAME.match(name):
        return ToolResult.failure(
            "INVALID_ARGS",
            "name must be a plain file name like 'report.md' (letters,"
            " digits, dot, dash, underscore; max 80 chars).",
            hint="No directories or slashes: pass only the file name.",
        )
    content = args.get("content")
    if not isinstance(content, str) or not content.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "content must be the non-empty text of the file.",
            hint="Write the full file body as the 'content' argument.",
        )
    data = content.encode("utf-8")
    if len(data) > _MAX_CONTENT_BYTES:
        return ToolResult.failure(
            "INVALID_ARGS",
            f"content is {len(data)} bytes; the artifact limit is"
            f" {_MAX_CONTENT_BYTES} bytes.",
            hint="Trim the file, or summarize and attach only the essential part.",
        )
    media_type = args.get("media_type") or "text/plain"
    if not isinstance(media_type, str) or not _MEDIA_TYPE.match(media_type):
        return ToolResult.failure(
            "INVALID_ARGS",
            "media_type must be a MIME type like 'text/markdown'.",
            hint="Omit it to default to 'text/plain'.",
        )

    safe_turn = re.sub(r"[^A-Za-z0-9._-]", "_", ctx.turn_id)[:64]
    # Dots survive the substitution, so a turn id of exactly ".." (or an
    # empty one) would name a parent folder; fall back to a literal one.
    if safe_turn in {"", ".", ".."}:
        safe_turn = "turn"
    target_dir = Path(settings.artifact_directory) / safe_turn
    target = target_dir / name
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as exc:
        return ToolResult.failure(
            "UPSTREAM",
            f"The artifact could not be written ({exc.__class__.__name__}).",
            hint="The artifact directory must be writable by the backend.",
        )
    payload = {
        "id": f"{safe_turn}/{name}",
        "name": name,
        "path": str(target),
        "media_type": media_type,
        "bytes": len(data),
        "turn_id": ctx.turn_id,
    }
    if isinstance(ctx.shared, dict):
        ctx.shared["artifact"] = payload
    return ToolResult.success(dict(payload))
