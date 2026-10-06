"""T11: memory stores, recalls deterministically, and isolates its users.

Every stored text carries a uuid so a rerun of the suite never collides with
a previous run's dedupe; the ranking, isolation and route rules are asserted
line by line.
"""

import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agent.schemas import ToolContext
from app.db.models import User
from app.db.session import SessionLocal
from app.main import app
from app.services import memory_service
from app.tools import recall, remember

client = TestClient(app)


@pytest.fixture(autouse=True)
def _users():
    """FK rows for both users in every test of this file."""
    with SessionLocal() as db:
        for user_id in ("mem-user", "mem-other", "mem-full"):
            if db.get(User, user_id) is None:
                db.add(User(id=user_id))
        db.commit()
    yield


def _ctx(user_id: str = "mem-user") -> ToolContext:
    return ToolContext(
        user_id=user_id,
        conversation_id="c",
        turn_id="t",
        permission_level=2,
    )


def _remember(text: str, user_id: str = "mem-user", label: str = "") -> object:
    args: dict = {"text": text}
    if label:
        args["label"] = label
    return asyncio.run(remember.run(args, _ctx(user_id)))


def _recall(query: str, user_id: str = "mem-user", **extra) -> object:
    return asyncio.run(recall.run({"query": query, **extra}, _ctx(user_id)))


# --- remember -----------------------------------------------------------------


def test_remember_stores_then_dedupes_the_identical_text():
    text = f"Prefers metric units ({uuid4()})"
    first = _remember(text, label="preference")
    assert first.ok is True
    assert first.data["stored"] is True
    assert first.data["label"] == "preference"
    assert first.data["id"]
    again = _remember(text)
    assert again.ok is True
    assert again.data["stored"] is False
    assert again.data["id"] == first.data["id"]
    assert "already existed" in again.data["note"]


def test_remember_validates_its_arguments():
    for args in ({"text": ""}, {"text": "   "}, {"text": 42}):
        result = asyncio.run(remember.run(args, _ctx()))
        assert result.ok is False, args
        assert result.error.code == "INVALID_ARGS"
    too_long = "x" * (memory_service.MAX_MEMORY_CHARS + 1)
    result = _remember(too_long)
    assert result.ok is False and result.error.code == "INVALID_ARGS"
    result = asyncio.run(
        remember.run({"text": "fine", "label": 7}, _ctx())
    )
    assert result.ok is False and result.error.code == "INVALID_ARGS"


def test_remember_is_approval_gated_write_tier():
    assert remember.TOOL_SPEC.tier == "write"
    assert recall.TOOL_SPEC.tier == "read"


def test_a_full_store_says_so_instead_of_dropping_silently(monkeypatch):
    monkeypatch.setattr(memory_service, "MAX_MEMORIES_PER_USER", 1)
    # A fresh user: the limit is about this store, not rows other tests wrote.
    assert _remember(f"only one ({uuid4()})", user_id="mem-full").ok is True
    result = _remember(f"nowhere to go ({uuid4()})", user_id="mem-full")
    assert result.ok is False
    assert result.error.code == "UPSTREAM"
    assert "Settings" in result.error.hint


# --- recall -------------------------------------------------------------------


def test_recall_ranks_by_overlap_and_isolates_users():
    mine = f"A/B testing framework in Go ({uuid4()})"
    other = f"A/B testing framework in Rust ({uuid4()})"
    _remember(mine, label="project")
    _remember(other, user_id="mem-other")

    result = _recall("testing framework")
    assert result.ok is True
    assert result.data["count"] >= 1
    assert result.data["memories"][0]["text"] == mine
    # The other user's row never leaks into this user's recall.
    assert all(m["text"] != other for m in result.data["memories"])

    theirs = _recall("testing framework", user_id="mem-other")
    assert theirs.data["memories"][0]["text"] == other
    assert all(m["text"] != mine for m in theirs.data["memories"])


def test_recall_breaks_ties_with_recency():
    tag = uuid4()
    older = _remember(f"standup is at nine ({tag})").data["id"]
    newer = _remember(f"standup moved to ten ({tag})").data["id"]
    result = _recall("standup")
    ids = [m["id"] for m in result.data["memories"]]
    assert newer in ids and older in ids
    assert ids.index(newer) < ids.index(older)


def test_recall_returns_nothing_for_no_match_and_rejects_bad_args():
    result = _recall(f"zzzqqq{uuid4()}")
    assert result.ok is True
    assert result.data["count"] == 0
    assert result.data["memories"] == []
    for args in ({"query": ""}, {"query": "   "}, {"query": 42}):
        bad = asyncio.run(recall.run(args, _ctx()))
        assert bad.ok is False, args
        assert bad.error.code == "INVALID_ARGS"
    for limit in (0, 999, "5", True):
        bad = _recall("standup", limit=limit)
        assert bad.ok is False, limit
        assert bad.error.code == "INVALID_ARGS"


# --- the settings UI's route ---------------------------------------------------


def test_route_lists_and_deletes_only_your_own_memories():
    text = f"removable fact ({uuid4()})"
    stored = _remember(text, label="temp")
    memory_id = stored.data["id"]

    listing = client.get("/api/memories", params={"user_id": "mem-user"})
    assert listing.status_code == 200
    assert any(row["id"] == memory_id for row in listing.json())

    # Another user guessing the id gets a 404, not a deletion.
    wrong_user = client.delete(
        f"/api/memories/{memory_id}", params={"user_id": "mem-other"}
    )
    assert wrong_user.status_code == 404

    deleted = client.delete(
        f"/api/memories/{memory_id}", params={"user_id": "mem-user"}
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    after = client.get("/api/memories", params={"user_id": "mem-user"})
    assert all(row["id"] != memory_id for row in after.json())

    missing = client.delete(
        f"/api/memories/{memory_id}", params={"user_id": "mem-user"}
    )
    assert missing.status_code == 404
