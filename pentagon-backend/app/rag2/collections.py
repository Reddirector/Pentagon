"""Collection CRUD, file assignment, conversation scoping (RAG §3, §4).

Ownership lives in the query: every function here takes ``user_id`` and
filters on it, which is how the Supabase ``own rows`` policies declared in
``supabase/migrations/rag2.sql`` are honoured on the local SQLite base
(DECISIONS #8). A foreign id finds nothing, and "nothing" is a 404 upstream --
never a 403, which would confirm the id exists.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    Chunk,
    Collection,
    CollectionFile,
    Conversation,
    ConversationCollection,
    Document,
    utc_now,
)
from app.rag2.embeddings import get_embedder
from app.rag2.store import purge_collection_vectors

logger = logging.getLogger(__name__)

MAX_COLLECTIONS_PER_USER = 200


def _embedding_ref(model: str | None) -> str:
    """Validate and version a requested embedding model.

    An unknown model is rejected here, at creation time, rather than being
    stored and failing later at the first embed -- a collection whose model
    cannot produce vectors is a broken collection.
    """
    return get_embedder(model or settings.embedding_model).ref


def create_collection(
    db: Session,
    *,
    user_id: str,
    name: str,
    description: str | None = None,
    embedding_model: str | None = None,
    graph_enabled: bool = False,
) -> Collection:
    collection = Collection(
        user_id=user_id,
        name=name.strip(),
        description=description,
        embedding_model=_embedding_ref(embedding_model),
        graph_enabled=graph_enabled,
    )
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


def list_collections(db: Session, user_id: str) -> list[Collection]:
    return list(
        db.scalars(
            select(Collection)
            .where(Collection.user_id == user_id)
            .order_by(Collection.created_at, Collection.id)
        )
    )


def get_collection(db: Session, user_id: str, collection_id: str) -> Collection | None:
    return db.scalar(
        select(Collection).where(
            Collection.id == collection_id,
            Collection.user_id == user_id,
        )
    )


def update_collection(
    db: Session,
    user_id: str,
    collection_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    graph_enabled: bool | None = None,
) -> Collection | None:
    collection = get_collection(db, user_id, collection_id)
    if collection is None:
        return None
    if name is not None:
        collection.name = name.strip()
    if description is not None:
        collection.description = description
    if graph_enabled is not None:
        collection.graph_enabled = graph_enabled
    collection.updated_at = utc_now()
    db.commit()
    db.refresh(collection)
    return collection


def delete_collection(db: Session, user_id: str, collection_id: str) -> bool:
    """Remove a collection and everything scoped to it.

    Rows go in one transaction (chunks, files, links and jobs cascade through
    their foreign keys); vectors and the keyword cache go after it, and a
    vector purge that fails is logged, never allowed to resurrect the rows.
    """
    collection = get_collection(db, user_id, collection_id)
    if collection is None:
        return False
    db.delete(collection)
    db.commit()
    try:
        purge_collection_vectors(collection_id)
    except Exception as exc:
        logger.warning(
            "Vector purge failed for collection %s (%s)", collection_id, type(exc).__name__
        )
    purge_bm25_cache(collection_id)
    return True


def purge_bm25_cache(collection_id: str) -> None:
    """Drop the on-disk keyword index, if one exists yet.

    The BM25 cache is written per collection (R2); deletion must not leave a
    file that a future collection with a recycled id could read.
    """
    cache_dir = Path(settings.chroma_persist_directory) / "bm25"
    for suffix in (".pkl", ".npz", ".json"):
        cache_file = cache_dir / f"{collection_id}{suffix}"
        try:
            cache_file.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - filesystem refusal
            logger.warning("Could not remove keyword cache %s", cache_file)


# --- files -----------------------------------------------------------------
def attach_file(db: Session, user_id: str, collection_id: str, file_id: str) -> bool:
    """Link an uploaded document to a collection. False when either is not
    the caller's -- a foreign file id must not become readable by linking it.
    """
    if get_collection(db, user_id, collection_id) is None:
        return False
    if db.scalar(select(Document).where(Document.id == file_id, Document.user_id == user_id)) is None:
        return False
    existing = db.get(CollectionFile, {"collection_id": collection_id, "file_id": file_id})
    if existing is None:
        db.add(
            CollectionFile(
                collection_id=collection_id, file_id=file_id, user_id=user_id
            )
        )
        db.commit()
    return True


def detach_file(db: Session, user_id: str, collection_id: str, file_id: str) -> bool:
    if get_collection(db, user_id, collection_id) is None:
        return False
    row = db.get(CollectionFile, {"collection_id": collection_id, "file_id": file_id})
    if row is None or row.user_id != user_id:
        return False
    db.delete(row)
    db.commit()
    return True


def list_file_ids(db: Session, user_id: str, collection_id: str) -> list[str]:
    return list(
        db.scalars(
            select(CollectionFile.file_id)
            .where(
                CollectionFile.collection_id == collection_id,
                CollectionFile.user_id == user_id,
            )
            .order_by(CollectionFile.file_id)
        )
    )


# --- conversation scope ----------------------------------------------------
def attach_conversation(
    db: Session, user_id: str, conversation_id: str, collection_id: str
) -> bool:
    """Put a collection in a conversation's retrieval scope."""
    if get_collection(db, user_id, collection_id) is None:
        return False
    if db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    ) is None:
        return False
    existing = db.get(
        ConversationCollection,
        {"conversation_id": conversation_id, "collection_id": collection_id},
    )
    if existing is None:
        db.add(
            ConversationCollection(
                conversation_id=conversation_id,
                collection_id=collection_id,
                user_id=user_id,
            )
        )
        db.commit()
    return True


