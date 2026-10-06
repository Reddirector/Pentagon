from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Memory
from app.db.session import get_db
from app.services import memory_service

router = APIRouter(prefix="/api/memories", tags=["memories"])

# The settings UI lists what is stored; it never needs more than this.
_MAX_LISTED = 200


@router.get("")
def list_memories(
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    rows = db.scalars(
        select(Memory)
        .where(Memory.user_id == user_id)
        .order_by(Memory.created_at.desc())
        .limit(_MAX_LISTED)
    )
    return [memory_service.serialize(row) for row in rows]


@router.delete("/{memory_id}")
def remove_memory(
    memory_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    # Scoped by user: a guessed id from another user is a 404, not a delete.
    memory = db.scalar(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found for this user.")
    db.delete(memory)
    db.commit()
    return {"deleted": True, "memory_id": memory_id}
