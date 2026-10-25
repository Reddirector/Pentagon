"""serve_website_locally: Host and run HTML websites or deliverables on a live localhost server port.

Use this tool whenever the user asks to run, host, preview, or launch a website,
web application, or HTML file on localhost (e.g. http://localhost:8080).
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.services.file_storage import get_storage
from app.services.localhost_server import LOCALHOST_MANAGER

logger = logging.getLogger(__name__)

TOOL_SPEC = ToolSpec(
    name="serve_website_locally",
    description=(
        "Run an HTML website or web app on a live localhost server port (e.g. http://localhost:8080)."
        " Call this whenever the user asks to run, preview, or host their website or application on localhost."
        " Provide either 'html' (the full website code), or 'file_id' (an existing file id),"
        " and an optional 'title' or 'port'. Returns the active clickable localhost URL."
    ),
    parameters={
        "type": "object",
        "properties": {
            "html": {
                "type": "string",
                "description": "The complete HTML code of the website to run on localhost.",
            },
            "title": {
                "type": "string",
                "description": "Title or name for the hosted website.",
            },
            "file_id": {
                "type": "string",
                "description": "The ID of an existing generated file to host locally.",
            },
            "port": {
                "type": "integer",
                "description": "Optional specific port number to bind to (e.g. 8080, 3000).",
            },
        },
    },
    tier="action",
    risk_category="local_shell",
    timeout_s=15,
    idempotent=False,
    parallel_safe=False,
    tags=("website", "localhost", "server", "host", "preview", "run"),
)


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    html = args.get("html")
    file_id = args.get("file_id")
    title = args.get("title") or "Pentagon Live Website"
    port = args.get("port")

    if not html and not file_id:
        return ToolResult.failure(
            "INVALID_ARGS",
            "Either 'html' or 'file_id' must be provided to run a website on localhost.",
            hint="Pass the website's HTML code or the file_id of a generated document.",
        )

    if file_id and not html:
        # Load the HTML from storage if file_id is provided
        try:
            from app.db.models import GeneratedFile
            from app.db.session import SessionLocal

            with SessionLocal() as db:
                row = db.get(GeneratedFile, file_id)
                if not row:
                    return ToolResult.failure("NOT_FOUND", f"File '{file_id}' not found.")
                data = await get_storage().get(row.storage_path)
                html = data.decode("utf-8", errors="replace")
                if not title:
                    title = row.filename
        except Exception as exc:
            logger.warning("Failed to load file %s for localhost serve: %s", file_id, exc)
            return ToolResult.failure("STORAGE_ERROR", f"Could not load file: {exc}")

    try:
        res = LOCALHOST_MANAGER.start_server(
            html=html or "",
            title=title,
            port=int(port) if port else None,
            file_id=file_id,
        )
        url = res["url"]
        return ToolResult.success({
            "url": url,
            "port": res["port"],
            "title": title,
            "message": f"Website is now running live on localhost at {url}",
            "hint": f"Open {url} in your browser to view and interact with the website.",
        })
    except Exception as exc:
        logger.error("Failed to start localhost server: %s", exc)
        return ToolResult.failure("SERVER_ERROR", f"Could not launch localhost server: {exc}")
