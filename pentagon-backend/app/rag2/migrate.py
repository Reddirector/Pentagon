"""One-time migration: legacy per-conversation chunks -> rag2 collections.

The base app keeps each conversation's vectors in a Chroma collection named
from the conversation id, with the text only inside Chroma. RAG 2 wants text,
metadata and language in the ``chunks`` table (source of truth), one
collection row per scope, and vectors in a store named after the collection --
so every conversation's uploads become an implicit private collection.

Order of operations is chosen so nothing can be lost:

1. read the legacy snapshot (ids, texts, metadatas, vectors),
2. write the new rows in one transaction,
3. write the new vector store,
4. **verify** both counts against the snapshot,
5. only then delete the legacy store.

A failure at 2-4 leaves the legacy store exactly as it was, so re-running the
script resumes rather than starting over: an existing collection with the
right chunk count skips straight to the vector step. ``--dry-run`` reports the
plan without touching anything.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    Chunk,
    Collection,
    CollectionFile,
    Conversation,
    ConversationCollection,
    Document,
    new_id,
)
from app.rag2.embeddings import get_embedder, needs_reindex, spec_from_provider
from app.rag2.store import chroma_collection_name
from app.services.document_store import _client, collection_name_for_conversation

logger = logging.getLogger(__name__)

EmbedFn = Callable[[list[str]], list[list[float]]]
EmitFn = Callable[[str], None]


@dataclass
class LegacySnapshot:
    conversation_id: str
    ids: list[str]
    texts: list[str]
    metadatas: list[dict[str, Any]]
    provider: str
    total_in_store: int


@dataclass
class MigrationPlan:
    conversation_id: str
    user_id: str
    title: str
    file_ids: list[str]
    chunk_count: int
    skipped_unattributed: int
    source_provider: str | None
    target_ref: str
    reembed: bool
    existing_collection_id: str | None = None

    @property
    def summary(self) -> str:
        source = self.source_provider or "no vectors"
        action = "re-embed" if self.reembed else "copy vectors"
        return (
            f"{self.title!r}: {len(self.file_ids)} file(s), {self.chunk_count} chunk(s), "
            f"{source} -> {self.target_ref} ({action})"
        )


@dataclass
class MigrationReport:
    dry_run: bool
    planned: list[MigrationPlan] = field(default_factory=list)
    migrated: list[MigrationPlan] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def _legacy_store(conversation_id: str):
    from app.services.document_store import _get_collection

    return _get_collection(collection_name_for_conversation(conversation_id))


def _read_legacy(conversation_id: str, *, with_vectors: bool) -> LegacySnapshot | None:
    store = _legacy_store(conversation_id)
    if store is None or store.count() == 0:
        return None
    include = ["documents", "metadatas"] + (["embeddings"] if with_vectors else [])
    payload = store.get(include=include)
    provider = (store.metadata or {}).get("embedding_provider", "")
    ids = list(payload.get("ids") or [])
    texts = [text or "" for text in (payload.get("documents") or [])]
    metadatas = [meta or {} for meta in (payload.get("metadatas") or [])]
    snapshot = LegacySnapshot(
        conversation_id=conversation_id,
        ids=ids,
        texts=texts,
        metadatas=metadatas,
        provider=provider,
        total_in_store=store.count(),
    )
    if with_vectors:
        # Chroma hands embeddings back as an ndarray; never test one for
        # truthiness ("ambiguous"), normalise to plain lists on the way in.
        raw_vectors = payload.get("embeddings")
        if raw_vectors is None:
            snapshot_vectors[conversation_id] = []
        elif hasattr(raw_vectors, "tolist"):
            snapshot_vectors[conversation_id] = raw_vectors.tolist()
        else:
            snapshot_vectors[conversation_id] = list(raw_vectors)
    return snapshot


# Vectors are only read on apply (they are the memory-heavy part); keyed by
# conversation for the duration of one migration call.
snapshot_vectors: dict[str, Any] = {}


def _plan_for(db: Session, conversation: Conversation, target_ref: str) -> MigrationPlan | None:
    snapshot = _read_legacy(conversation.id, with_vectors=False)
    if snapshot is None:
        return None

    document_ids = {
        row.id: row.id
        for row in db.scalars(
            select(Document).where(
                Document.conversation_id == conversation.id,
                Document.user_id == conversation.user_id,
            )
        )
    }
    file_ids: list[str] = []
    kept = 0
    skipped = 0
    for metadata in snapshot.metadatas:
        file_id = metadata.get("document_id")
        if file_id in document_ids:
            kept += 1
            if file_id not in file_ids:
                file_ids.append(file_id)
        else:
            skipped += 1

    source_spec = spec_from_provider(snapshot.provider) if snapshot.provider else None
    reembed = True if source_spec is None else needs_reindex(source_spec.ref, target_ref)

    link = db.scalar(
        select(ConversationCollection).where(
            ConversationCollection.conversation_id == conversation.id
        )
    )
    existing_id = None
    if link is not None:
        existing = db.get(Collection, link.collection_id)
        if existing is not None and existing.user_id == conversation.user_id:
            existing_id = existing.id

    return MigrationPlan(
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        title=conversation.title,
        file_ids=file_ids,
        chunk_count=kept,
        skipped_unattributed=skipped,
        source_provider=snapshot.provider or None,
        target_ref=target_ref,
        reembed=reembed,
        existing_collection_id=existing_id,
    )


def _ordered_rows(snapshot: LegacySnapshot, plan: MigrationPlan) -> list[tuple[str, str, int]]:
    """(file_id, text, ord) in the order the documents were uploaded."""
    valid = {
        file_id for file_id in plan.file_ids
    }
    rows: list[tuple[str, str, int]] = []
    for text, metadata in zip(snapshot.texts, snapshot.metadatas):
        file_id = metadata.get("document_id")
        if file_id not in valid:
            continue
        try:
            order = int(metadata.get("chunk_index", len(rows)))
        except (TypeError, ValueError):
            order = len(rows)
        rows.append((str(file_id), text, order))
    # Stable within a file, files in first-appearance order (upload order).
    position = {file_id: index for index, file_id in enumerate(plan.file_ids)}
    rows.sort(key=lambda row: (position.get(row[0], 0), row[2]))
    return rows


def _default_embed_fn(target_ref: str, user_id: str) -> EmbedFn:
    """Real embedding for one owner: their stored key, else the server's."""
    embedder = get_embedder(target_ref)

    def embed(texts: list[str]) -> list[list[float]]:
        api_key: str | None = None
        if embedder.provider == "nvidia":
            from app.db.session import SessionLocal
            from app.security.keys import resolve_api_key_or_http

            with SessionLocal() as db:
                try:
                    api_key = resolve_api_key_or_http(db, user_id)
                except Exception:
                    # No key anywhere: fail honestly at embed time rather
                    # than silently writing vectors in another space.
                    api_key = None
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(embedder.embed_documents(texts, api_key=api_key))
        raise RuntimeError(
            "embed_fn must be supplied when called from inside a running event loop."
        )

    return embed


