"""Where a collection's vectors live, and how they disappear.

Chroma has no row-level security either, so isolation is by naming: one
Chroma collection per collection, derived from its id, never from anything a
request supplies. The name is deterministic so a reindex can find its own
store and a delete can be sure it removed the right one.

The single ``PersistentClient`` is shared with the base app's document store:
two clients on one persist directory would be two views of the same files.
"""

from __future__ import annotations

import logging

from app.services.document_store import _client  # one client per persist path

logger = logging.getLogger(__name__)

_PREFIX = "ragcol_"


def chroma_collection_name(collection_id: str) -> str:
    """Chroma's own constraints apply (3-63 chars, no path separators), hence
    the hex form: a uuid's dashes are stripped so the name is 38 safe chars."""
    return f"{_PREFIX}{collection_id.replace('-', '')}"


def _get(name: str):
    client = _client()
    names = {item.name if hasattr(item, "name") else str(item) for item in client.list_collections()}
    if name not in names:
        return None
    return client.get_collection(name=name, embedding_function=None)


def collection_vectors(collection_id: str):
    """The Chroma collection for one Pentagon collection, or None if absent."""
    return _get(chroma_collection_name(collection_id))


def purge_collection_vectors(collection_id: str) -> bool:
    """Delete the collection's vectors. True when anything was removed.

    Called on collection deletion: chunks, vectors, keyword cache and graph
    rows all go together, or a "deleted" collection would keep serving text
    from disk (RAG §14.2).
    """
    name = chroma_collection_name(collection_id)
    if _get(name) is None:
        return False
    try:
        _client().delete_collection(name)
    except Exception as exc:  # pragma: no cover - chroma internal failure
        logger.warning("Could not delete vector store %s (%s)", name, type(exc).__name__)
        return False
    logger.info("Purged vector store %s", name)
    return True
