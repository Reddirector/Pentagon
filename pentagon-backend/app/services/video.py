# Model available under the stored NVIDIA key: nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
from __future__ import annotations

import asyncio
import base64
import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.config import settings
from app.services.nvidia_client import complete_video_request


VIDEO_MODEL_ID = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
MAX_VIDEO_BYTES = 120 * 1024 * 1024
MAX_VIDEO_SECONDS = 600.0
MAX_SAMPLED_FRAMES = 60
_VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
_VIDEO_MIME_TO_SUFFIX = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
    "video/x-msvideo": ".avi",
    "video/avi": ".avi",
}


@dataclass(frozen=True)
class PreparedVideo:
    data_uri: str
    duration_seconds: float
    fps: float
    frames_sent: int


def _bad_video(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


async def read_uploaded_video(upload: UploadFile) -> PreparedVideo:
    filename_suffix = Path(upload.filename or "").suffix.lower()
    content_type = (upload.content_type or "").lower().split(";", 1)[0].strip()
    mime_suffix = _VIDEO_MIME_TO_SUFFIX.get(content_type)

    if filename_suffix not in _VIDEO_SUFFIXES:
        raise _bad_video("Video format must be mp4, mov, webm, mkv, or avi.")
    if content_type and not content_type.startswith("video/"):
        raise _bad_video("The uploaded video must use a video content type.")
    if mime_suffix and filename_suffix != mime_suffix:
        raise _bad_video("Video filename and content type must match.")

    # The configured limit can lower the hard ceiling but never raise it, so a
    # generous deployment setting cannot remove the bound entirely.
    max_bytes = max_bytes_limit()
    content = await upload.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise _bad_video(f"Video must be {max_bytes // (1024 * 1024)} MB or smaller.")
    if not content:
        raise _bad_video("Video file is empty.")
    return await asyncio.to_thread(_prepare_video, content, filename_suffix)


def max_bytes_limit() -> int:
    """The effective upload ceiling for this deployment."""
    configured = int(getattr(settings, "video_max_bytes", 0) or 0)
    if configured <= 0:
        return MAX_VIDEO_BYTES
    return min(configured, MAX_VIDEO_BYTES)


def _prepare_video(content: bytes, suffix: str) -> PreparedVideo:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise HTTPException(
            status_code=503,
            detail="Video processing requires ffmpeg and ffprobe on the server.",
        )

    max_duration = min(float(settings.video_max_duration_seconds), MAX_VIDEO_SECONDS)
    if max_duration <= 0:
        raise HTTPException(status_code=503, detail="Video duration limit is not configured.")

    # A long clip is sampled more sparsely rather than rejected, so the frame
    # budget stays fixed no matter how long the video is.
    requested_fps = float(settings.video_sampling_fps)
    fps = min(max(requested_fps, 0.1), 1.0)
    fps = min(fps, max(MAX_SAMPLED_FRAMES / max_duration, 0.02))

    with tempfile.TemporaryDirectory(prefix="pentagon-video-") as directory:
        source_path = Path(directory) / f"source{suffix}"
        sampled_path = Path(directory) / "sampled.mp4"
        source_path.write_bytes(content)
        try:
            probe = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-show_entries", "format=duration:stream=codec_type,width,height",
                    "-of", "json",
                    str(source_path),
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except subprocess.TimeoutExpired:
            raise _bad_video("The video could not be inspected within the time limit.") from None
        if probe.returncode != 0:
            raise _bad_video("The uploaded file is not a valid video.")
        try:
            probe_data: dict[str, Any] = json.loads(probe.stdout)
            duration = float(probe_data["format"]["duration"])
            video_stream = next(
                stream for stream in probe_data["streams"]
                if stream.get("codec_type") == "video"
            )
            width = int(video_stream["width"])
            height = int(video_stream["height"])
        except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError):
            raise _bad_video("The uploaded file is not a valid video.") from None

        if not math.isfinite(duration) or duration <= 0:
            raise _bad_video("Video duration could not be determined.")
        if duration > max_duration:
            raise _bad_video(
                f"Video must be {max_duration:g} seconds or shorter."
            )
        if width <= 0 or height <= 0:
            raise _bad_video("Video dimensions could not be determined.")

        scale = min(1.0, 1000 / max(width, height), math.sqrt(1_000_000 / (width * height)))
        output_width = max(2, int(width * scale) // 2 * 2)
        output_height = max(2, int(height * scale) // 2 * 2)
        filter_chain = f"fps={fps:g},scale={output_width}:{output_height}"
        try:
            transcode = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(source_path),
                    "-t", f"{max_duration:g}",
                    "-vf", filter_chain,
                    "-an",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-crf", "30",
                    "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    str(sampled_path),
                ],
                capture_output=True,
                text=True,
                timeout=45,
            )
        except subprocess.TimeoutExpired:
            raise _bad_video("The video could not be prepared within the time limit.") from None
        if transcode.returncode != 0 or not sampled_path.exists():
            raise _bad_video("The video could not be prepared for NVIDIA analysis.")

        try:
            sampled_probe = subprocess.run(
                [
                    ffprobe,
                    "-v", "error",
                    "-count_frames",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=nb_read_frames",
                    "-of", "json",
                    str(sampled_path),
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except subprocess.TimeoutExpired:
            raise _bad_video("The sampled video could not be inspected within the time limit.") from None
        try:
            sampled_data = json.loads(sampled_probe.stdout)
            frames_sent = int(sampled_data["streams"][0]["nb_read_frames"])
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise _bad_video("The sampled video frame count could not be determined.") from None
        if sampled_probe.returncode != 0 or not 1 <= frames_sent <= MAX_SAMPLED_FRAMES:
            raise _bad_video("Video sampling produced an invalid frame count.")

        sampled_bytes = sampled_path.read_bytes()

    encoded = base64.b64encode(sampled_bytes).decode("ascii")
    return PreparedVideo(
        data_uri=f"data:video/mp4;base64,{encoded}",
        duration_seconds=duration,
        fps=fps,
        frames_sent=frames_sent,
    )


async def analyze_video(
    api_key: str,
    question: str,
    video_data_uri: str,
    *,
    image_data_uri: str | None = None,
) -> str:
    return await complete_video_request(
        api_key,
        VIDEO_MODEL_ID,
        question or "Describe what's happening in this video with timestamps.",
        video_data_uri,
        image_data_uri=image_data_uri,
    )