def _verify(db: Session, plan: MigrationPlan, collection_id: str, vector_count: int) -> bool:
    """Both stores must hold what the legacy store held, or nothing is deleted."""
    from sqlalchemy import func

    rows = int(
        db.scalar(
            select(func.count(Chunk.id)).where(Chunk.collection_id == collection_id)
        )
        or 0
    )
    return rows == plan.chunk_count and vector_count == plan.chunk_count


def _ensure_collection(db: Session, plan: MigrationPlan) -> Collection:
    if plan.existing_collection_id is not None:
        collection = db.get(Collection, plan.existing_collection_id)
        if collection is not None:
            return collection
    collection = Collection(
        id=new_id(),
        user_id=plan.user_id,
        name=f"{plan.title or 'Conversation'} documents",
        description="Migrated from this conversation's original document store.",
        embedding_model=plan.target_ref,
    )
    db.add(collection)
    db.flush()
    db.add(
        ConversationCollection(
            conversation_id=plan.conversation_id,
            collection_id=collection.id,
            user_id=plan.user_id,
        )
    )
    return collection


def _write_chunks(db: Session, plan: MigrationPlan, collection: Collection, snapshot: LegacySnapshot) -> None:
    rows = _ordered_rows(snapshot, plan)
    # Resume safety: only this plan's files are rewritten, so anything added
    # to the collection after the first run is left alone.
    existing = db.scalars(
        select(Chunk).where(
            Chunk.collection_id == collection.id,
            Chunk.file_id.in_(plan.file_ids),
        )
    ).all()
    for chunk in existing:
        db.delete(chunk)
    for file_id, text, order in rows:
        db.add(
            Chunk(
                id=new_id(),
                user_id=plan.user_id,
                collection_id=collection.id,
                file_id=file_id,
                ord=order,
                text=text,
            )
        )
    for file_id in plan.file_ids:
        if db.get(CollectionFile, {"collection_id": collection.id, "file_id": file_id}) is None:
            db.add(
                CollectionFile(
                    collection_id=collection.id, file_id=file_id, user_id=plan.user_id
                )
            )
    db.commit()


