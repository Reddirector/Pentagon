"""Collection CRUD, file assignment and conversation scope (RAG §4, §12).

Every route is scoped by ``user_id`` and answers **404** for a foreign id --
a 403 would confirm the id exists, which is itself a leak. This mirrors the
``own rows`` policies in ``supabase/migrations/rag2.sql`` on the local-first
SQLite base (DECISIONS #8).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ConversationCollection
from app.db.session import get_db
from app.rag2 import collections as service
from app.rag2.embeddings import UnknownEmbeddingModel

router = APIRouter(prefix="/api/collections", tags=["collections"])


class CollectionCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    embedding_model: str | None = Field(default=None, max_length=255)
    graph_enabled: bool = False
    conversation_id: str | None = Field(default=None, max_length=36)


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    graph_enabled: bool | None = None


class FileLink(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    file_id: str = Field(min_length=1, max_length=36)


class ConversationLink(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=36)


def _detail(db: Session, user_id: str, collection) -> dict:
    return {
        "id": collection.id,
        "name": collection.name,
        "description": collection.description,
        "embedding_model": collection.embedding_model,
        "graph_enabled": collection.graph_enabled,
        "file_count": service.file_counts(db, user_id, collection.id),
        "chunk_count": service.chunk_counts(db, user_id, collection.id),
        "created_at": collection.created_at,
        "updated_at": collection.updated_at,
    }


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Collection not found for this user.")


@router.post("", status_code=201)
def create_collection(payload: CollectionCreate, db: Session = Depends(get_db)) -> dict:
    if len(service.list_collections(db, payload.user_id)) >= service.MAX_COLLECTIONS_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A user may have at most {service.MAX_COLLECTIONS_PER_USER} collections; "
                "delete one first."
            ),
        )
    try:
        collection = service.create_collection(
            db,
            user_id=payload.user_id,
            name=payload.name,
            description=payload.description,
            embedding_model=payload.embedding_model,
            graph_enabled=payload.graph_enabled,
        )
    except UnknownEmbeddingModel as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if payload.conversation_id is not None and not service.attach_conversation(
        db, payload.user_id, payload.conversation_id, collection.id
    ):
        # The collection exists; the conversation simply is not the caller's.
        raise HTTPException(
            status_code=404, detail="Conversation not found for this user."
        )
    return _detail(db, payload.user_id, collection)


@router.get("")
def list_collections(user_id: str, db: Session = Depends(get_db)) -> list[dict]:
    return [_detail(db, user_id, c) for c in service.list_collections(db, user_id)]


@router.get("/{collection_id}")
def get_collection(
    collection_id: str, user_id: str, db: Session = Depends(get_db)
) -> dict:
    collection = service.get_collection(db, user_id, collection_id)
    if collection is None:
        raise _not_found()
    detail = _detail(db, user_id, collection)
    detail["file_ids"] = service.list_file_ids(db, user_id, collection_id)
    detail["conversation_ids"] = list(
        db.scalars(
            select(ConversationCollection.conversation_id).where(
                ConversationCollection.collection_id == collection_id,
                ConversationCollection.user_id == user_id,
            )
        )
    )
    return detail


@router.patch("/{collection_id}")
def update_collection(
    collection_id: str,
    payload: CollectionUpdate,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict:
    fields = payload.model_fields_set
    collection = service.update_collection(
        db,
        user_id,
        collection_id,
        name=payload.name if "name" in fields else None,
        description=payload.description if "description" in fields else None,
        graph_enabled=payload.graph_enabled if "graph_enabled" in fields else None,
    )
    if collection is None:
        raise _not_found()
    return _detail(db, user_id, collection)


@router.delete("/{collection_id}", status_code=204)
def delete_collection(
    collection_id: str, user_id: str, db: Session = Depends(get_db)
) -> None:
    if not service.delete_collection(db, user_id, collection_id):
        raise _not_found()


# --- files -----------------------------------------------------------------
@router.post("/{collection_id}/files", status_code=201)
def attach_file(
    collection_id: str, payload: FileLink, db: Session = Depends(get_db)
) -> dict:
    if not service.attach_file(db, payload.user_id, collection_id, payload.file_id):
        raise HTTPException(
            status_code=404, detail="Collection or document not found for this user."
        )
    return {"collection_id": collection_id, "file_id": payload.file_id}


@router.delete("/{collection_id}/files/{file_id}", status_code=204)
def detach_file(
    collection_id: str, file_id: str, user_id: str, db: Session = Depends(get_db)
) -> None:
    if not service.detach_file(db, user_id, collection_id, file_id):
        raise HTTPException(
            status_code=404, detail="Collection or document not found for this user."
        )


@router.get("/{collection_id}/files")
def list_files(
    collection_id: str, user_id: str, db: Session = Depends(get_db)
) -> list[str]:
    if service.get_collection(db, user_id, collection_id) is None:
        raise _not_found()
    return service.list_file_ids(db, user_id, collection_id)


# --- conversation scope ----------------------------------------------------
@router.post("/{collection_id}/conversations", status_code=201)
def attach_conversation(
    collection_id: str, payload: ConversationLink, db: Session = Depends(get_db)
) -> dict:
    if not service.attach_conversation(
        db, payload.user_id, payload.conversation_id, collection_id
    ):
        raise HTTPException(
            status_code=404, detail="Collection or conversation not found for this user."
        )
    return {"collection_id": collection_id, "conversation_id": payload.conversation_id}


@router.delete("/{collection_id}/conversations/{conversation_id}", status_code=204)
def detach_conversation(
    collection_id: str,
    conversation_id: str,
    user_id: str,
    db: Session = Depends(get_db),
) -> None:
    if not service.detach_conversation(db, user_id, conversation_id, collection_id):
        raise HTTPException(
            status_code=404, detail="Collection or conversation not found for this user."
        )


@router.get("/{collection_id}/conversations")
def list_conversations(
    collection_id: str, user_id: str, db: Session = Depends(get_db)
) -> list[str]:
    if service.get_collection(db, user_id, collection_id) is None:
        raise _not_found()
    return list(
        db.scalars(
            select(ConversationCollection.conversation_id).where(
                ConversationCollection.collection_id == collection_id,
                ConversationCollection.user_id == user_id,
            )
        )
    )
