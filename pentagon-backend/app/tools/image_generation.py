"""image_generation: generate a high-quality image or visual diagram from a prompt.

Uses FLUX.1 / diffusion with prompt expansion and a local fallback graphics engine.
Stores the rendered image bytes in the private file bucket, records a
``generated_files`` row with format="jpg", and publishes the record on the turn's
shared state so the client can display the image card with inline preview and download.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.db import session as db_session
from app.db.models import GeneratedFile
from app.services.file_storage import StorageError, build_key, get_storage
from app.services.image_generator import generate_image

TOOL_SPEC = ToolSpec(
    name="image_generation",
    description=(
        "Generate a synthetic AI image, artistic illustration, or digital diagram using"
        " diffusion models. ONLY invoke this tool when the user EXPLICITLY COMMANDS image generation"
        " (e.g. 'generate an image of...', 'create an AI picture of...', 'draw...', 'paint...', 'synthesize a diagram of...')."
        " DO NOT call this tool for real-world entities, historical figures, places, products, or factual topics"
        " when real photos/images are requested; for real subjects, use real images from web search results."
        " Provide a detailed 'prompt', a 'title' for the file (e.g. 'Cybernetic Neon City'),"
        " an optional 'aspect_ratio' ('16:9', '1:1', '4:3', '9:16'), and an optional 'style'"
        " ('photorealistic', 'cinematic', 'diagram', 'digital-art', 'minimalist')."
        " The generated image is saved, previewable inline in chat, and downloadable."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Detailed description of what to depict in the image.",
            },
            "title": {
                "type": "string",
                "description": "Short title and filename for the image (e.g. 'AI Data Center').",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["16:9", "1:1", "4:3", "9:16"],
                "default": "16:9",
                "description": "Image dimensions aspect ratio. Defaults to 16:9 (widescreen).",
            },
            "style": {
                "type": "string",
                "enum": ["photorealistic", "cinematic", "diagram", "digital-art", "minimalist"],
                "default": "photorealistic",
                "description": "Visual style direction. Defaults to photorealistic.",
            },
        },
        "required": ["prompt", "title"],
    },
    tier="write",
    risk_category="local_filesystem_write",
    timeout_s=60,
    cacheable=False,
    idempotent=False,
    parallel_safe=True,
    tags=(
        "image",
        "generate",
        "picture",
        "photo",
        "illustration",
        "diagram",
        "visual",
        "draw",
        "flux",
        "art",
    ),
)

GRAPH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "image_generation",
        "description": TOOL_SPEC.description,
        "parameters": TOOL_SPEC.parameters,
    },
    "_risk_category": "local_filesystem_write",
}


def _safe_image_filename(title: str, ext: str = "jpg") -> str:
    import re
    name = re.sub(r"[^A-Za-z0-9 _.-]+", "", title or "").strip(" .")
    name = re.sub(r"\s+", " ", name)[:100].strip(" .") or "Generated_Image"
    if not name.lower().endswith(f".{ext}"):
        name = f"{name}.{ext}"
    return name


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


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "prompt must be a non-empty string.",
            hint="Describe what the image should show.",
        )
    title = args.get("title")
    if not isinstance(title, str) or not title.strip():
        title = "Generated Image"
    title = title.strip()[:180]
    aspect_ratio = str(args.get("aspect_ratio") or "16:9")
    style = str(args.get("style") or "photorealistic")

    try:
        data, media_type = await generate_image(
            prompt=prompt,
            style=style,
            aspect_ratio=aspect_ratio,
        )
    except Exception as exc:
        return ToolResult.failure(
            "UPSTREAM",
            f"Image generation failed: {exc}",
            hint="Try rephrasing the prompt with simpler terms.",
        )

    if not data:
        return ToolResult.failure("UPSTREAM", "Image generation produced 0 bytes.")

    ext = "jpg" if "jpeg" in media_type or "jpg" in media_type else "png"
    filename = _safe_image_filename(title, ext=ext)
    storage = get_storage()
    file_uuid = str(uuid4())
    key = build_key(ctx.user_id, ctx.conversation_id, file_uuid, ext)

    try:
        await storage.put(key, data, media_type)
    except StorageError as exc:
        return ToolResult.failure("UPSTREAM", str(exc), hint="File storage failed.")

    record = GeneratedFile(
        id=key.split("/")[-1].rsplit(".", 1)[0],
        user_id=ctx.user_id,
        conversation_id=ctx.conversation_id,
        filename=filename,
        format=ext,
        media_type=media_type,
        size_bytes=len(data),
        storage_path=key,
    )

    try:
        with db_session.SessionLocal() as db:
            db.add(record)
            db.commit()
            payload = _serialize(record)
    except Exception:
        try:
            await storage.delete(key)
        except Exception:
            pass
        return ToolResult.failure("UPSTREAM", "Failed to register generated image in database.")

    if isinstance(ctx.shared, dict):
        ctx.shared["generated_file"] = payload

    download_url = f"/api/files/{record.id}/download"
    res_data = dict(payload)
    res_data["url"] = download_url
    res_data["markdown"] = f"![{title}]({download_url})"
    res_data["instruction"] = f"Image generated successfully. Embed this image in your final markdown response using: {res_data['markdown']}. Conclude your answer."

    return ToolResult.success(res_data)