def detach_conversation(
    db: Session, user_id: str, conversation_id: str, collection_id: str
) -> bool:
    row = db.get(
        ConversationCollection,
        {"conversation_id": conversation_id, "collection_id": collection_id},
    )
    if row is None or row.user_id != user_id:
        return False
    db.delete(row)
    db.commit()
    return True


def attached_collection_ids(db: Session, user_id: str, conversation_id: str) -> list[str]:
    """The only collections a retriever may search for this conversation."""
    return list(
        db.scalars(
            select(ConversationCollection.collection_id)
            .where(
                ConversationCollection.conversation_id == conversation_id,
                ConversationCollection.user_id == user_id,
            )
            .order_by(ConversationCollection.collection_id)
        )
    )


def ensure_conversation_collection(
    db: Session, user_id: str, conversation_id: str
) -> Collection | None:
    """The implicit private collection for one conversation's documents.

    Every conversation owns its own scope; asking for one creates it on
    demand, named after the thread at the time, and reuses it thereafter so
    repeated uploads land together. Returns None when the conversation is not
    the caller's.
    """
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    if conversation is None:
        return None
    for collection_id in attached_collection_ids(db, user_id, conversation_id):
        existing = get_collection(db, user_id, collection_id)
        if existing is not None:
            return existing
    collection = create_collection(
        db,
        user_id=user_id,
        name=f"{conversation.title or 'Conversation'} documents",
        description="Created automatically for this conversation's uploads.",
    )
    attach_conversation(db, user_id, conversation_id, collection.id)
    return collection


# --- chunks (RLS-equivalent scoping) --------------------------------------
def list_chunks(
    db: Session,
    user_id: str,
    collection_id: str,
    *,
    file_id: str | None = None,
    limit: int | None = None,
) -> list:
    """Chunks the caller may read, ordered by file then position.

    Filtering on ``user_id`` *is* the isolation: without it any caller who
    guessed a collection id could read every passage inside it.
    """
    statement = (
        select(Chunk)
        .where(
            Chunk.collection_id == collection_id,
            Chunk.user_id == user_id,
        )
        .order_by(Chunk.file_id, Chunk.ord)
    )
    if file_id is not None:
        statement = statement.where(Chunk.file_id == file_id)
    if limit is not None:
        statement = statement.limit(limit)
    return list(db.scalars(statement))


def chunk_counts(db: Session, user_id: str, collection_id: str) -> int:
    return int(
        db.scalar(
            select(func.count(Chunk.id)).where(
                Chunk.collection_id == collection_id, Chunk.user_id == user_id
            )
        )
        or 0
    )


def file_counts(db: Session, user_id: str, collection_id: str) -> int:
    return int(
        db.scalar(
            select(func.count(CollectionFile.file_id)).where(
                CollectionFile.collection_id == collection_id,
                CollectionFile.user_id == user_id,
            )
        )
        or 0
    )
