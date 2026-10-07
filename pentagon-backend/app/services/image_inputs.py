from __future__ import annotations

import base64
import binascii
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from fastapi import HTTPException, Request
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from app.schemas import ChatRequest
from app.services.video import PreparedVideo, read_uploaded_video


MAX_IMAGE_BYTES = 10 * 1024 * 1024
_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}
_MIME_TO_FORMAT = {
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


@dataclass(frozen=True)
class PreparedImage:
    content: bytes
    extension: str
    media_type: str
    data_uri: str


def _unsupported_format() -> HTTPException:
    return HTTPException(
        status_code=400,
        detail="Image format must be jpg, png, or webp.",
    )


def _validate_image_bytes(
    content: bytes,
    *,
    declared_format: str | None = None,
) -> PreparedImage:
    if len(content) >= MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image must be smaller than 10 MB.")
    if not content:
        raise HTTPException(status_code=400, detail="Image file is empty.")
    try:
        with Image.open(io.BytesIO(content)) as image:
            detected_format = image.format
            image.verify()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
    ):
        # Pillow reports corrupt payloads as SyntaxError (e.g. a bad PNG chunk
        # checksum), so it has to be caught here or it escapes as a 500.
        raise HTTPException(
            status_code=400,
            detail="Image data is invalid or does not match jpg, png, or webp format.",
        ) from None

    if detected_format not in _FORMATS:
        raise _unsupported_format()
    if declared_format is not None and declared_format != detected_format:
        raise HTTPException(
            status_code=400,
            detail="Image content does not match its declared jpg, png, or webp format.",
        )
    extension, media_type = _FORMATS[detected_format]
    encoded = base64.b64encode(content).decode("ascii")
    return PreparedImage(
        content=content,
        extension=extension,
        media_type=media_type,
        data_uri=f"data:{media_type};base64,{encoded}",
    )


def _decode_data_uri(value: str) -> PreparedImage:
    header, separator, encoded = value.partition(",")
    if not separator or not header.startswith("data:") or ";base64" not in header.lower():
        raise HTTPException(
            status_code=400,
            detail="Image must be a base64 data URI in jpg, png, or webp format.",
        )
    mime_type = header[5:].split(";", 1)[0].lower()
    declared_format = _MIME_TO_FORMAT.get(mime_type)
    if declared_format is None:
        raise _unsupported_format()
    if len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        raise HTTPException(status_code=400, detail="Image must be smaller than 10 MB.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Image data is not valid base64.") from None
    return _validate_image_bytes(content, declared_format=declared_format)


async def _read_uploaded_image(upload: UploadFile) -> PreparedImage:
    extension = Path(upload.filename or "").suffix.lower()
    declared_format = None
    if extension in {".jpg", ".jpeg"}:
        declared_format = "JPEG"
    elif extension == ".png":
        declared_format = "PNG"
    elif extension == ".webp":
        declared_format = "WEBP"
    elif extension:
        raise _unsupported_format()

    content_type = (upload.content_type or "").lower().split(";", 1)[0].strip()
    if content_type:
        content_type_format = _MIME_TO_FORMAT.get(content_type)
        if content_type_format is None:
            raise _unsupported_format()
        if declared_format is not None and content_type_format != declared_format:
            raise HTTPException(
                status_code=400,
                detail="Image filename and content type must match a jpg, png, or webp image.",
            )
        declared_format = content_type_format
    content = await upload.read(MAX_IMAGE_BYTES + 1)
    if len(content) >= MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image must be smaller than 10 MB.")
    return _validate_image_bytes(content, declared_format=declared_format)


async def parse_chat_submission(
    request: Request,
) -> tuple[ChatRequest, PreparedImage | None, PreparedVideo | None]:
    """Parse chat bodies and validate all uploaded media before other work."""
    content_type = request.headers.get("content-type", "").lower()
    image: PreparedImage | None = None
    video: PreparedVideo | None = None
    if "application/json" in content_type:
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="Request body must be valid JSON.") from None
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
        data = dict(body)
        raw_image = data.pop("image", None)
        raw_video = data.pop("video", None)
        if raw_video is not None:
            raise HTTPException(
                status_code=400,
                detail="Video must be uploaded as a multipart file in the video field.",
            )
        if raw_image is not None:
            if not isinstance(raw_image, str):
                raise HTTPException(status_code=400, detail="Image must be a base64 data URI string.")
            image = _decode_data_uri(raw_image)
    elif "multipart/form-data" in content_type:
        try:
            form = await request.form()
        except Exception:
            raise HTTPException(status_code=400, detail="Multipart request body is invalid.") from None
        data = {}
        raw_image = form.get("image")
        if isinstance(raw_image, UploadFile):
            image = await _read_uploaded_image(raw_image)
        elif isinstance(raw_image, str) and raw_image:
            image = _decode_data_uri(raw_image)
        raw_video = form.get("video")
        if isinstance(raw_video, UploadFile):
            video = await read_uploaded_video(raw_video)
        elif raw_video is not None and raw_video != "":
            raise HTTPException(
                status_code=400,
                detail="Video must be uploaded as a multipart file in the video field.",
            )
        for field in (
            "user_id",
            "conversation_id",
            "model",
            "message",
            "use_web_search",
            "respond_with_audio",
            "regenerate",
            "voice",
            "transcription_duration_ms",
            "transcription_provider",
        ):
            value = form.get(field)
            if value is not None:
                data[field] = value
    else:
        raise HTTPException(
            status_code=415,
            detail="Chat requests must use application/json or multipart/form-data.",
        )

    try:
        payload = ChatRequest.model_validate(data)
    except ValidationError as exc:
        details = [
            {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        raise HTTPException(status_code=422, detail=details) from None
    if not payload.message.strip() and image is None and video is None:
        raise HTTPException(status_code=422, detail="message is required when no media is attached.")
    return payload, image, video