def _write_vectors(
    plan: MigrationPlan,
    collection: Collection,
    snapshot: LegacySnapshot,
    embed_fn: EmbedFn,
) -> int:
    """Put the collection's vectors in its own store. Returns their count."""
    client = _client()
    name = chroma_collection_name(collection.id)
    existing_names = {
        item.name if hasattr(item, "name") else str(item) for item in client.list_collections()
    }
    if name in existing_names:
        store = client.get_collection(name=name, embedding_function=None)
        if store.count() == plan.chunk_count:
            return store.count()
        client.delete_collection(name)

    ordered = _ordered_rows(snapshot, plan)
    texts = [text for _, text, _ in ordered]
    vectors: list[list[float]] = []
    if plan.reembed:
        vectors = embed_fn(texts)
    else:
        stored = snapshot_vectors.get(plan.conversation_id)
        vectors = [] if stored is None else list(stored)
        # The snapshot's order is the store's order; re-order to match rows.
        if len(vectors) == len(snapshot.texts):
            by_position = {
                (metadata.get("document_id"), str(metadata.get("chunk_index"))): vector
                for vector, metadata in zip(vectors, snapshot.metadatas)
            }
            vectors = [
                by_position.get((file_id, str(order)), [])
                for file_id, _, order in ordered
            ]

    if len(vectors) != len(texts) or any(len(vector) == 0 for vector in vectors):
        raise RuntimeError("Embedding returned the wrong number of vectors; not storing.")

    store = client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine", "embedding_model": plan.target_ref},
        embedding_function=None,
    )
    store.add(
        ids=[row[0] + ":" + str(index) for index, row in enumerate(ordered)],
        embeddings=vectors,
        documents=texts,
        metadatas=[
            {"document_id": file_id, "collection_id": collection.id, "ord": order}
            for file_id, _, order in ordered
        ],
    )
    return store.count()


def _purge_legacy(conversation_id: str) -> bool:
    from app.services.document_store import purge_conversation_collection

    return purge_conversation_collection(conversation_id)


def migrate(
    db: Session,
    *,
    dry_run: bool = False,
    embed_fn: EmbedFn | None = None,
    emit: EmitFn = print,
    only: list[str] | None = None,
) -> MigrationReport:
    """Migrate every conversation that still has a legacy store.

    ``only`` narrows the run to specific conversation ids -- used by tests and
    by anyone who wants to re-run one thread without touching the rest.
    """
    target_ref = get_embedder(settings.embedding_model).ref
    report = MigrationReport(dry_run=dry_run)
    snapshot_vectors.clear()
    statement = (
        db.execute(
            select(Conversation)
            .join(Document, Document.conversation_id == Conversation.id)
            .group_by(Conversation.id)
            .order_by(Conversation.created_at)
        )
        .scalars()
        .all()
    )
    conversations = [row for row in statement if only is None or row.id in set(only)]

    for conversation in conversations:
        plan = _plan_for(db, conversation, target_ref)
        if plan is None:
            report.skipped.append((conversation.id, "no legacy vectors to migrate"))
            continue
        if plan.chunk_count == 0:
            report.skipped.append(
                (conversation.id, "every legacy chunk belongs to a deleted file")
            )
            continue
        report.planned.append(plan)
        prefix = "[dry-run]" if dry_run else "[migrate]"
        emit(f"{prefix} {plan.summary}")
        if dry_run:
            continue

        try:
            snapshot = _read_legacy(conversation.id, with_vectors=not plan.reembed)
            if snapshot is None:
                raise RuntimeError("Legacy store disappeared between plan and apply.")
            collection = _ensure_collection(db, plan)
            plan.existing_collection_id = collection.id
            _write_chunks(db, plan, collection, snapshot)
            embed = embed_fn or _default_embed_fn(plan.target_ref, plan.user_id)
            vector_count = _write_vectors(plan, collection, snapshot, embed)
            if not _verify(db, plan, collection.id, vector_count):
                raise RuntimeError(
                    "Verification failed: the new stores do not match the legacy count; "
                    "the original document store was kept."
                )
            _purge_legacy(conversation.id)
        except Exception as exc:
            db.rollback()
            reason = str(exc) or type(exc).__name__
            report.failed.append((conversation.id, reason))
            emit(f"[failed] {plan.title!r}: {reason} (original store kept)")
            logger.warning("Migration failed for conversation %s: %s", conversation.id, reason)
            continue

        report.migrated.append(plan)
        emit(f"[done] {plan.title!r}: {plan.chunk_count} chunk(s) -> collection {collection.id}")

    if dry_run:
        emit(
            f"[dry-run] {len(report.planned)} conversation(s) would be migrated; "
            "nothing was changed."
        )
    else:
        emit(
            f"[summary] migrated={len(report.migrated)} failed={len(report.failed)} "
            f"skipped={len(report.skipped)}"
        )
    snapshot_vectors.clear()
    return report
