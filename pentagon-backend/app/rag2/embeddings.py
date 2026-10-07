"""Embeddings behind an explicit model identity (RAG §5.4, §6).

Every collection records the model its vectors were made with as ``id@version``
(``Collection.embedding_model``), because embedding spaces are not
interchangeable: mixing two models in one store silently corrupts similarity,
and comparing scores across models is meaningless. A different id *or* version
means reindex -- see :func:`needs_reindex`.

What is verified rather than assumed:

* The **local** path goes through ``sentence-transformers`` exactly as the base
  app's fallback does: same library, CPU, normalized embeddings. Any local
  model id can be named, so a benchmarked multilingual model (R1) can become
  the default without new code.
* The **NVIDIA** path reuses ``app.services.embeddings.embed_texts`` with the
  ``nvidia:<id>`` provider string the base app already exercises: batched
  requests, ``input_type`` of ``query``/``passage``. NIM embedding endpoints
  take the input type as a field, not a string prefix, so both prefixes are
  empty for the shipped specs -- but the fields exist because *some* model
  cards (E5-style) require ``"query: "``/``"passage: "`` prefixes, and the card
  of the chosen model is what fills them in (RAG §5.4).
* Results are cached by ``hash(text, model)`` so re-embedding the same chunk
  during a reindex or a second retrieval costs nothing.

Nothing here probes the network: dimension is learned from the first real
batch (or read from the local model when it is already loaded) instead of
being hardcoded from a model card nobody has read.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Literal

from app.config import settings

LOCAL_PROVIDER_PREFIX = "local:"
NVIDIA_PROVIDER_PREFIX = "nvidia:"

# Refill-by-model cache. Bounded so a long indexing run cannot grow without
# limit; entries are (model_ref, input_type, text) -> vector.
_CACHE_MAX_ENTRIES = 4096
_vector_cache: OrderedDict[tuple[str, str, str], list[float]] = OrderedDict()
_learned_dims: dict[str, int] = {}

CacheInputType = Literal["passage", "query"]


class UnknownEmbeddingModel(ValueError):
    """The requested model id is not one this server can produce vectors with."""


@dataclass(frozen=True)
class EmbedderSpec:
    """Identity of one embedding space: model, version, and card-mandated prefixes."""

    model_id: str
    provider: str  # "local" | "nvidia"
    version: int = 1
    query_prefix: str = ""
    passage_prefix: str = ""

    @property
    def ref(self) -> str:
        return f"{self.model_id}@{self.version}"


# Shipped specs. The local model is the one this app already downloads and
# runs (settings default); its card specifies no input prefixes.
_LOCAL_SPECS: dict[str, EmbedderSpec] = {
    "sentence-transformers/all-MiniLM-L6-v2": EmbedderSpec(
        model_id="sentence-transformers/all-MiniLM-L6-v2", provider="local"
    ),
}


def parse_ref(ref: str) -> tuple[str, int]:
    """Split ``id@version``; a bare id means version 1."""
    if "@" in ref:
        model_id, _, version_text = ref.rpartition("@")
        try:
            return model_id, int(version_text)
        except ValueError:
            return ref, 1
    return ref, 1


def spec_for(ref: str) -> EmbedderSpec:
    """Resolve a stored reference to a spec, or raise UnknownEmbeddingModel.

    Accepted forms: a stored ``id@version`` ref, a bare model id this server
    knows, the configured defaults, and ``nvidia:<id>`` passthrough (NVIDIA
    serves hundreds of embedding models; verifying one exists needs a key and
    a network call, which happens at embed time and fails honestly there).
    """
    model_id, version = parse_ref(ref)
    bare_id = model_id.removeprefix(NVIDIA_PROVIDER_PREFIX)
    if model_id.startswith(NVIDIA_PROVIDER_PREFIX):
        return EmbedderSpec(model_id=bare_id, provider="nvidia", version=version)
    if model_id.startswith(LOCAL_PROVIDER_PREFIX):
        model_id = model_id.removeprefix(LOCAL_PROVIDER_PREFIX)
    if model_id in _LOCAL_SPECS:
        return replace(_LOCAL_SPECS[model_id], version=version)
    if model_id in (settings.local_embedding_model, settings.embedding_model):
        # Configured as the local model (EMBEDDING_MODEL /
        # LOCAL_EMBEDDING_MODEL), so treat it as local even before its spec
        # has been curated above.
        return EmbedderSpec(model_id=model_id, provider="local", version=version)
    raise UnknownEmbeddingModel(
        f"{ref!r} is not an embedding model this server can produce vectors with."
    )


def spec_from_provider(provider: str) -> EmbedderSpec:
    """Map a base-app provider string (``local:...`` / ``nvidia:...``) to a spec.

    The legacy per-conversation Chroma collections record their space this
    way; the migration needs to know whether they match a target collection's
    model before deciding to re-embed.
    """
    if provider.startswith(NVIDIA_PROVIDER_PREFIX):
        return EmbedderSpec(
            model_id=provider.removeprefix(NVIDIA_PROVIDER_PREFIX), provider="nvidia"
        )
    if provider.startswith(LOCAL_PROVIDER_PREFIX):
        model_id = provider.removeprefix(LOCAL_PROVIDER_PREFIX)
        if model_id in _LOCAL_SPECS:
            return _LOCAL_SPECS[model_id]
        return EmbedderSpec(model_id=model_id, provider="local")
    return spec_for(provider)


def needs_reindex(current_ref: str, target_ref: str) -> bool:
    """True when two refs name different embedding spaces."""
    return parse_ref(current_ref) != parse_ref(target_ref)


def _cache_put(key: tuple[str, str, str], vector: list[float]) -> None:
    _vector_cache[key] = vector
    _vector_cache.move_to_end(key)
    while len(_vector_cache) > _CACHE_MAX_ENTRIES:
        _vector_cache.popitem(last=False)


def clear_cache() -> None:
    """Drop cached vectors (tests, and any deliberate re-index)."""
    _vector_cache.clear()
    _learned_dims.clear()


@lru_cache(maxsize=4)
def _load_local_model(model_id: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_id, device="cpu")


def _encode_local(model_id: str, texts: list[str]) -> list[list[float]]:
    model = _load_local_model(model_id)
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


class Embedder:
    """``Embedder(model_id)`` with ``embed_documents`` / ``embed_query`` / ``dim``."""

    def __init__(self, spec: EmbedderSpec) -> None:
        self.spec = spec

    @property
    def model_id(self) -> str:
        return self.spec.model_id

    @property
    def version(self) -> int:
        return self.spec.version

    @property
    def ref(self) -> str:
        return self.spec.ref

    @property
    def provider(self) -> str:
        return self.spec.provider

    @property
    def dim(self) -> int | None:
        """Vector width, or None until it has been observed.

        Never hardcoded: a wrong dimension is a silent failure at query time,
        so it is read from the local model or learned from the first batch.
        """
        if self.spec.model_id in _learned_dims:
            return _learned_dims[self.spec.model_id]
        if self.spec.provider == "local":
            try:
                model = _load_local_model(self.spec.model_id)
            except Exception:
                return None
            dimension = model.get_sentence_embedding_dimension()
            if dimension:
                _learned_dims[self.spec.model_id] = int(dimension)
            return int(dimension) if dimension else None
        return None

    async def embed_documents(
        self, texts: list[str], api_key: str | None = None
    ) -> list[list[float]]:
        """Embed passages (documents, entities) with any card-mandated prefix."""
        if not texts:
            return []
        prefixed = [self.spec.passage_prefix + text for text in texts]
        return await self._embed_many(prefixed, input_type="passage", api_key=api_key)

    async def embed_query(self, text: str, api_key: str | None = None) -> list[float]:
        """Embed one query, applying the card's query prefix if it has one."""
        prefixed = self.spec.query_prefix + text
        key = (self.ref, "query", prefixed)
        cached = _vector_cache.get(key)
        if cached is not None:
            _vector_cache.move_to_end(key)
            return cached
        vectors = await self._embed_many([prefixed], input_type="query", api_key=api_key)
        return vectors[0]

    async def _embed_many(
        self,
        texts: list[str],
        *,
        input_type: CacheInputType,
        api_key: str | None,
    ) -> list[list[float]]:
        results: list[list[float] | None] = []
        missing: list[str] = []
        missing_keys: list[tuple[str, str, str]] = []
        for text in texts:
            key = (self.ref, input_type, text)
            cached = _vector_cache.get(key)
            if cached is not None:
                _vector_cache.move_to_end(key)
                results.append(cached)
            else:
                results.append(None)
                missing.append(text)
                missing_keys.append(key)

        if missing:
            computed = await self._compute(missing, input_type=input_type, api_key=api_key)
            if len(computed) == len(missing) and computed and computed[0]:
                # Dimension belongs to the model, not to our version counter.
                _learned_dims.setdefault(self.spec.model_id, len(computed[0]))
            for key, vector in zip(missing_keys, computed):
                _cache_put(key, vector)
            cursor = 0
            for index, value in enumerate(results):
                if value is None:
                    results[index] = computed[cursor]
                    cursor += 1
        # A short answer from the provider is a failure, not a shorter list.
        if any(vector is None for vector in results) or len(results) != len(texts):
            raise RuntimeError("The embedding provider returned an unexpected result.")
        return [vector for vector in results if vector is not None]

    async def _compute(
        self, texts: list[str], *, input_type: CacheInputType, api_key: str | None
    ) -> list[list[float]]:
        if self.spec.provider == "nvidia":
            from app.services.embeddings import embed_texts

            provider = f"{NVIDIA_PROVIDER_PREFIX}{self.spec.model_id}"
            return await embed_texts(texts, provider, api_key, input_type)
        return await asyncio.to_thread(_encode_local, self.spec.model_id, texts)


def get_embedder(ref: str | None = None) -> Embedder:
    """Resolve a stored ref (or the configured default) to an Embedder."""
    return Embedder(spec_for(ref or settings.embedding_model))


def default_embedder() -> Embedder:
    return get_embedder(settings.embedding_model)
