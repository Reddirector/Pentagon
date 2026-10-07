"""Embeddings: identity first, vectors second (RAG §5.4).

A collection's model is ``id@version`` and a change means reindex -- those are
the invariants that keep similarity scores meaningful. The rest of this file
pins the behaviours that make the abstraction honest: unknown models are
refused before storage, the cache is keyed by model *and* input type, and the
dimension is never hardcoded.
"""

from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.rag2 import embeddings as emb


@pytest.fixture(autouse=True)
def clean_cache():
    emb.clear_cache()
    yield
    emb.clear_cache()


def test_default_embedder_is_the_configured_local_model() -> None:
    embedder = emb.default_embedder()
    assert embedder.model_id == settings.embedding_model
    assert embedder.provider == "local"
    assert embedder.ref == f"{settings.embedding_model}@1"


def test_refs_parse_id_and_version() -> None:
    assert emb.parse_ref("some/model@3") == ("some/model", 3)
    assert emb.parse_ref("some/model") == ("some/model", 1)
    assert emb.parse_ref("some/model@not-a-number") == ("some/model@not-a-number", 1)


def test_unknown_model_is_refused() -> None:
    with pytest.raises(emb.UnknownEmbeddingModel):
        emb.get_embedder("acme/unverified-model")
    # And refused with a message that names the culprit.
    try:
        emb.spec_for("acme/unverified-model")
    except emb.UnknownEmbeddingModel as exc:
        assert "acme/unverified-model" in str(exc)


def test_nvidia_models_pass_through() -> None:
    spec = emb.spec_for("nvidia:nemotron-3-embed-1b")
    assert spec.provider == "nvidia"
    assert spec.model_id == "nemotron-3-embed-1b"
    # The provider string form the base app records maps back the same way.
    assert emb.spec_from_provider("nvidia:nemotron-3-embed-1b").model_id == "nemotron-3-embed-1b"
    assert emb.spec_from_provider("local:sentence-transformers/all-MiniLM-L6-v2").provider == "local"


def test_nvidia_without_a_key_fails_honestly() -> None:
    """No key means an error, never vectors from some other space."""
    embedder = emb.get_embedder("nvidia:some-embed-model")
    with pytest.raises(RuntimeError, match="[Kk]ey"):
        asyncio.run(embedder.embed_documents(["hello"]))


def test_needs_reindex_compares_id_and_version() -> None:
    assert emb.needs_reindex("model-a@1", "model-a@1") is False
    assert emb.needs_reindex("model-a@1", "model-a@2") is True, "a version bump is a new space"
    assert emb.needs_reindex("model-a@1", "model-b@1") is True
    # Bare vs explicit version of the same model is not a change.
    assert emb.needs_reindex("model-a", "model-a@1") is False


def test_cache_is_keyed_by_model_text_and_input_type(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_encode(model_id: str, texts: list[str]) -> list[list[float]]:
        calls.append(list(texts))
        return [[1.0, float(len(text)), 0.0] for text in texts]

    monkeypatch.setattr(emb, "_encode_local", fake_encode)
    embedder = emb.get_embedder(None)

    first = asyncio.run(embedder.embed_documents(["alpha", "beta"]))
    second = asyncio.run(embedder.embed_documents(["alpha", "beta"]))
    assert first == second
    assert calls == [["alpha", "beta"]], "identical texts must be embedded once"

    # The same words as a query live in a different cache slot: query and
    # passage inputs are not interchangeable for prefixing models.
    asyncio.run(embedder.embed_query("alpha"))
    assert calls[-1] == ["alpha"], "query cache must not be satisfied by a passage"


def test_query_and_passage_prefixes_are_applied(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    def fake_encode(model_id: str, texts: list[str]) -> list[list[float]]:
        seen.append((model_id, texts[0]))
        return [[0.0, 0.0, 1.0] for _ in texts]

    monkeypatch.setattr(emb, "_encode_local", fake_encode)
    spec = emb.EmbedderSpec(
        model_id="e5-style/model", provider="local", query_prefix="query: ", passage_prefix="passage: "
    )
    embedder = emb.Embedder(spec)

    asyncio.run(embedder.embed_documents(["some text"]))
    asyncio.run(embedder.embed_query("some text"))

    assert seen == [
        ("e5-style/model", "passage: some text"),
        ("e5-style/model", "query: some text"),
    ], "the model card's prefixes must reach the model, or retrieval mismatches"


def test_dimension_is_read_not_assumed(monkeypatch) -> None:
    class StubModel:
        def get_sentence_embedding_dimension(self) -> int:
            return 768

    monkeypatch.setattr(emb, "_load_local_model", lambda model_id: StubModel())
    embedder = emb.get_embedder(None)
    assert embedder.dim == 768
    assert emb._learned_dims[embedder.model_id] == 768  # learned once, reused

    # An unprovisioned remote model reports None instead of guessing.
    assert emb.get_embedder("nvidia:unprovisioned").dim is None


def test_empty_inputs_cost_nothing() -> None:
    embedder = emb.get_embedder(None)
    assert asyncio.run(embedder.embed_documents([])) == []


def test_shaped_provider_strings_resolve() -> None:
    # The base app's provider constant maps to the same model as the default.
    from app.services.embeddings import LOCAL_EMBEDDING_PROVIDER

    spec = emb.spec_from_provider(LOCAL_EMBEDDING_PROVIDER)
    assert spec.model_id == settings.local_embedding_model
    assert spec.provider == "local"
    assert emb.needs_reindex(spec.ref, emb.default_embedder().ref) is (
        settings.local_embedding_model != settings.embedding_model
    )
