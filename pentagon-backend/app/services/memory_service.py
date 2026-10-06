"""remember/recall: one table, deterministic retrieval, honest limits.

Memories are stored and recalled exactly as written -- no embedding call, no
re-ranking model. ``search_memories`` scores the user's own rows by keyword
overlap against the query (recency breaks ties), which is deterministic
enough to test line by line and cheap enough to run on every ``recall`` call.
Limits are part of the contract: a memory is short, a user has a bounded
number of them, and running out says so instead of silently dropping the
oldest fact.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Memory

MAX_MEMORY_CHARS = 2_000
MAX_LABEL_CHARS = 120
MAX_MEMORIES_PER_USER = 500
DEFAULT_RECALL_LIMIT = 5
MAX_RECALL_LIMIT = 20

# Three-plus characters, so tiny stop-words cannot score a hit on their own.
_WORDS = re.compile(r"[a-z0-9]{3,}")


class MemoryLimitError(RuntimeError):
    """The user's memory store is full; nothing was written."""


def store_memory(
    db: Session, *, user_id: str, text: str, label: str = ""
) -> tuple[Memory, bool]:
    """Persist one memory. Returns (memory, created) -- storing the exact
    same text again returns the existing row instead of duplicating it."""
    text = text.strip()
    existing = db.scalar(
        select(Memory).where(Memory.user_id == user_id, Memory.text == text)
    )
    if existing is not None:
        return existing, False
    count = len(
        db.scalars(select(Memory.id).where(Memory.user_id == user_id)).all()
    )
    if count >= MAX_MEMORIES_PER_USER:
        raise MemoryLimitError(
            f"memory is full: {MAX_MEMORIES_PER_USER} entries per user"
        )
    memory = Memory(user_id=user_id, label=label.strip()[:MAX_LABEL_CHARS], text=text)
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory, True


def search_memories(
    db: Session, *, user_id: str, query: str, limit: int = DEFAULT_RECALL_LIMIT
) -> list[Memory]:
    """The user's memories that share words with ``query``, best first.

    Score = number of distinct query terms that appear as whole words in the
    memory's text or label; ties go to the most recent. An empty term set
    matches nothing rather than dumping the whole store into a turn.
    """
    terms = set(_WORDS.findall(query.lower()))
    if not terms:
        return []
    rows = db.scalars(
        select(Memory)
        .where(Memory.user_id == user_id)
        .order_by(Memory.created_at.desc())
        .limit(MAX_MEMORIES_PER_USER)
    )
    scored: list[tuple[int, float, Memory]] = []
    for row in rows:
        words = set(_WORDS.findall(row.text.lower())) | set(
            _WORDS.findall(row.label.lower())
        )
        hits = len(terms & words)
        if hits:
            scored.append((hits, row.created_at.timestamp(), row))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    return [row for _, _, row in scored[:limit]]


def serialize(memory: Memory) -> dict[str, object]:
    """The shape both the tool envelope and the HTTP route return."""
    return {
        "id": memory.id,
        "label": memory.label,
        "text": memory.text,
        "created_at": memory.created_at.isoformat(),
    }
