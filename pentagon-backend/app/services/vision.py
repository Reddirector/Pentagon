# Model selected from the stored NVIDIA key's live /v1/models response: meta/llama-3.2-11b-vision-instruct
from __future__ import annotations

from app.services.nvidia_client import complete_vision_request


VISION_MODEL_ID = "meta/llama-3.2-11b-vision-instruct"


async def analyze_image(api_key: str, question: str, image_data_uri: str) -> str:
    """Ask NVIDIA's OpenAI-compatible chat endpoint to describe an image."""
    return await complete_vision_request(
        api_key,
        VISION_MODEL_ID,
        question or "Describe what's in this image.",
        image_data_uri,
    )
