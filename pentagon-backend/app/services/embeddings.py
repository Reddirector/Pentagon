from __future__ import annotations

import asyncio
import logging
import threading
from functools import lru_cache
from typing import Literal

import httpx

from app.config import settings
from app.services.nvidia_client import NvidiaApiError, list_models_for_user


logger = logging.getLogger(__name__)
EmbeddingInputType = Literal["passage", "query"]
LOCAL_EMBEDDING_PROVIDER = f"local:{settings.local_embedding_model}"
_NVIDIA_EMBEDDING_PREFIX = "nvidia:"
_local_model_lock = threading.Lock()


async def choose_embedding_provider(user_id: str, api_key: str | None) -> str:
    if api_key:
        try:
            models = await list_models_for_user(user_id, api_key)
            embedding_ids = [
                item["id"]
                for item in models
                if isinstance(item.get("id"), str)
                and "embed" in item["id"].lower()
                and "rerank" not in item["id"].lower()
            ]
            preferred = next(
                (item for item in embedding_ids if "nemotron-3-embed-1b" in item.lower()),
                embedding_ids[0] if embedding_ids else None,
            )
            if preferred:
                return f"{_NVIDIA_EMBEDDING_PREFIX}{preferred}"
        except NvidiaApiError as exc:
            logger.info("NVIDIA embedding discovery unavailable (%s); using local embeddings", exc.category)

    logger.info("No NVIDIA embedding model is available for this user; using local embeddings")
    return LOCAL_EMBEDDING_PROVIDER


async def embed_texts(
    texts: list[str],
    provider: str,
    api_key: str | None,
    input_type: EmbeddingInputType,
) -> list[list[float]]:
    if not texts:
        return []
    if provider.startswith(_NVIDIA_EMBEDDING_PREFIX):
        if not api_key:
            raise RuntimeError("An NVIDIA key is required for this conversation's embedding model.")
        model = provider.removeprefix(_NVIDIA_EMBEDDING_PREFIX)
        return await _nvidia_embeddings(texts, model, api_key, input_type)
    if provider != LOCAL_EMBEDDING_PROVIDER:
        raise RuntimeError("The conversation's embedding model is not available on this server.")
    return await asyncio.to_thread(_local_embeddings, texts)


async def _nvidia_embeddings(
    texts: list[str],
    model: str,
    api_key: str,
    input_type: EmbeddingInputType,
) -> list[list[float]]:
    vectors: list[list[float]] = []
    async with httpx.AsyncClient(timeout=settings.nvidia_timeout_seconds) as client:
        for start in range(0, len(texts), 32):
            batch = texts[start : start + 32]
            try:
                response = await client.post(
                    f"{settings.nvidia_base_url.rstrip('/')}/embeddings",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "input": batch,
                        "model": model,
                        "input_type": input_type,
                        "encoding_format": "float",
                    },
                )
                response.raise_for_status()
                data = response.json()["data"]
                vectors.extend(
                    item["embedding"]
                    for item in sorted(data, key=lambda row: row.get("index", 0))
                )
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise RuntimeError("The NVIDIA embedding request failed.") from None
    if len(vectors) != len(texts) or any(not isinstance(vector, list) for vector in vectors):
        raise RuntimeError("NVIDIA returned an unexpected embedding response.")
    return vectors


@lru_cache(maxsize=1)
def _load_sentence_transformer():
    from sentence_transformers import SentenceTransformer

    with _local_model_lock:
        return SentenceTransformer(settings.local_embedding_model, device="cpu")


def _local_embeddings(texts: list[str]) -> list[list[float]]:
    model = _load_sentence_transformer()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()
