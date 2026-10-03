from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

import httpx
from langchain_openai import ChatOpenAI

from app.config import settings


@dataclass(frozen=True)
class KeyValidationResult:
    valid: bool
    model_count: int = 0
    sample_models: tuple[str, ...] = ()
    reason: str | None = None
    category: str | None = None

    def as_response(self) -> dict[str, Any]:
        if self.valid:
            return {
                "valid": True,
                "model_count": self.model_count,
                "sample_models": list(self.sample_models),
            }
        return {"valid": False, "reason": self.reason}


class NvidiaApiError(Exception):
    def __init__(self, category: str, reason: str, status_code: int | None = None) -> None:
        self.category = category
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)


def _new_async_client(timeout_seconds: float | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout_seconds or settings.nvidia_timeout_seconds)


def _models_url() -> str:
    return f"{settings.nvidia_base_url.rstrip('/')}/models"


def _classify_status(status_code: int) -> tuple[str, str]:
    if status_code == 401 or status_code == 403:
        return "invalid_key", "The NVIDIA API key was rejected. Check the key and try again."
    if status_code == 429:
        return "rate_limited", "NVIDIA rate-limited this request. Please wait and try again."
    return "unknown_error", "NVIDIA could not validate this API key right now."


async def _request_models(api_key: str) -> list[dict[str, Any]]:
    try:
        async with _new_async_client() as client:
            response = await client.get(
                _models_url(),
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.RequestError:
        raise NvidiaApiError("network_error", "Could not reach NVIDIA. Check your connection and try again.") from None

    if response.status_code >= 400:
        category, reason = _classify_status(response.status_code)
        raise NvidiaApiError(category, reason, response.status_code)

    try:
        payload = response.json()
        models = payload["data"]
        if not isinstance(models, list):
            raise TypeError
        return [model for model in models if isinstance(model, dict)]
    except (ValueError, KeyError, TypeError):
        raise NvidiaApiError("unknown_error", "NVIDIA returned an unexpected models response.") from None


async def validate_api_key(api_key: str) -> KeyValidationResult:
    try:
        models = await _request_models(api_key)
        model_ids = tuple(
            model["id"] for model in models[:5] if isinstance(model.get("id"), str)
        )
        return KeyValidationResult(valid=True, model_count=len(models), sample_models=model_ids)
    except NvidiaApiError as exc:
        return KeyValidationResult(
            valid=False,
            reason=exc.reason,
            category=exc.category,
        )
    except Exception:
        return KeyValidationResult(
            valid=False,
            reason="An unexpected error occurred while validating the NVIDIA API key.",
            category="unknown_error",
        )


_MODEL_CACHE_TTL_SECONDS = 300
_model_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def clear_models_cache(user_id: str) -> None:
    _model_cache.pop(user_id, None)


async def list_models_for_user(user_id: str, api_key: str) -> list[dict[str, Any]]:
    cached = _model_cache.get(user_id)
    now = monotonic()
    if cached is not None and cached[0] > now:
        return [model.copy() for model in cached[1]]

    models = await _request_models(api_key)
    _model_cache[user_id] = (now + _MODEL_CACHE_TTL_SECONDS, models)
    return [model.copy() for model in models]


def make_chat_model(api_key: str, model: str) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=settings.nvidia_base_url,
        timeout=settings.nvidia_timeout_seconds,
        max_retries=0,
        streaming=True,
    )


async def complete_vision_request(
    api_key: str,
    model: str,
    question: str,
    image_data_uri: str,
) -> str:
    """Call an NVIDIA multimodal chat model using the shared NVIDIA client setup."""
    url = f"{settings.nvidia_base_url.rstrip('/')}/chat/completions"
    async with _new_async_client() as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": question},
                            {"type": "image_url", "image_url": {"url": image_data_uri}},
                        ],
                    }
                ],
                "temperature": 0.2,
                "max_tokens": 1024,
                "stream": False,
            },
        )
    response.raise_for_status()
    return _completion_text(response.json(), "vision")


async def complete_video_request(
    api_key: str,
    model: str,
    question: str,
    video_data_uri: str,
    *,
    image_data_uri: str | None = None,
) -> str:
    """Send a video (and optional image) through NVIDIA's chat completions API."""
    content: list[dict[str, Any]] = [
        {"type": "video_url", "video_url": {"url": video_data_uri}},
        {"type": "text", "text": question},
    ]
    if image_data_uri:
        content.append({"type": "image_url", "image_url": {"url": image_data_uri}})

    url = f"{settings.nvidia_base_url.rstrip('/')}/chat/completions"
    async with _new_async_client(max(settings.nvidia_timeout_seconds, 120.0)) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.2,
                "max_tokens": 1024,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
    response.raise_for_status()
    return _completion_text(response.json(), "video")


def _completion_text(payload: Any, modality: str) -> str:
    try:
        choices = payload["choices"]
        content = choices[0]["message"]["content"]
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        raise ValueError(f"NVIDIA {modality} response did not contain completion text.") from None

    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        text_parts = [
            part["text"] for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        result = "".join(text_parts).strip()
        if result:
            return result
    raise ValueError(f"NVIDIA {modality} response did not contain description text.")
